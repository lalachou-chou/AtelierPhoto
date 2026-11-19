"""Retouches locales : réglages photographiques appliqués dans une zone détectée.

Aucun pixel n'est inventé. Chaque retouche locale combine :

* une zone, produit d'un ou plusieurs masques doux (ciel, peau, sujet, fond,
  plage de couleur, plage de tons, dégradé géométrique), éventuellement inversée ;
* des réglages identiques aux curseurs globaux (exposition, température,
  contraste, saturation), mélangés à l'image selon le masque.

Les zones qui demandent une vue d'ensemble (ciel, peau, sujet) sont estimées
sur une copie réduite de la photo développée, puis affinées pixel par pixel à
pleine résolution. L'aperçu et l'export obtiennent donc le même masque, quelle
que soit la définition traitée. Les zones de couleur, de tons et de géométrie
sont calculées directement pour chaque pixel.
"""
import numpy as np
from PIL import Image

PROXY = 384
LUMA = np.array([.2126, .7152, .0722], dtype=np.float32)

# Teinte centrale (degrés) et demi-largeur de chaque plage de couleur.
COLORS = {
    "rouges": (0., 28.), "oranges": (30., 20.), "jaunes": (58., 22.), "verts": (115., 48.),
    "cyans": (180., 25.), "bleus": (222., 35.), "violets": (272., 28.), "magentas": (318., 30.),
    "eau": (200., 45.),
}
TONES = ("ombres", "tons_moyens", "hautes_lumieres")
GEOMETRY = ("haut", "bas", "gauche", "droite", "centre", "bords")
REGIONS = ("ciel", "peau", "sujet", "fond")

ZONE_LABELS = {
    "image": "toute l’image", "ciel": "ciel", "peau": "peau", "sujet": "sujet (estimé)", "fond": "fond (estimé)",
    "rouges": "rouges", "oranges": "oranges", "jaunes": "jaunes", "verts": "verts", "cyans": "turquoises",
    "bleus": "bleus", "violets": "violets", "magentas": "magentas et roses", "eau": "eau (bleus et turquoises)",
    "ombres": "ombres", "tons_moyens": "tons moyens", "hautes_lumieres": "hautes lumières",
    "haut": "haut de l’image", "bas": "bas de l’image", "gauche": "côté gauche", "droite": "côté droit",
    "centre": "centre", "bords": "bords",
}
ZONES = tuple(ZONE_LABELS)

# Bornes de chaque réglage local ; mêmes unités que les curseurs globaux.
ADJUSTMENTS = {"exposure": (-2., 2.), "temperature": (-1.2, 1.2), "contrast": (-.6, .6), "saturation": (-1., 1.),
               "clarity": (-1., 1.), "hue": (-1., 1.)}


def active(edits):
    """Retouches locales activées et effectives."""
    return [e for e in edits or () if e.get("enabled", True) and e.get("strength", 1.) > 0
            and any(abs(e.get(k, 0.)) > 1e-6 for k in ADJUSTMENTS)]


def applied(edits, batch_filter=True):
    """Retouches rendues : les propositions apprises suivent la retouche du lot, les consignes restent."""
    return [e for e in active(edits) if batch_filter or not e.get("proposed")]


def amounts(edit):
    strength = float(edit.get("strength", 1.))
    return {k: float(np.clip(edit.get(k, 0.) * strength, *bounds)) for k, bounds in ADJUSTMENTS.items()}


# ---------------------------------------------------------------- outils


def _smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0., 1.)
    return t * t * (3 - 2 * t)


def _box(a, radius, axis):
    if radius < 1:
        return a
    width = [(radius + 1, radius) if ax == axis else (0, 0) for ax in range(a.ndim)]
    total = np.cumsum(np.pad(a, width, mode="edge"), axis=axis, dtype=np.float64)
    n = a.shape[axis]
    upper = np.take(total, np.arange(2 * radius + 1, 2 * radius + 1 + n), axis=axis)
    lower = np.take(total, np.arange(n), axis=axis)
    return ((upper - lower) / (2 * radius + 1)).astype(np.float32)


def blur(a, radius):
    """Flou quasi gaussien : trois flous en boîte séparables."""
    radius = int(round(radius))
    for _ in range(3):
        a = _box(_box(a, radius, 0), radius, 1)
    return a


def _hsv(x):
    maximum, minimum = x.max(-1), x.min(-1)
    chroma = maximum - minimum
    safe = np.where(chroma > 1e-6, chroma, 1.)
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    hue = np.where(maximum == r, ((g - b) / safe) % 6,
                   np.where(maximum == g, (b - r) / safe + 2, (r - g) / safe + 4)) * 60
    saturation = np.where(maximum > 1e-6, chroma / np.maximum(maximum, 1e-6), 0.)
    return hue, saturation, maximum


def _luma(x):
    return x @ LUMA


def _hue_weight(x, center, half_width):
    hue, saturation, value = _hsv(x)
    distance = np.abs((hue - center + 180.) % 360. - 180.)
    return ((1 - _smooth(half_width * .5, half_width, distance)) * _smooth(.06, .2, saturation)
            * _smooth(.03, .1, value)).astype(np.float32)


def _tone_weight(x, tone):
    luma = _luma(x)
    if tone == "ombres":
        return (1 - _smooth(.12, .45, luma)).astype(np.float32)
    if tone == "hautes_lumieres":
        return _smooth(.55, .85, luma).astype(np.float32)
    return (1 - _smooth(.15, .38, np.abs(luma - .5))).astype(np.float32)


def _skin_weight(x):
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    y = .299 * r + .587 * g + .114 * b
    cb = .5 - .168736 * r - .331264 * g + .5 * b
    cr = .5 + .5 * r - .418688 * g - .081312 * b
    distance = ((cb - .40) / .09) ** 2 + ((cr - .60) / .075) ** 2
    return ((1 - _smooth(.55, 1., distance)) * _smooth(.1, .22, y) * (1 - _smooth(.95, 1., y))).astype(np.float32)


def _sky_candidate(x):
    hue, saturation, value = _hsv(x)
    distance = np.abs((hue - 212. + 180.) % 360. - 180.)
    blue = (1 - _smooth(25., 50., distance)) * _smooth(.06, .18, saturation) * _smooth(.25, .45, value)
    overcast = _smooth(.62, .82, _luma(x)) * (1 - _smooth(.1, .22, saturation))
    return np.maximum(blue, overcast).astype(np.float32)


def _geometry(kind, rows, columns):
    """Dégradés doux en coordonnées normalisées (lignes, colonnes dans [0, 1])."""
    v, u = rows[:, None], columns[None, :]
    if kind == "haut":
        m = 1 - _smooth(.1, .6, v) + 0 * u
    elif kind == "bas":
        m = _smooth(.4, .9, v) + 0 * u
    elif kind == "gauche":
        m = 1 - _smooth(.1, .6, u) + 0 * v
    elif kind == "droite":
        m = _smooth(.4, .9, u) + 0 * v
    else:
        radius = np.sqrt((2 * u - 1) ** 2 + (2 * v - 1) ** 2)
        m = 1 - _smooth(.35, .95, radius) if kind == "centre" else _smooth(.55, 1.3, radius)
    return m.astype(np.float32)


def _otsu(values):
    histogram, edges = np.histogram(values, bins=64)
    centers = (edges[:-1] + edges[1:]) / 2
    weight = np.cumsum(histogram)
    total = weight[-1]
    mean = np.cumsum(histogram * centers)
    between = (mean[-1] * weight - mean * total) ** 2 / np.maximum(weight * (total - weight), 1)
    return float(centers[int(np.argmax(between[:-1]))])


# ------------------------------------------------- zones estimées sur l'aperçu réduit


def proxy(pixels):
    """Copie réduite (côté maximal PROXY) utilisée pour estimer les zones."""
    height, width = pixels.shape[:2]
    scale = min(1., PROXY / max(height, width))
    if scale >= 1.:
        return np.asarray(pixels, dtype=np.float32)
    size = (max(8, round(width * scale)), max(8, round(height * scale)))
    image = Image.fromarray(np.round(np.clip(pixels, 0, 1) * 255).astype(np.uint8))
    return np.asarray(image.resize(size, Image.Resampling.BOX), dtype=np.float32) / 255


def _sky_region(small):
    height, width = small.shape[:2]
    luma = blur(_luma(small), 1)
    texture = blur(np.abs(np.diff(luma, axis=0, prepend=luma[:1])) + np.abs(np.diff(luma, axis=1, prepend=luma[:, :1])), 1)
    seeds = (_sky_candidate(small) * (1 - _smooth(.025, .07, texture))) > .5
    reach = np.zeros_like(seeds)
    reach[0] = seeds[0]
    for i in range(1, height):
        above = reach[i - 1].copy()
        above[1:] |= reach[i - 1][:-1]
        above[:-1] |= reach[i - 1][1:]
        row = seeds[i]
        starts = row & ~np.r_[False, row[:-1]]
        labels = np.cumsum(starts) * row
        touched = np.unique(labels[row & above])
        reach[i] = row & np.isin(labels, touched[touched > 0])
    if reach.mean() < .01:
        return np.zeros((height, width), dtype=np.float32), None
    region = np.clip(blur(reach.astype(np.float32), max(1, width // 120)) * 1.8, 0, 1)
    return region, small[reach].mean(0)


def _skin_region(small):
    core = blur(_skin_weight(small), 1) > .5
    if core.mean() < .002:
        return np.zeros(small.shape[:2], dtype=np.float32)
    return np.clip(blur(core.astype(np.float32), max(1, small.shape[1] // 100)) * 2.5, 0, 1)


def _subject_region(small):
    """Sujet estimé : contraste de couleur avec les bords, détails nets, position centrale."""
    height, width = small.shape[:2]
    soft = np.stack([blur(small[..., c], 1) for c in range(3)], -1)
    band = max(2, round(min(height, width) * .06))
    border = np.concatenate([soft[:band].reshape(-1, 3), soft[-band:].reshape(-1, 3),
                             soft[:, :band].reshape(-1, 3), soft[:, -band:].reshape(-1, 3)])
    samples = border[np.linspace(0, len(border) - 1, 48).astype(int)]
    distance = np.full((height, width), np.inf, dtype=np.float32)
    for color in samples:
        distance = np.minimum(distance, np.linalg.norm(soft - color, axis=-1))
    distance /= max(float(np.quantile(distance, .97)), 1e-3)
    luma = _luma(soft)
    laplacian = np.abs(-4 * luma + np.roll(luma, 1, 0) + np.roll(luma, -1, 0) + np.roll(luma, 1, 1) + np.roll(luma, -1, 1))
    laplacian[[0, -1]] = 0
    laplacian[:, [0, -1]] = 0
    sharp = blur(laplacian, max(2, width // 60))
    sharp /= max(float(np.quantile(sharp, .97)), 1e-4)
    v, u = np.linspace(0, 1, height)[:, None], np.linspace(0, 1, width)[None, :]
    center = np.exp(-((u - .5) ** 2 / (2 * .28 ** 2) + (v - .55) ** 2 / (2 * .32 ** 2)))
    saliency = blur((.55 * np.clip(distance, 0, 1) + .45 * np.clip(sharp, 0, 1)) * (.35 + .65 * center), max(2, width // 80))
    # Les pixels de même couleur que les bords appartiennent au fond, même près du sujet.
    binary = (saliency > _otsu(saliency)) & (distance > .2)
    # Fermeture douce : bouche les trous du sujet sans élargir sa silhouette.
    closed = blur(binary.astype(np.float32), max(1, width // 120)) > .5
    return np.clip(guided(soft, closed.astype(np.float32), max(2, width // 90)), 0, 1).astype(np.float32)


def guided(guide, mask, radius, epsilon=2e-3):
    """Filtre guidé (He et al.) : le bord du masque suit les contours de la photo, sans halo."""
    image = _luma(guide).astype(np.float32)
    mean = lambda a: _box(_box(a, radius, 0), radius, 1)  # noqa: E731
    mean_i, mean_p = mean(image), mean(mask)
    variance = mean(image * image) - mean_i ** 2
    a = (mean(image * mask) - mean_i * mean_p) / (variance + epsilon)
    b = mean_p - a * mean_i
    return mean(a) * image + mean(b)


def _upsample(low, start, count, shape):
    """Interpolation bilinéaire d'une bande de lignes d'un masque réduit."""
    height, width = shape[:2]
    lh, lw = low.shape
    y = np.clip((np.arange(start, start + count) + .5) * lh / height - .5, 0, lh - 1)
    x = np.clip((np.arange(width) + .5) * lw / width - .5, 0, lw - 1)
    y0, x0 = np.floor(y).astype(int), np.floor(x).astype(int)
    y1, x1 = np.minimum(y0 + 1, lh - 1), np.minimum(x0 + 1, lw - 1)
    fy, fx = (y - y0)[:, None].astype(np.float32), (x - x0)[None, :].astype(np.float32)
    top = low[y0][:, x0] * (1 - fx) + low[y0][:, x1] * fx
    bottom = low[y1][:, x0] * (1 - fx) + low[y1][:, x1] * fx
    return top * (1 - fy) + bottom * fy


# ------------------------------------------------------- préparation et rendu


class Zone:
    """Masque d'une zone : régional (estimé sur l'aperçu réduit) et/ou par pixel."""

    def __init__(self, kind, small):
        self.kind = kind
        self.region = None
        self.reference = None
        if kind == "ciel":
            self.region, self.reference = _sky_region(small)
        elif kind == "peau":
            self.region = _skin_region(small)
        elif kind in ("sujet", "fond"):
            self.region = _subject_region(small)

    def pixels(self, x, start, shape):
        """Masque pour la bande ``x`` commençant à la ligne ``start`` d'une image ``shape``."""
        kind = self.kind
        if kind == "image":
            return np.ones(x.shape[:2], dtype=np.float32)
        if kind in COLORS:
            return _hue_weight(x, *COLORS[kind])
        if kind in TONES:
            return _tone_weight(x, kind)
        if kind in GEOMETRY:
            height, width = shape[:2]
            rows = (np.arange(start, start + x.shape[0]) + .5) / height
            return _geometry(kind, rows, (np.arange(width) + .5) / width)
        region = _upsample(self.region, start, x.shape[0], shape)
        if kind == "ciel":
            if self.reference is None:
                return region
            similar = np.exp(-np.sum((x - self.reference) ** 2, axis=-1) / (2 * .12 ** 2))
            return region * np.maximum(_sky_candidate(x), similar).astype(np.float32)
        if kind == "peau":
            return region * _skin_weight(x)
        return 1 - region if kind == "fond" else region


class Prepared:
    def __init__(self, edit, small):
        kinds = [z for z in edit.get("zones") or ["image"] if z in ZONE_LABELS] or ["image"]
        self.zones = [Zone(kind, small) for kind in kinds]
        self.invert = bool(edit.get("invert"))
        self.amounts = amounts(edit)
        weight = self.mask(small, 0, small.shape)
        self.coverage = float(weight.mean())
        luma = _luma(small)
        self.pivot = float((weight * luma).sum() / weight.sum()) if weight.sum() > 1e-3 else .5

    def mask(self, x, start, shape):
        weight = np.ones(x.shape[:2], dtype=np.float32)
        for zone in self.zones:
            weight *= zone.pixels(x, start, shape)
        return 1 - weight if self.invert else weight


def prepare(edits, developed_proxy):
    """Masques régionaux et pivots, estimés une fois par photo et par rendu."""
    return [Prepared(e, developed_proxy) for e in active(edits)]


def coverage(edits, pixels):
    """Part de l'image (0 à 1) touchée par chaque retouche ; utile pour signaler une zone introuvable."""
    small = proxy(pixels)
    return [p.coverage for p in prepare(edits, small)]


def adjust(x, values, pivot, detail=None):
    y = x
    if values.get("clarity") and detail is not None:
        from .tools import clarity
        y = clarity(y, detail, values["clarity"])
    y = y * np.float32(2 ** values["exposure"])
    warmth = values["temperature"]
    if warmth:
        y = y * np.array([1 + warmth * .12, 1., 1 - warmth * .12], dtype=np.float32)
    if values["contrast"]:
        y = (y - pivot) * (1 + values["contrast"]) + pivot
    if values["saturation"]:
        luma = (y @ LUMA)[..., None]
        y = luma + (y - luma) * (1 + values["saturation"])
    if values.get("hue"):
        # Rotation de teinte (1 = 30°), comme la teinte locale de Lightroom.
        from .tools import COLORS as HSL_COLORS
        from .tools import apply_hsl, identity
        rotation = identity()
        rotation["hsl"] = {c: [values["hue"], 0., 0.] for c in HSL_COLORS}
        y = apply_hsl(y, rotation)
    return y


def apply(x, start, shape, prepared, detail=None):
    """Applique les retouches locales préparées à une bande de pixels développés.

    ``detail`` est le détail local de la bande (voir tools.detail), utilisé par la clarté.
    """
    for item in prepared:
        weight = item.mask(x, start, shape)
        if not weight.any():
            continue
        selected = weight > 1e-3
        if selected.mean() < .6:
            # Zone partielle : réglages calculés seulement sur ses pixels.
            x = np.array(x, dtype=np.float32, copy=True)
            part = x[selected]
            changed = adjust(part, item.amounts, item.pivot, None if detail is None else detail[selected])
            x[selected] = part + weight[selected][:, None] * (changed - part)
        else:
            x = x + weight[..., None] * (adjust(x, item.amounts, item.pivot, detail) - x)
    return x


# ------------------------------------------------------------ apprentissage


def signature(edit):
    """Même zone, même sens de réglage : deux retouches comparables entre photos."""
    signs = [int(np.sign(round(edit.get(k, 0.), 3))) for k in ADJUSTMENTS]
    # Clarté et teinte sont venues après : sans elles, la signature reste celle déjà enregistrée.
    while len(signs) > 4 and not signs[-1]:
        signs.pop()
    return [sorted(edit.get("zones") or ["image"]), bool(edit.get("invert")), list(signs)]


def lessons(edits, initial=(), batch_filter=True):
    """Retouches à apprendre et propositions refusées, lues au moment de la validation.

    Une proposition gardée telle quelle n'apprend rien de nouveau ; modifiée, elle
    est apprise avec sa nouvelle intensité. Une proposition retirée ou décochée
    est mémorisée comme refus pour les photos similaires.
    """
    if not batch_filter:
        edits = [e for e in edits or () if not e.get("proposed")]
        initial = ()
    kept = {e["id"]: e for e in active(edits)}
    learned = []
    for edit in kept.values():
        if edit.get("proposed") and abs(edit.get("strength", 1.) - 1.) < 1e-6:
            continue
        values = amounts(edit)
        learned.append({"zones": list(edit.get("zones") or ["image"]), "invert": bool(edit.get("invert")),
                        **{k: round(v, 4) for k, v in values.items()}})
    refused = [signature(e) for e in initial or () if e["id"] not in kept]
    return learned, refused


def suggest(neighbours):
    """Retouches proposées d'après les photos validées similaires ``[(correction, similarité)]``.

    Chaque voisin vote pour les retouches qu'il a gardées et contre celles qu'il a
    refusées, avec le poids de sa ressemblance. Une retouche n'est proposée que si
    les votes pour l'emportent ; ses réglages sont la moyenne pondérée des exemples.
    """
    votes = {}
    for correction, similarity in neighbours:
        weight = similarity ** 6
        for edit in correction.get("local", []):
            key = repr(signature(edit))
            entry = votes.setdefault(key, {"for": 0., "against": 0., "examples": []})
            entry["for"] += weight
            entry["examples"].append((edit, weight))
        for refused in correction.get("local_refused", []):
            votes.setdefault(repr(refused), {"for": 0., "against": 0., "examples": []})["against"] += weight
    proposals = []
    for entry in votes.values():
        if not entry["examples"] or entry["for"] <= entry["against"]:
            continue
        examples = entry["examples"]
        total = sum(w for _, w in examples)
        model = examples[0][0]
        edit = {"zones": list(model["zones"]), "invert": bool(model.get("invert"))}
        edit.update({k: float(sum(e.get(k, 0.) * w for e, w in examples) / total) for k in ADJUSTMENTS})
        proposals.append(edit)
    return proposals
