import hashlib
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageFilter, ImageOps

from .config import EXTENSIONS, RAW_EXTENSIONS
from .cr2 import broken_raw_strip


class CorruptPhoto(ValueError):
    """A photo with evidence of damaged image data."""


SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def capture_time(path):
    """Capture time in seconds (EXIF DateTimeOriginal + sub-seconds), else file time.

    Only used to order photos and split them into moments; never exported.
    """
    import datetime
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            details = exif.get_ifd(34665)
            stamp = details.get(36867) or exif.get(306)
            if stamp:
                moment = datetime.datetime.strptime(str(stamp).strip()[:19], "%Y:%m:%d %H:%M:%S")
                digits = "".join(c for c in str(details.get(37521) or "") if c.isdigit())
                return moment.timestamp() + (float("0." + digits) if digits else 0.)
    except (OSError, ValueError, SyntaxError):
        pass
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None


def decode(path, preview=False):
    """Return oriented sRGB float pixels and safe metadata. RAW remains 16-bit."""
    path = Path(path)
    if path.suffix.lower() not in EXTENSIONS:
        raise ValueError(f"Format non pris en charge : {path.suffix}")
    if path.suffix.lower() in RAW_EXTENSIONS:
        import rawpy
        try:
            with rawpy.imread(str(path)) as raw:
                pixels = raw.postprocess(use_camera_wb=True, no_auto_bright=True,
                                         output_bps=16, output_color=rawpy.ColorSpace.sRGB,
                                         half_size=preview, gamma=(2.4, 12.92))
        except (rawpy.LibRawDataError, rawpy.LibRawIOError) as exc:
            # Readable file, damaged or truncated image data.
            raise CorruptPhoto(f"RAW corrompu ou incomplet : {exc}") from exc
        except rawpy.LibRawError as exc:
            if (isinstance(exc, rawpy.LibRawFileUnsupportedError) and path.suffix.lower() == ".cr2"
                    and broken_raw_strip(path)):
                raise CorruptPhoto("CR2 endommagé : le bloc RAW indiqué dans le fichier est invalide.") from exc
            raise ValueError(f"RAW illisible ou boîtier non reconnu : {exc}") from exc
        if preview:
            # Only analysis proxies are reduced to eight bits.
            # Integer division: same bytes as truncating pixels / 257, without a
            # float64 copy four times the size of the photo.
            image = Image.fromarray((pixels // 257).astype(np.uint8))
            image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
            return np.asarray(image, dtype=np.float32) / 255, {}
        return pixels.astype(np.float32) / 65535, {}
    with Image.open(path) as source:
        if preview and source.format == "JPEG":
            source.draft("RGB", (1600, 1600))
        exif = source.getexif()
        image = ImageOps.exif_transpose(source)
        if image.mode == "RGBA" or "transparency" in source.info:
            rgba = image.convert("RGBA")
            image = Image.new("RGB", rgba.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        if source.info.get("icc_profile"):
            profile = ImageCms.ImageCmsProfile(io.BytesIO(source.info["icc_profile"]))
            image = ImageCms.profileToProfile(image, profile, ImageCms.createProfile("sRGB"), outputMode="RGB")
        else:
            image = image.convert("RGB")
        # Preserve photographic EXIF but discard orientation, thumbnail offsets,
        # and dimensions which may describe the unrotated source.
        for key in (274, 256, 257, 40962, 40963, 513, 514):
            if key in exif:
                del exif[key]
        # The output color space is always sRGB, not the source ICC space.
        if 34665 in exif:
            photographic = exif.get_ifd(34665)
            photographic[40961] = 1
            photographic.pop(40962, None)
            photographic.pop(40963, None)
        if preview:
            image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        return np.asarray(image, dtype=np.float32) / 255, {"exif": exif.tobytes()}


def source_size(path):
    """Oriented (width, height) of the full-resolution source, without decoding its pixels."""
    path = Path(path)
    if path.suffix.lower() in RAW_EXTENSIONS:
        import rawpy
        with rawpy.imread(str(path)) as raw:
            width, height, flip = raw.sizes.width, raw.sizes.height, raw.sizes.flip
        # LibRaw flips 5 and 6 are quarter turns.
        return (height, width) if flip in (5, 6) else (width, height)
    with Image.open(path) as source:
        width, height = source.size
        orientation = source.getexif().get(274, 1)
    return (height, width) if orientation in (5, 6, 7, 8) else (width, height)


def as_image(pixels):
    return Image.fromarray(np.round(np.clip(pixels, 0, 1) * 255).astype(np.uint8))


def active_crop(data, batch_enabled=True):
    enabled = data.get("crop_enabled", True) if batch_enabled else data.get("crop_when_off", False)
    return data.get("crop") if enabled else None


def crop_box(size, crop):
    """Map the normalized edges of an oriented photo to a nonempty pixel box."""
    width, height = size
    left, top, right, bottom = crop
    x = max(0, min(width - 1, round(left * width)))
    y = max(0, min(height - 1, round(top * height)))
    return x, y, max(x + 1, min(width, round(right * width))), max(y + 1, min(height, round(bottom * height)))


def cropped_pixels(pixels, crop):
    if not crop:
        return pixels
    height, width = pixels.shape[:2]
    x, y, right, bottom = crop_box((width, height), crop)
    return pixels[y:bottom, x:right]


def color_features(image):
    """Global colour statistics, also used to compare a rendered sample to references."""
    x = np.asarray(image, dtype=np.float32) / 255
    gray = np.asarray(image.convert("L"), dtype=np.float32) / 255
    hsv = np.asarray(image.convert("HSV"), dtype=np.float32) / 255
    return {"luma": float(np.median(gray)), "spread": float(np.quantile(gray, .9) - np.quantile(gray, .1)),
            "rgb": np.mean(x, axis=(0, 1)).tolist(), "saturation": float(hsv[:, :, 1].mean())}


def features(pixels):
    image = as_image(pixels)
    image.thumbnail((512, 512), Image.Resampling.LANCZOS)
    gray = np.asarray(image.convert("L"), dtype=np.float32) / 255
    if min(gray.shape) < 8:
        raise ValueError("Image trop petite pour être analysée")
    lap = -4 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    tiles = [float(np.var(t)) for band in np.array_split(lap, 4) for t in np.array_split(band, 4, axis=1)]
    blurred = np.asarray(image.convert("L").filter(ImageFilter.MedianFilter(3)), dtype=np.float32) / 255
    gradient = np.abs(np.diff(gray, axis=0, prepend=gray[:1])) + np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    flat = gradient <= np.quantile(gradient, .35)
    noise = float(np.median(np.abs(gray - blurred)[flat]))
    return {**color_features(image),
            "sharpness": float(np.quantile(tiles, .8)), "peak": float(max(tiles)), "noise": noise,
            "black": float(np.mean(gray < .015)), "white": float(np.mean(gray > .985)),
            "aspect": pixels.shape[1] / pixels.shape[0]}


NEUTRAL = {"intensity": .65, "exposure": 0., "temperature": 0., "contrast": 0., "saturation": 0.}
# Calibrate the existing red/blue gain control to an equivalent daylight white
# point on the developed sRGB image. D65 is the neutral reference.
_KELVIN = np.arange(4000, 20001, 25)
_inverse = 1. / _KELVIN
_x = np.where(_KELVIN <= 7000, np.polyval([-4.607e9, 2.9678e6, 99.11, .244063], _inverse),
              np.polyval([-2.0064e9, 1.9018e6, 247.48, .237040], _inverse))
_y = -3 * _x ** 2 + 2.87 * _x - .275
_X, _Z = _x / _y, (1 - _x - _y) / _y
_ratio = ((.0557 * _X - .2040 + 1.0570 * _Z) / (3.2406 * _X - 1.5372 - .4986 * _Z)) ** (1 / 2.4)
_ratio /= _ratio[_KELVIN == 6500].item()
_WARMTH = (_ratio - 1) / (.12 * (_ratio + 1))


def warmth_from_kelvin(kelvin):
    return float(np.interp(kelvin, _KELVIN, _WARMTH))


def temperature_kelvin(warmth):
    return round(float(np.interp(warmth, _WARMTH, _KELVIN)))


LIMITS = {"intensity": (0., 1.), "exposure": (-2., 2.), "temperature": (float(_WARMTH[0]), float(_WARMTH[-1])), "contrast": (-.5, .5), "saturation": (-.6, .6)}


IDENTITY_RECIPE = {"intensity": 0., "exposure": 0., "temperature": 0., "contrast": 0., "saturation": 0.}
IDENTITY_STYLE = {"exposure": 0., "temperature": 0., "contrast": 0., "saturation": 0.}


def active_recipe(data, batch_filter):
    if batch_filter:
        return data["recipe"]
    return data.get("manual_recipe") or IDENTITY_RECIPE


def effective(recipe, style):
    """Total global correction applied by render(): user recipe plus weighted profile style."""
    r = clamp_recipe(recipe)
    return {k: r[k] + style.get(k, 0.) * r["intensity"] for k in IDENTITY_STYLE}


def clamp_recipe(recipe):
    return {k: float(np.clip(recipe.get(k, NEUTRAL[k]), *bounds)) for k, bounds in LIMITS.items()}


def look_strength(recipe, style, look):
    if look is None or style.get("knots") is None:
        return 0.
    return clamp_recipe(recipe)["intensity"]


def render(pixels, recipe, style, look=None, local=None, tools=None):
    """Eight-bit display/JPEG/PNG rendition of the shared full-precision edits."""
    return Image.fromarray(render_pixels(pixels, recipe, style, look, bit_depth=8, local=local, tools=tools))


def render_pixels(pixels, recipe, style, look=None, *, bit_depth=16, local=None, tools=None):
    """Same pointwise transform for preview/export; fixed stats, no size dependence.

    With a learned ``look`` (see look.py), the photographer's colour table and the
    photo's tone curve (``style["knots"]``) are applied first, blended by the
    intensity slider; the other sliders then act as manual adjustments.
    ``local`` lists zone edits (see local.py), applied last. Their regional masks
    are estimated once on a reduced developed copy, so preview and export agree.
    ``tools`` holds clarity, tone curve and HSL (see tools.py), in Lightroom's
    order: clarity on the input, curve after contrast, HSL after saturation.
    """
    if bit_depth not in (8, 16):
        raise ValueError("Le rendu doit être en 8 ou 16 bits.")
    from . import tools as advanced
    tools = advanced.normalize(tools) if tools and not advanced.is_identity(tools) else None
    prepared = None
    if local:
        from . import local as zones
        if zones.active(local):
            small = render_pixels(zones.proxy(pixels), recipe, style, look, tools=tools).astype(np.float32) / 65535
            prepared = zones.prepare(local, small)
    low = advanced.base(pixels) if advanced.needs_base(tools, prepared and [p.amounts for p in prepared]) else None
    tables = advanced.curve_tables(tools)
    total = effective(recipe, style)
    strength = look_strength(recipe, style, look)
    if strength:
        from .look import apply as apply_look
    # Process stripes to avoid multiple full-resolution float intermediates.
    result = np.empty(pixels.shape, dtype=np.uint16 if bit_depth == 16 else np.uint8)
    maximum = (1 << bit_depth) - 1
    for start in range(0, pixels.shape[0], 128):
        x = pixels[start:start + 128].astype(np.float32, copy=True)
        detail = advanced.detail(x, start, pixels.shape, low) if low is not None else None
        if tools and tools["clarity"]:
            x = advanced.clarity(x, detail, tools["clarity"])
        if strength:
            x += strength * (apply_look(look, x, style["knots"]) - x)
        x *= 2 ** total["exposure"]
        warmth = total["temperature"]
        x *= np.array([1 + warmth * .12, 1., 1 - warmth * .12], dtype=np.float32)
        x = (x - .5) * (1 + total["contrast"]) + .5
        x = advanced.apply_curve(x, tables)
        luma = (x * np.array([.2126, .7152, .0722], dtype=np.float32)).sum(axis=2, keepdims=True)
        x = luma + (x - luma) * (1 + total["saturation"])
        x = advanced.apply_hsl(x, tools)
        if prepared:
            x = zones.apply(x, start, pixels.shape, prepared, detail)
        result[start:start + 128] = np.round(np.clip(x, 0, 1) * maximum).astype(result.dtype)
    return result

