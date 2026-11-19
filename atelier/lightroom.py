"""Retouches locales d'Atelier écrites comme masques Lightroom (XMP ``crs``).

Chaque retouche devient une correction de ``crs:MaskGroupBasedCorrections``
(Lightroom 11 et suivants, Camera Raw 14 et suivants) :

- position → dégradé linéaire (``Mask/Gradient``) ou radial (``Mask/CircularGradient``) ;
- ombres, tons moyens, hautes lumières → plage de luminance (``Mask/RangeMask``, type 2) ;
- couleurs, végétation, eau, peau → plage de couleur (type 1), avec la couleur
  échantillonnée sur la photo ;
- ciel, sujet → masques IA de Lightroom (``Mask/Image``), que Lightroom doit
  calculer lui-même ; fond = sujet inversé ;
- plusieurs zones → intersection des composants ; « sauf » → inversion.

Lightroom refait le rendu avec son propre moteur : le résultat est proche de
l'aperçu d'Atelier, pas identique. Le format suit la description publique du
XMP de Lightroom ; il n'est pas documenté par Adobe.
"""
import colorsys
import uuid
from xml.sax.saxutils import quoteattr

import numpy as np

from .local import COLORS, TONES, _hue_weight, _skin_weight, amounts

# Plages de luminance (trapèzes Lightroom) équivalentes aux tons d'Atelier.
LUMINANCE = {"ombres": (0., 0., .12, .45), "tons_moyens": (.12, .35, .65, .88), "hautes_lumieres": (.55, .85, 1., 1.)}
# Dégradés linéaires : (point d'effet nul, point d'effet complet) dans le cadre affiché.
LINEAR = {"haut": ((.5, .6), (.5, .1)), "bas": ((.5, .4), (.5, .9)),
          "gauche": ((.6, .5), (.1, .5)), "droite": ((.4, .5), (.9, .5))}
# Masques IA de Lightroom (« Sélectionner le sujet », « Sélectionner le ciel »).
AI_SUBTYPES = {"sujet": 1, "ciel": 2, "fond": 1}
# Zones traduites en plage de couleur, échantillonnée sur la photo.
SAMPLED = set(COLORS) | {"peau"}
ADD, SUBTRACT, INTERSECT = 0, 1, 2
LOCAL_DEFAULTS = ("LocalExposure2012", "LocalContrast2012", "LocalHighlights2012", "LocalShadows2012",
                  "LocalWhites2012", "LocalBlacks2012", "LocalClarity2012", "LocalTexture", "LocalDehaze",
                  "LocalTemperature", "LocalTint", "LocalSaturation", "LocalHue", "LocalSharpness",
                  "LocalLuminanceNoise", "LocalMoire", "LocalDefringe", "LocalToningHue",
                  "LocalToningSaturation")


def _identifier():
    return uuid.uuid4().hex.upper()


def _clip(value):
    return float(np.clip(value, -1., 1.))


def local_settings(edit):
    """Réglages d'une retouche d'Atelier sur l'échelle des corrections locales de Lightroom."""
    values = amounts(edit)
    settings = {key: 0. for key in LOCAL_DEFAULTS}
    settings.update({
        # Lightroom enregistre l'exposition locale en quarts d'IL (+2 IL = 0,5).
        "LocalExposure2012": _clip(values["exposure"] / 4),
        "LocalContrast2012": _clip(values["contrast"] / .5),
        "LocalTemperature": _clip(values["temperature"] * .4),
        "LocalSaturation": _clip(values["saturation"]),
        "LocalClarity2012": _clip(values.get("clarity", 0.)),
        "LocalHue": _clip(values.get("hue", 0.)),
    })
    return settings


class Frame:
    """Passage du cadre affiché (recadré, orienté) aux coordonnées du XMP.

    Comme le recadrage (``crs:Crop*``), les points sont exprimés dans l'image
    entière, dans l'orientation du capteur.
    """

    def __init__(self, crop=None, flip=0):
        self.crop = tuple(crop) if crop else (0., 0., 1., 1.)
        self.flip = flip

    def point(self, u, v):
        left, top, right, bottom = self.crop
        x, y = left + u * (right - left), top + v * (bottom - top)
        if self.flip & 4:
            x, y = y, x
        if self.flip & 2:
            y = 1 - y
        if self.flip & 1:
            x = 1 - x
        return x, y

    def box(self, left, top, right, bottom):
        (x0, y0), (x1, y1) = self.point(left, top), self.point(right, bottom)
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _sample(kind, small):
    """Couleur représentative de la zone et sa position, pour une plage de couleur."""
    if small is not None:
        if kind == "peau":
            weight = _skin_weight(small)
        else:
            weight = _hue_weight(small, *COLORS[kind])
        if weight.max() > .3:
            threshold = np.quantile(weight, .98) if (weight > .3).mean() > .02 else .3
            selected = weight >= max(threshold, .3)
            rows, columns = np.nonzero(selected)
            color = small[selected].mean(axis=0)
            height, width = weight.shape
            return [float(c) for c in np.clip(color, 0, 1)], ((columns.mean() + .5) / width, (rows.mean() + .5) / height)
    hue = 25. if kind == "peau" else COLORS[kind][0]
    saturation, value = (.4, .75) if kind == "peau" else (.65, .7)
    return list(colorsys.hsv_to_rgb(hue / 360, saturation, value)), (.5, .5)


def _attributes(values):
    return " ".join(f"crs:{k}={quoteattr(str(v))}" for k, v in values.items())


def _component(kind, frame, small, *, inverted, blend):
    """Un composant de masque Lightroom pour une zone d'Atelier, ou None."""
    common = {"MaskActive": "true", "MaskBlendMode": blend, "MaskInverted": "true" if inverted else "false",
              "MaskValue": 1, "MaskSyncID": _identifier()}
    if kind == "image":
        # Dégradé dont l'effet complet commence au-dessus de l'image : toute la photo.
        x0, y0 = frame.point(.5, -2.)
        x1, y1 = frame.point(.5, -1.)
        return (f'<rdf:li {_attributes({"What": "Mask/Gradient", "MaskName": "Toute l’image", **common})} '
                f'{_attributes({"ZeroX": f"{x0:.6f}", "ZeroY": f"{y0:.6f}", "FullX": f"{x1:.6f}", "FullY": f"{y1:.6f}"})}/>')
    if kind in LINEAR:
        (zu, zv), (fu, fv) = LINEAR[kind]
        x0, y0 = frame.point(zu, zv)
        x1, y1 = frame.point(fu, fv)
        return (f'<rdf:li {_attributes({"What": "Mask/Gradient", "MaskName": kind.capitalize(), **common})} '
                f'{_attributes({"ZeroX": f"{x0:.6f}", "ZeroY": f"{y0:.6f}", "FullX": f"{x1:.6f}", "FullY": f"{y1:.6f}"})}/>')
    if kind in ("centre", "bords"):
        # Rayon d'effet nul et largeur du fondu, d'après les dégradés d'Atelier.
        outer, inner = (.95, .35) if kind == "centre" else (1.3, .55)
        half = outer / 2
        left, top, right, bottom = frame.box(.5 - half, .5 - half, .5 + half, .5 + half)
        feather = round(100 * (outer - inner) / outer)
        # « Bords » : l'effet est hors de l'ellipse, donc l'ellipse est inversée.
        flipped = inverted != (kind == "bords")
        common["MaskInverted"] = "true" if flipped else "false"
        return (f'<rdf:li {_attributes({"What": "Mask/CircularGradient", "MaskName": kind.capitalize(), **common})} '
                f'{_attributes({"Top": f"{top:.6f}", "Left": f"{left:.6f}", "Bottom": f"{bottom:.6f}", "Right": f"{right:.6f}", "Angle": 0, "Midpoint": 50, "Roundness": 0, "Feather": feather, "Flipped": "false" if flipped else "true", "Version": 2})}/>')
    if kind in TONES:
        lum = " ".join(f"{v:.6f}" for v in LUMINANCE[kind])
        return (f'<rdf:li><rdf:Description {_attributes({"What": "Mask/RangeMask", "MaskName": "Plage de luminance", **common})}>'
                f'<crs:CorrectionRangeMask {_attributes({"Version": 3, "Type": 2, "SampleType": 0, "LumRange": lum})}/>'
                "</rdf:Description></rdf:li>")
    if kind in COLORS or kind == "peau":
        color, (u, v) = _sample(kind, small)
        x, y = frame.point(u, v)
        amount = .35 if kind == "peau" else float(np.clip(COLORS[kind][1] / 60, .2, .8))
        model = f"{color[0]:.6f} {color[1]:.6f} {color[2]:.6f} {x:.6f} {y:.6f} 0"
        # Structure avec enfants : rdf:Description, comme Adobe l'écrit (voir crs:Look).
        return (f'<rdf:li><rdf:Description {_attributes({"What": "Mask/RangeMask", "MaskName": "Plage de couleurs", **common})}>'
                f'<crs:CorrectionRangeMask><rdf:Description {_attributes({"Version": 3, "Type": 1, "SampleType": 0, "ColorAmount": f"{amount:.6f}"})}>'
                f"<crs:PointModels><rdf:Seq><rdf:li>{model}</rdf:li></rdf:Seq></crs:PointModels>"
                "</rdf:Description></crs:CorrectionRangeMask></rdf:Description></rdf:li>")
    if kind in AI_SUBTYPES:
        if kind == "fond":
            common["MaskInverted"] = "false" if inverted else "true"
        names = {"sujet": "Sujet", "ciel": "Ciel", "fond": "Fond (sujet inversé)"}
        return (f'<rdf:li {_attributes({"What": "Mask/Image", "MaskSubType": AI_SUBTYPES[kind], "MaskName": names[kind], **common})}/>')
    return None


def corrections(edits, *, crop=None, flip=0, small=None):
    """Élément ``crs:MaskGroupBasedCorrections`` pour les retouches actives, ou "".

    ``small`` est la copie réduite développée de la photo (cadre affiché), qui
    sert à échantillonner les couleurs des plages de couleur.
    """
    frame = Frame(crop, flip)
    items = []
    for edit in edits or ():
        if not edit.get("enabled", True):
            continue
        zones = [z for z in edit.get("zones") or ["image"] if z != "image"] or ["image"]
        invert = bool(edit.get("invert"))
        components = []
        for index, kind in enumerate(zones):
            if invert and len(zones) > 1:
                # Inverse d'une intersection = réunion des inverses (De Morgan).
                component = _component(kind, frame, small, inverted=True, blend=ADD)
            else:
                component = _component(kind, frame, small, inverted=invert, blend=ADD if index == 0 else INTERSECT)
            if component:
                components.append(component)
        if not components:
            continue
        identifier = _identifier()
        settings = {"What": "Correction", "CorrectionAmount": 1, "CorrectionActive": "true",
                    "CorrectionName": edit.get("label") or "Retouche Atelier", "CorrectionSyncID": identifier,
                    **{k: f"{v:+.6f}" for k, v in local_settings(edit).items()}, "LocalCurveRefineSaturation": 100}
        items.append(f"<rdf:li><rdf:Description {_attributes(settings)}>"
                     f"<crs:CorrectionMasks><rdf:Seq>{''.join(components)}</rdf:Seq></crs:CorrectionMasks>"
                     "</rdf:Description></rdf:li>")
    if not items:
        return ""
    return f"<crs:MaskGroupBasedCorrections><rdf:Seq>{''.join(items)}</rdf:Seq></crs:MaskGroupBasedCorrections>"


def zone_kinds(edits):
    """Zones utilisées, pour signaler celles que Lightroom doit recalculer."""
    return {z for e in edits or () for z in (e.get("zones") or ["image"])}


__all__ = ["corrections", "local_settings", "zone_kinds", "Frame"]
