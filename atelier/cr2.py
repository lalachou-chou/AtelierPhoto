"""Inspect the two single-strip JPEG directories in a Canon CR2 v2 file."""
import io
import os
import struct

from PIL import Image


def _jpeg_strip(stream, *, raw):
    header = stream.read(16)
    if len(header) != 16 or header[8:12] != b"CR\x02\x00":
        return None
    endian = {b"II*\x00": "<", b"MM\x00*": ">"}.get(header[:4])
    if not endian:
        return None
    directory, = struct.unpack_from(endian + "I", header, 12 if raw else 4)
    if directory < 16:
        return None
    stream.seek(directory)
    count = stream.read(2)
    if len(count) != 2:
        return None
    count, = struct.unpack(endian + "H", count)
    entries = stream.read(12 * count)
    if len(entries) != 12 * count:
        return None
    tags = {}
    for tag, kind, length, field in struct.iter_unpack(endian + "HHI4s", entries):
        if tag in (259, 273, 279) and length == 1 and kind in (3, 4):
            tags[tag], = struct.unpack_from(endian + ("H" if kind == 3 else "I"), field)
    if tags.get(259) == 6 and 273 in tags and 279 in tags:
        return tags[273], tags[279]
    return None


def broken_raw_strip(path):
    """Positive evidence of corruption before treating an unknown camera as damaged."""
    with path.open("rb") as stream:
        strip = _jpeg_strip(stream, raw=True)
        if strip is None:
            return False
        offset, length = strip
        stream.seek(offset)
        return (length < 4 or offset + length > os.fstat(stream.fileno()).st_size
                or stream.read(2) != b"\xff\xd8")


def embedded_jpeg(path):
    """Return the camera JPEG verbatim only when its complete image decodes."""
    with path.open("rb") as stream:
        strip = _jpeg_strip(stream, raw=False)
        if strip is None:
            return None
        offset, length = strip
        if not 4 <= length <= 64 * 1024 * 1024 or offset + length > os.fstat(stream.fileno()).st_size:
            return None
        stream.seek(offset)
        data = stream.read(length)
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        return None
    try:
        with Image.open(io.BytesIO(data), formats=("JPEG",)) as image:
            image.load()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None
    return data
