import hashlib
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageFilter, ImageOps

from .config import EXTENSIONS, RAW_EXTENSIONS

SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


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
        except rawpy.LibRawError as exc:
            raise ValueError(f"RAW illisible ou boîtier non reconnu : {exc}") from exc
        if preview:
            # Only analysis proxies are reduced to eight bits.
            image = Image.fromarray((pixels / 257).astype(np.uint8))
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


def as_image(pixels):
    return Image.fromarray(np.round(np.clip(pixels, 0, 1) * 255).astype(np.uint8))


def features(pixels):
    image = as_image(pixels)
    image.thumbnail((512, 512), Image.Resampling.LANCZOS)
    x = np.asarray(image, dtype=np.float32) / 255
    gray = np.asarray(image.convert("L"), dtype=np.float32) / 255
    if min(gray.shape) < 8:
        raise ValueError("Image trop petite pour être analysée")
    lap = -4 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    tiles = [float(np.var(t)) for band in np.array_split(lap, 4) for t in np.array_split(band, 4, axis=1)]
    blurred = np.asarray(image.convert("L").filter(ImageFilter.MedianFilter(3)), dtype=np.float32) / 255
    gradient = np.abs(np.diff(gray, axis=0, prepend=gray[:1])) + np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    flat = gradient <= np.quantile(gradient, .35)
    noise = float(np.median(np.abs(gray - blurred)[flat]))
    hsv = np.asarray(image.convert("HSV"), dtype=np.float32) / 255
    thumb = np.asarray(image.convert("L").resize((9, 8), Image.Resampling.LANCZOS))
    dhash = "".join("1" if b else "0" for b in (thumb[:, 1:] > thumb[:, :-1]).ravel())
    return {"luma": float(np.median(gray)), "spread": float(np.quantile(gray, .9) - np.quantile(gray, .1)),
            "rgb": np.mean(x, axis=(0, 1)).tolist(), "saturation": float(hsv[:, :, 1].mean()),
            "sharpness": float(np.quantile(tiles, .8)), "peak": float(max(tiles)), "noise": noise,
            "black": float(np.mean(gray < .015)), "white": float(np.mean(gray > .985)),
            "hash": dhash, "aspect": pixels.shape[1] / pixels.shape[0]}


NEUTRAL = {"intensity": .65, "exposure": 0., "temperature": 0., "contrast": 0., "saturation": 0.}
LIMITS = {"intensity": (0., 1.), "exposure": (-2., 2.), "temperature": (-1., 1.), "contrast": (-.5, .5), "saturation": (-.6, .6)}


IDENTITY_RECIPE = {"intensity": 0., "exposure": 0., "temperature": 0., "contrast": 0., "saturation": 0.}
IDENTITY_STYLE = {"exposure": 0., "temperature": 0., "contrast": 0., "saturation": 0.}


def effective(recipe, style):
    """Total global correction applied by render(): user recipe plus weighted profile style."""
    r = clamp_recipe(recipe)
    return {k: r[k] + style.get(k, 0.) * r["intensity"] for k in IDENTITY_STYLE}


def clamp_recipe(recipe):
    return {k: float(np.clip(recipe.get(k, NEUTRAL[k]), *bounds)) for k, bounds in LIMITS.items()}


def render(pixels, recipe, style, look=None):
    """Same pointwise transform for preview/export; fixed stats, no size dependence.

    With a learned ``look`` (see look.py), the photographer's colour table and the
    photo's tone curve (``style["knots"]``) are applied first, blended by the
    intensity slider; the other sliders then act as manual adjustments.
    """
    total = effective(recipe, style)
    learned = look is not None and style.get("knots") is not None
    if learned:
        from .look import apply as apply_look
        strength = clamp_recipe(recipe)["intensity"]
    # Process stripes to avoid multiple full-resolution float intermediates.
    result = np.empty(pixels.shape, dtype=np.uint8)
    for start in range(0, pixels.shape[0], 128):
        x = pixels[start:start + 128].astype(np.float32, copy=True)
        if learned:
            x += strength * (apply_look(look, x, style["knots"]) - x)
        x *= 2 ** total["exposure"]
        warmth = total["temperature"]
        x *= np.array([1 + warmth * .12, 1., 1 - warmth * .12], dtype=np.float32)
        x = (x - .5) * (1 + total["contrast"]) + .5
        luma = (x * np.array([.2126, .7152, .0722], dtype=np.float32)).sum(axis=2, keepdims=True)
        x = luma + (x - luma) * (1 + total["saturation"])
        result[start:start + 128] = np.round(np.clip(x, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(result)

