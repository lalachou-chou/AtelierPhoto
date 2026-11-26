import datetime
import hashlib
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageFilter, ImageOps

from .config import EXTENSIONS, RAW_EXTENSIONS
from .cr2 import broken_raw_strip

# Longest side of the analysis copy, which is also the on-screen preview.
ANALYSIS_SIZE = 1280


class CorruptPhoto(ValueError):
    """A photo with evidence of damaged image data."""


def digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def capture_time(path):
    """Capture time in seconds (EXIF DateTimeOriginal + sub-seconds), else file time.

    Only used to order photos and split them into moments.
    """
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


def _develop(path):
    """Half-size RAW development with the camera white balance, 8-bit sRGB."""
    import rawpy
    try:
        with rawpy.imread(str(path)) as raw:
            pixels = raw.postprocess(use_camera_wb=True, no_auto_bright=True,
                                     output_bps=16, output_color=rawpy.ColorSpace.sRGB,
                                     half_size=True, gamma=(2.4, 12.92))
    except (rawpy.LibRawDataError, rawpy.LibRawIOError) as exc:
        # Readable file, damaged or truncated image data.
        raise CorruptPhoto(f"RAW corrompu ou incomplet : {exc}") from exc
    except rawpy.LibRawError as exc:
        if (isinstance(exc, rawpy.LibRawFileUnsupportedError) and path.suffix.lower() == ".cr2"
                and broken_raw_strip(path)):
            raise CorruptPhoto("CR2 endommagé : le bloc RAW indiqué dans le fichier est invalide.") from exc
        raise ValueError(f"RAW illisible ou boîtier non reconnu : {exc}") from exc
    # Integer division: same bytes as truncating pixels / 257, without a float copy.
    return Image.fromarray((pixels // 257).astype(np.uint8))


def _open(path):
    """Oriented sRGB copy of a JPEG or PNG; transparency is composed on white."""
    with Image.open(path) as source:
        if source.format == "JPEG":
            source.draft("RGB", (1600, 1600))
        image = ImageOps.exif_transpose(source)
        if image.mode == "RGBA" or "transparency" in source.info:
            rgba = image.convert("RGBA")
            image = Image.new("RGB", rgba.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        if source.info.get("icc_profile"):
            profile = ImageCms.ImageCmsProfile(io.BytesIO(source.info["icc_profile"]))
            return ImageCms.profileToProfile(image, profile, ImageCms.createProfile("sRGB"), outputMode="RGB")
        return image.convert("RGB")


def decode(path):
    """Analysis copy of a photo: oriented 8-bit sRGB, ``ANALYSIS_SIZE`` px at most.

    Damaged image data raises CorruptPhoto (the file is then set aside), an
    unreadable or unsupported file ValueError, a disk problem OSError (resumable).
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in EXTENSIONS:
        raise ValueError(f"Format non pris en charge : {path.suffix}")
    if suffix in RAW_EXTENSIONS:
        image = _develop(path)
    else:
        try:
            image = _open(path)
        except (OSError, SyntaxError) as exc:
            # Pillow reports damaged data as OSError without errno; keep real I/O errors.
            if isinstance(exc, OSError) and exc.errno is not None and exc.errno >= 0:
                raise
            with path.open("rb") as stream:
                header = stream.read(8)
            if header.startswith(b"\xff\xd8\xff") or header == b"\x89PNG\r\n\x1a\n":
                raise CorruptPhoto(f"Photo endommagée ou incomplète : {exc}") from exc
            raise ValueError(f"Photo illisible : {exc}") from exc
    image.thumbnail((ANALYSIS_SIZE, ANALYSIS_SIZE), Image.Resampling.LANCZOS)
    return image


def features(image):
    """Technical measures of an analysis copy, computed at 512 px at most."""
    image = image.copy()
    image.thumbnail((512, 512), Image.Resampling.LANCZOS)
    gray_image = image.convert("L")
    gray = np.asarray(gray_image, dtype=np.float32) / 255
    if min(gray.shape) < 8:
        raise ValueError("Image trop petite pour être analysée")
    hsv = np.asarray(image.convert("HSV"), dtype=np.float32) / 255
    lap = -4 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    tiles = [float(np.var(t)) for band in np.array_split(lap, 4) for t in np.array_split(band, 4, axis=1)]
    blurred = np.asarray(gray_image.filter(ImageFilter.MedianFilter(3)), dtype=np.float32) / 255
    gradient = np.abs(np.diff(gray, axis=0, prepend=gray[:1])) + np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    flat = gradient <= np.quantile(gradient, .35)
    return {"luma": float(np.median(gray)), "spread": float(np.quantile(gray, .9) - np.quantile(gray, .1)),
            "saturation": float(hsv[:, :, 1].mean()),
            "sharpness": float(np.quantile(tiles, .8)), "peak": float(max(tiles)),
            "noise": float(np.median(np.abs(gray - blurred)[flat])),
            "black": float(np.mean(gray < .015)), "white": float(np.mean(gray > .985))}
