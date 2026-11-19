"""XMP sidecar describing Atelier's global correction for RAW editors.

Lightroom / Camera Raw read the ``crs`` settings; darktable imports the
exposure, contrast and saturation values. Atelier's own values are kept in
their own namespace so that nothing is lost when a tool ignores ``crs``.
"""
import re
from pathlib import Path

import numpy as np

from .config import RAW_EXTENSIONS
from .imaging import IDENTITY_STYLE, effective, temperature_kelvin, warmth_from_kelvin


def raw_crop(crop, flip):
    """Undo LibRaw's display flip (transpose, then reverse source axes)."""
    left, top, right, bottom = crop
    if flip & 4:
        left, top, right, bottom = top, left, bottom, right
    if flip & 2:
        top, bottom = 1 - bottom, 1 - top
    if flip & 1:
        left, right = 1 - right, 1 - left
    return left, top, right, bottom


def tool_settings(tools):
    """Clarté, courbe paramétrique et TSL au format ``crs`` ; courbes par points en éléments."""
    from . import tools as advanced
    t = advanced.normalize(tools)
    settings = {"crs:Clarity2012": f"{round(t['clarity'] * 100):+d}"}
    for key, name in zip(advanced.CURVE, ("Shadows", "Darks", "Lights", "Highlights"), strict=True):
        settings[f"crs:Parametric{name}"] = f"{round(t['curve'][key] * 100):+d}"
    for color, name in zip(advanced.COLORS, advanced.ADOBE_COLORS, strict=True):
        for index, kind in enumerate(("Hue", "Saturation", "Luminance")):
            settings[f"crs:{kind}Adjustment{name}"] = f"{round(t['hsl'][color][index] * 100):+d}"
    children = []
    for channel, suffix in (("master", ""), ("red", "Red"), ("green", "Green"), ("blue", "Blue")):
        points = (t.get("points") or {}).get(channel)
        if points:
            items = "".join(f"<rdf:li>{round(x * 255)}, {round(y * 255)}</rdf:li>" for x, y in points)
            children.append(f"<crs:ToneCurvePV2012{suffix}><rdf:Seq>{items}</rdf:Seq></crs:ToneCurvePV2012{suffix}>")
    return settings, "".join(children)


def sidecar(recipe, style, enabled=True, raw=True, *, crop=None, tools=None, masks=""):
    """XMP sidecar: global correction, crop, advanced tools and local corrections.

    ``masks`` is a ``crs:MaskGroupBasedCorrections`` element (see lightroom.py).
    """
    total = effective(recipe, style) if enabled else dict(IDENTITY_STYLE)
    settings = {
        "crs:Exposure2012": f"{max(-5., min(5., total['exposure'])):+.2f}",
        "crs:Contrast2012": f"{round(max(-100, min(100, total['contrast'] * 200))):+d}",
        "crs:Saturation": f"{round(max(-100, min(100, total['saturation'] * 100))):+d}",
    }
    if crop:
        settings["crs:HasCrop"] = "True"
        settings["crs:CropAngle"] = "0"
        for edge, value in zip(("Left", "Top", "Right", "Bottom"), crop, strict=True):
            settings[f"crs:Crop{edge}"] = f"{value:.8f}"
    if raw:
        # Absolute Kelvin is unknown without the camera's as-shot white balance;
        # keep the shot's balance and record Atelier's warmth below.
        settings["crs:WhiteBalance"] = "As Shot"
    else:
        settings["crs:IncrementalTemperature"] = f"{round(max(-100, min(100, total['temperature'] * 40))):+d}"
    atelier = {f"atelier:{k}": f"{v:.4f}" for k, v in total.items()}
    atelier["atelier:RenderedTemperatureKelvin"] = str(temperature_kelvin(total["temperature"]))
    atelier["atelier:FilterEnabled"] = "True" if enabled else "False"
    children = masks or ""
    if tools:
        extra, curves = tool_settings(tools)
        settings.update(extra)
        children = curves + children
    attributes = "\n".join(f'   {k}="{v}"' for k, v in {**settings, **atelier}.items())
    body = f">\n   {children}\n  </rdf:Description>" if children else "/>"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Atelier Photo">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
   xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   xmlns:atelier="https://atelier-photo.local/ns/1.0/"
   crs:Version="15.0"
   crs:ProcessVersion="11.0"
   crs:HasSettings="True"
{attributes}{body}
 </rdf:RDF>
</x:xmpmeta>
""".encode("utf-8")


# --- Reading a photographer's sidecar (reference photos) -------------------

_ATTRIBUTE = re.compile(rb'\b(crs|atelier):(\w+)\s*=\s*"([^"]*)"')
_ELEMENT = re.compile(rb"<(crs|atelier):(\w+)>([^<]*)</\1:\2>")
_LOCAL = re.compile(rb"<crs:\w*BasedCorrections>\s*<rdf:Seq>\s*<rdf:li")
# Nested blocks whose crs attributes are not the photo's own global settings.
_NESTED = re.compile(rb"<crs:(Look|MaskGroupBasedCorrections|GradientBasedCorrections|"
                     rb"CircularGradientBasedCorrections|PaintBasedCorrections|RetouchAreas)>.*?</crs:\1>", re.S)
_CURVE = re.compile(rb"<crs:(ToneCurvePV2012(?:Red|Green|Blue)?)>\s*<rdf:Seq>(.*?)</rdf:Seq>", re.S)
_POINT = re.compile(rb"<rdf:li>\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*</rdf:li>")
# Basic-panel settings Atelier has no equivalent for; reported, never guessed.
IGNORED = ("Texture", "Dehaze", "Tint", "IncrementalTint")


def find_sidecar(path):
    """Adobe replaces the extension (photo.xmp); darktable appends it (photo.nef.xmp)."""
    path = Path(path)
    for stem in (path.stem, path.name):
        for extension in (".xmp", ".XMP"):
            candidate = path.with_name(stem + extension)
            if candidate.is_file():
                return candidate
    return None


def read_settings(path):
    """``crs``/``atelier`` values of the main description, first occurrence wins.

    Nested masks and looks come after the main attributes and use other names.
    """
    with open(path, "rb") as stream:
        text = stream.read(16 * 1024 * 1024)
    settings = {}
    if _LOCAL.search(text):
        settings["local"] = "True"
    text = _NESTED.sub(b"", text)
    for match in _CURVE.finditer(text):
        points = ";".join(f"{float(x):g},{float(y):g}" for x, y in _POINT.findall(match[2]))
        settings.setdefault(f"crs:{match[1].decode()}", points)
    for pattern in (_ATTRIBUTE, _ELEMENT):
        for match in pattern.finditer(text):
            key = f"{match[1].decode()}:{match[2].decode()}"
            settings.setdefault(key, match[3].decode("utf-8", "replace").strip())
    return settings


def read_tools(settings):
    """Clarté, courbes et TSL d'un XMP, au format de tools.py."""
    from . import tools as advanced
    tools = advanced.identity()
    tools["clarity"] = _number(settings, "crs:Clarity2012") / 100
    for key, name in zip(advanced.CURVE, ("Shadows", "Darks", "Lights", "Highlights"), strict=True):
        tools["curve"][key] = _number(settings, f"crs:Parametric{name}") / 100
    for color, name in zip(advanced.COLORS, advanced.ADOBE_COLORS, strict=True):
        tools["hsl"][color] = [_number(settings, f"crs:{kind}Adjustment{name}") / 100
                               for kind in ("Hue", "Saturation", "Luminance")]
    points = {}
    for channel, suffix in (("master", ""), ("red", "Red"), ("green", "Green"), ("blue", "Blue")):
        pairs = [tuple(float(v) / 255 for v in item.split(","))
                 for item in settings.get(f"crs:ToneCurvePV2012{suffix}", "").split(";") if "," in item]
        if len(pairs) >= 2:
            points[channel] = [list(p) for p in pairs]
    if points:
        tools["points"] = points
    return advanced.normalize(tools)


def _number(settings, key, default=0.):
    try:
        return float(settings.get(key, default))
    except ValueError:
        return default


def as_shot_kelvin(path):
    """Correlated colour temperature of the camera's as-shot white balance."""
    import rawpy
    with rawpy.imread(str(path)) as raw:
        multipliers = np.asarray(raw.camera_whitebalance[:3], dtype=np.float64)
        cam_xyz = np.asarray(raw.rgb_xyz_matrix[:3], dtype=np.float64)
    if multipliers.min() <= 0 or not cam_xyz.any():
        return None
    xyz = np.linalg.lstsq(cam_xyz, multipliers[1] / multipliers, rcond=None)[0]
    if xyz.sum() <= 0:
        return None
    x, y = xyz[:2] / xyz.sum()
    n = (x - .3320) / (.1858 - y)
    kelvin = 449 * n ** 3 + 3525 * n ** 2 + 6823.3 * n + 5520.33
    return float(kelvin) if 1500 < kelvin < 50000 else None


def raw_to_display(crop, flip):
    """Inverse of ``raw_crop``: sensor crop to the displayed orientation."""
    left, top, right, bottom = crop
    if flip & 1:
        left, right = 1 - right, 1 - left
    if flip & 2:
        top, bottom = 1 - bottom, 1 - top
    if flip & 4:
        left, top, right, bottom = top, left, bottom, right
    return left, top, right, bottom


def development(settings, source):
    """Atelier approximation of the sidecar's global edit.

    Returns ``style`` (render() offsets), ``tones`` (highlights/shadows/whites/
    blacks, -1..1), ``crop`` in display orientation and the edits left out.
    """
    raw = Path(source).suffix.lower() in RAW_EXTENSIONS
    crop = None
    if settings.get("crs:HasCrop") == "True":
        edges = tuple(min(1., max(0., _number(settings, f"crs:Crop{e}", d)))
                      for e, d in (("Left", 0), ("Top", 0), ("Right", 1), ("Bottom", 1)))
        if edges[2] - edges[0] > .05 and edges[3] - edges[1] > .05 and edges != (0, 0, 1, 1):
            crop = edges
            if raw:
                import rawpy
                with rawpy.imread(str(source)) as image:
                    crop = raw_to_display(crop, image.sizes.flip)
    ignored = []
    if "atelier:exposure" in settings:
        # Written by Atelier itself: exact values.
        enabled = settings.get("atelier:FilterEnabled", "True") == "True"
        style = {k: _number(settings, f"atelier:{k}") if enabled else 0. for k in IDENTITY_STYLE}
        return {"style": style, "tones": {}, "crop": crop, "ignored": ignored, "tools": read_tools(settings)}
    if settings.get("crs:HasSettings") == "False":
        return {"style": dict(IDENTITY_STYLE), "tones": {}, "crop": crop, "ignored": ignored, "tools": None}
    style = {
        "exposure": _number(settings, "crs:Exposure2012", _number(settings, "crs:Exposure")),
        "contrast": _number(settings, "crs:Contrast2012") / 200,
        "saturation": _number(settings, "crs:Saturation") / 100 + _number(settings, "crs:Vibrance") / 200,
        "temperature": 0.,
    }
    if settings.get("crs:ConvertToGrayscale") == "True":
        style["saturation"] = -1.
    if "crs:IncrementalTemperature" in settings:
        style["temperature"] = _number(settings, "crs:IncrementalTemperature") / 40
    elif raw and settings.get("crs:WhiteBalance", "As Shot") != "As Shot" and "crs:Temperature" in settings:
        shot = as_shot_kelvin(source)
        if shot:
            # Same mired shift from D65 (Atelier's neutral) as Lightroom's from as shot;
            # in both, a higher temperature warms the photo.
            mired = 1e6 / 6500 - 1e6 / shot + 1e6 / max(2000., _number(settings, "crs:Temperature"))
            style["temperature"] = warmth_from_kelvin(1e6 / max(mired, 1.))
        else:
            ignored.append("Temperature")
    tones = {k: max(-1., min(1., _number(settings, f"crs:{k}2012") / 100))
             for k in ("Highlights", "Shadows", "Whites", "Blacks")}
    ignored += [k for k in IGNORED if _number(settings, f"crs:{k}")]
    if settings.get("local") == "True":
        ignored.append("Retouches locales")
    return {"style": style, "tones": {k: v for k, v in tones.items() if v}, "crop": crop, "ignored": ignored,
            "tools": read_tools(settings)}


def apply_tones(pixels, tones):
    """Highlights/shadows/whites/blacks as a smooth luminance curve (display values)."""
    if not tones:
        return pixels
    x = np.clip(pixels, 0, 1)
    luma = (x * np.array([.2126, .7152, .0722], dtype=np.float32)).sum(axis=2, keepdims=True)
    curve = luma.copy()
    curve += .30 * tones.get("Shadows", 0.) * luma * (1 - luma) ** 2 * 4
    curve += .30 * tones.get("Highlights", 0.) * luma ** 2 * (1 - luma) * 4
    curve += .12 * tones.get("Whites", 0.) * luma ** 3
    curve += .12 * tones.get("Blacks", 0.) * (1 - luma) ** 3
    curve = np.clip(curve, 0, 1)
    return np.clip(x * (curve / np.maximum(luma, 1e-4)), 0, 1)
