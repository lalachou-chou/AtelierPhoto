"""Outils de retouche avancés : clarté, courbe des tons et TSL (teinte, saturation, luminance).

Ils s'appliquent à toute l'image, comme les curseurs globaux, et dans le même
ordre que Lightroom : clarté sur l'image d'entrée, puis courbe après le
contraste, puis TSL après la saturation. Les valeurs suivent l'échelle de
Lightroom divisée par 100 (-1..1), ce qui rend l'échange par XMP direct.

Format enregistré dans ``data["tools"]`` :
``{"clarity": c, "curve": {"shadows", "darks", "lights", "highlights"},
"hsl": {"rouges": [teinte, saturation, luminance], ...},
"points": {"master"|"red"|"green"|"blue": [[x, y], ...]}}`` (points 0..1, lus
d'un XMP de référence ; facultatif).
"""
import numpy as np
from PIL import Image

COLORS = ("rouges", "oranges", "jaunes", "verts", "cyans", "bleus", "violets", "magentas")
COLOR_LABELS = ("Rouges", "Oranges", "Jaunes", "Verts", "Turquoises", "Bleus", "Violets", "Magentas")
ADOBE_COLORS = ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta")
# Centres des couleurs de Lightroom, en degrés.
HUES = np.array([0., 30., 60., 120., 180., 240., 270., 300.], dtype=np.float32)
CURVE = ("shadows", "darks", "lights", "highlights")
CURVE_LABELS = ("Ombres", "Tons sombres", "Tons clairs", "Hautes lumières")
CHANNELS = ("master", "red", "green", "blue")
LUMA = np.array([.2126, .7152, .0722], dtype=np.float32)
BASE = 768
HUE_RANGE = 30.


def identity():
    return {"clarity": 0., "curve": {k: 0. for k in CURVE}, "hsl": {c: [0., 0., 0.] for c in COLORS}}


def _clip(value):
    try:
        return float(np.clip(float(value), -1., 1.))
    except (TypeError, ValueError):
        return 0.


def normalize(tools):
    """Copie complète et bornée ; tolère des données partielles ou anciennes."""
    tools = tools or {}
    result = identity()
    result["clarity"] = _clip(tools.get("clarity", 0.))
    for key in CURVE:
        result["curve"][key] = _clip((tools.get("curve") or {}).get(key, 0.))
    for color in COLORS:
        values = list((tools.get("hsl") or {}).get(color, ())) + [0., 0., 0.]
        result["hsl"][color] = [_clip(v) for v in values[:3]]
    points = {}
    for channel, curve in (tools.get("points") or {}).items():
        if channel in CHANNELS and curve:
            pairs = sorted((float(np.clip(x, 0, 1)), float(np.clip(y, 0, 1))) for x, y in curve)
            if len(pairs) >= 2 and any(abs(x - y) > 1e-3 for x, y in pairs):
                points[channel] = [list(p) for p in pairs]
    if points:
        result["points"] = points
    return result


def is_identity(tools):
    t = normalize(tools)
    return (not t["clarity"] and not any(t["curve"].values())
            and not any(any(v) for v in t["hsl"].values()) and not t.get("points"))


def difference(tools, initial):
    """Outils moins la proposition du profil : ce que la photographe a réglé elle-même."""
    t, i = normalize(tools), normalize(initial)
    result = identity()
    result["clarity"] = _clip(t["clarity"] - i["clarity"])
    for key in CURVE:
        result["curve"][key] = _clip(t["curve"][key] - i["curve"][key])
    for color in COLORS:
        result["hsl"][color] = [_clip(a - b) for a, b in zip(t["hsl"][color], i["hsl"][color], strict=True)]
    if t.get("points") and t.get("points") != i.get("points"):
        result["points"] = t["points"]
    return result


def active(data, batch_filter=True):
    """Outils appliqués : tous avec la retouche du lot, sinon les seuls réglages manuels."""
    tools = data.get("tools")
    if not tools:
        return None
    if not batch_filter:
        tools = difference(tools, data.get("initial_tools"))
    return None if is_identity(tools) else normalize(tools)


def mean(weighted):
    """Moyenne pondérée de réglages d'outils [(outils, poids)], pour l'apprentissage."""
    if not weighted:
        return None
    total = sum(w for _, w in weighted)
    result = identity()
    for tools, weight in weighted:
        t = normalize(tools)
        share = weight / total
        result["clarity"] += t["clarity"] * share
        for key in CURVE:
            result["curve"][key] += t["curve"][key] * share
        for color in COLORS:
            result["hsl"][color] = [a + b * share for a, b in zip(result["hsl"][color], t["hsl"][color], strict=True)]
    return None if is_identity(result) else normalize(result)


def describe(tools):
    """Résumé lisible des outils actifs."""
    t = normalize(tools)
    parts = []
    if t["clarity"]:
        parts.append(f"clarté {t['clarity'] * 100:+.0f}")
    curve = [f"{label.lower()} {t['curve'][k] * 100:+.0f}" for k, label in zip(CURVE, CURVE_LABELS, strict=True)
             if t["curve"][k]]
    if curve:
        parts.append("courbe (" + ", ".join(curve) + ")")
    if t.get("points"):
        parts.append("courbe par points")
    for color, label in zip(COLORS, COLOR_LABELS, strict=True):
        values = t["hsl"][color]
        if any(values):
            changes = [f"{name} {v * 100:+.0f}" for name, v in zip(("T", "S", "L"), values, strict=True) if v]
            parts.append(f"{label.lower()} " + " ".join(changes))
    return ", ".join(parts)


# ------------------------------------------------------------------ clarté


def needs_base(tools, local=None):
    return bool((tools and tools.get("clarity")) or any(e.get("clarity") for e in (local or ())))


def base(pixels):
    """Luminance floutée de l'image d'entrée, estimée sur une copie réduite.

    Le rayon est relatif au cadre : l'aperçu et l'export à pleine définition
    obtiennent donc le même effet de clarté.
    """
    from .local import blur
    height, width = pixels.shape[:2]
    scale = min(1., BASE / max(height, width))
    if scale < 1.:
        size = (max(8, round(width * scale)), max(8, round(height * scale)))
        image = Image.fromarray(np.round(np.clip(pixels, 0, 1) * 255).astype(np.uint8))
        small = np.asarray(image.resize(size, Image.Resampling.BOX), dtype=np.float32) / 255
    else:
        small = np.asarray(pixels, dtype=np.float32)
    luma = small @ LUMA
    return blur(luma, max(1, round(max(luma.shape) * .012)))


def detail(x, start, shape, low):
    """Détail local (luminance moins sa version floutée) d'une bande de lignes."""
    from .local import _upsample
    return (x @ LUMA) - _upsample(low, start, x.shape[0], shape)


def clarity(x, detail_band, amount):
    """Contraste local des tons moyens, sans changer la luminosité moyenne."""
    if not amount:
        return x
    luma = np.clip(x @ LUMA, 1e-4, None)
    midtones = 4 * np.clip(luma, 0, 1) * (1 - np.clip(luma, 0, 1))
    target = np.clip(luma + 1.2 * amount * detail_band * midtones, 0, None)
    return x * (target / luma)[..., None]


# ------------------------------------------------------------------ courbe


def _bump(x, center, width=.25):
    u = np.clip((x - center) / width, -1, 1)
    return (1 - u * u) ** 2


def _monotone(xs, ys, grid):
    """Interpolation cubique monotone (Fritsch-Carlson) d'une courbe par points."""
    xs, ys = np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)
    if len(xs) == 2:
        return np.interp(grid, xs, ys)
    h = np.diff(xs)
    h[h == 0] = 1e-6
    delta = np.diff(ys) / h
    m = np.zeros_like(xs)
    m[1:-1] = np.where(delta[:-1] * delta[1:] > 0, (delta[:-1] + delta[1:]) / 2, 0)
    m[0], m[-1] = delta[0], delta[-1]
    for i in range(len(delta)):
        if delta[i] == 0:
            m[i] = m[i + 1] = 0
        else:
            a, b = m[i] / delta[i], m[i + 1] / delta[i]
            s = a * a + b * b
            if s > 9:
                t = 3 / np.sqrt(s)
                m[i], m[i + 1] = t * a * delta[i], t * b * delta[i]
    index = np.clip(np.searchsorted(xs, grid) - 1, 0, len(xs) - 2)
    t = (grid - xs[index]) / h[index]
    h00, h10 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t
    h01, h11 = -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
    inside = h00 * ys[index] + h10 * h[index] * m[index] + h01 * ys[index + 1] + h11 * h[index] * m[index + 1]
    return np.where(grid < xs[0], ys[0], np.where(grid > xs[-1], ys[-1], inside))


def curve_tables(tools, size=4096):
    """Tables 0..1 → 0..1 : une table commune et, s'il y en a, une par canal."""
    if not tools:
        return None
    grid = np.linspace(0, 1, size)
    master = grid.copy()
    curve = tools["curve"]
    if any(curve.values()):
        for key, center in zip(CURVE, (.125, .375, .625, .875), strict=True):
            master = master + .12 * curve[key] * _bump(grid, center)
        master = np.maximum.accumulate(np.clip(master, 0, 1))
    points = tools.get("points") or {}
    if "master" in points:
        xs, ys = zip(*points["master"], strict=True)
        master = _monotone(xs, ys, master)
    channels = []
    for channel in ("red", "green", "blue"):
        if channel in points:
            xs, ys = zip(*points[channel], strict=True)
            channels.append(np.clip(_monotone(xs, ys, grid), 0, 1).astype(np.float32))
        else:
            channels.append(None)
    if np.allclose(master, grid) and not any(c is not None for c in channels):
        return None
    return np.clip(master, 0, 1).astype(np.float32), channels


def _lookup(x, table):
    """Interpolation linéaire dans une table régulière sur 0..1 (rapide, sans paliers)."""
    position = np.clip(x, 0, 1) * np.float32(len(table) - 1)
    index = np.minimum(position.astype(np.int32), len(table) - 2)
    fraction = position - index
    return table[index] + (table[index + 1] - table[index]) * fraction


def apply_curve(x, tables):
    if tables is None:
        return x
    master, channels = tables
    y = _lookup(x, master)
    for index, table in enumerate(channels):
        if table is not None:
            y[..., index] = _lookup(y[..., index], table)
    # Au-delà de 1 (avant écrêtage), la courbe se prolonge sans casser les hautes lumières.
    over = x > 1
    if over.any():
        y = np.where(over, y + (x - 1), y)
    return y.astype(np.float32, copy=False)


# --------------------------------------------------------------------- TSL

_CENTERS = np.append(HUES, 360.).astype(np.float32)


def hsl_active(tools):
    return bool(tools) and any(any(v) for v in tools["hsl"].values())


def apply_hsl(x, tools):
    """Teinte, saturation et luminance par couleur.

    Entre deux couleurs voisines de Lightroom, le réglage est interpolé
    linéairement selon la teinte du pixel : les huit poids forment une
    partition de l'unité, sans transition brutale.
    """
    if not hsl_active(tools):
        return x
    table = np.array([tools["hsl"][c] for c in COLORS] + [tools["hsl"][COLORS[0]]], dtype=np.float32)
    clipped = np.clip(x, 0, None)
    high, low = clipped.max(axis=-1), clipped.min(axis=-1)
    chroma = high - low
    colored = chroma > 1e-5
    if not colored.any():
        return x
    safe = np.where(colored, chroma, 1.)
    r, g, b = clipped[..., 0], clipped[..., 1], clipped[..., 2]
    hue = np.where(high == r, ((g - b) / safe) % 6, np.where(high == g, (b - r) / safe + 2, (r - g) / safe + 4)) * 60
    # Réglage interpolé tous les quarts de degré : une table remplace la recherche du segment.
    grid = np.arange(0, 360.25, .25, dtype=np.float32)
    lookup = np.stack([np.interp(grid, _CENTERS, table[:, i]) for i in range(3)], axis=-1).astype(np.float32)
    adjust = lookup[(hue * 4).astype(np.int32)]
    # Seuls les pixels des couleurs réglées sont recalculés.
    touched = colored & (np.abs(adjust).max(axis=-1) > 1e-6)
    if not touched.any():
        return x
    x = np.array(x, dtype=np.float32, copy=True)
    x[touched] = _hsl_pixels(hue[touched], chroma[touched], high[touched], adjust[touched])
    return x


def _hsl_pixels(hue, chroma, high, adjust):
    """Nouvelles couleurs RVB de pixels (tableaux 1D) d'après leur réglage TSL."""
    shift, saturation, lightness = adjust[..., 0], adjust[..., 1], adjust[..., 2]
    saturation_level = np.where(high > 1e-6, chroma / np.maximum(high, 1e-6), 0.)
    hue = (hue + shift * HUE_RANGE) % 360
    chroma = chroma * np.clip(1 + saturation, 0, 2)
    # La luminance ne touche que les pixels colorés ; les gris restent neutres.
    value = high * (1 + .5 * lightness * np.clip(saturation_level * 2, 0, 1))
    chroma = np.minimum(chroma, value)
    sector = hue / 60
    # Conversion TSV → RVB analytique : f(n) = V − C·max(0, min(k, 4 − k, 1)), k = (n + H/60) mod 6.
    channels = []
    for n in (5., 3., 1.):
        k = (n + sector) % 6
        channels.append(value - chroma * np.clip(np.minimum(k, 4 - k), 0, 1))
    return np.stack(channels, axis=-1).astype(np.float32, copy=False)
