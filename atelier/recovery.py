"""Recover usable image data to a separate file at the user's request."""
import io
import struct
import zlib
from pathlib import Path

from PIL import Image

from .cr2 import embedded_jpeg


def _png_pixels(data):
    # Keep intact image and colour chunks. A damaged text/EXIF chunk can
    # prevent the normal reader from reaching otherwise readable pixels.
    chunks = [data[:8]]
    offset = 8
    while offset + 12 <= len(data):
        length, kind = struct.unpack_from(">I4s", data, offset)
        end = offset + 12 + length
        if end > len(data) or kind == b"IEND":
            break
        if kind in (b"IHDR", b"PLTE", b"IDAT", b"tRNS", b"gAMA", b"sRGB", b"iCCP", b"cHRM"):
            checksum, = struct.unpack_from(">I", data, end - 4)
            if checksum != zlib.crc32(memoryview(data)[offset+4:end-4]):
                raise ValueError("Un bloc de l’image PNG est endommagé.")
            chunks.append(data[offset:end])
        offset = end
    chunks.append(b"\x00\x00\x00\x00IEND\xaeB\x60\x82")
    return b"".join(chunks)


def _checked_image(data, format):
    with Image.open(io.BytesIO(data), formats=(format,)) as image:
        image.load()
    return data, ".jpg" if format == "JPEG" else ".png"


def recover_image(path):
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix in (".jpg", ".jpeg", ".png"):
        if source.stat().st_size > 128 * 1024 * 1024:
            raise ValueError("Fichier trop volumineux pour cette méthode de récupération.")
        data = source.read_bytes()
        if suffix == ".png":
            return _checked_image(_png_pixels(data), "PNG")
        # An explicit end marker lets the decoder retain readable scan lines.
        if not data.endswith(b"\xff\xd9"):
            data += b"\xff\xd9"
        return _checked_image(data, "JPEG")
    if suffix == ".cr2":
        data = embedded_jpeg(source)
        if data is not None:
            return data, ".jpg"
    import rawpy
    try:
        # Opening the container alone can read its preview even if unpacking
        # the sensor data fails. Do not use imread(), which also unpacks.
        with rawpy.RawPy() as raw:
            raw.open_file(str(source))
            thumb = raw.extract_thumb()
        if thumb.format == rawpy.ThumbFormat.JPEG:
            return _checked_image(thumb.data, "JPEG")
        image = Image.fromarray(thumb.data)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue(), ".png"
    except rawpy.LibRawError as exc:
        raise ValueError("Aucun aperçu de boîtier exploitable dans ce RAW.") from exc
