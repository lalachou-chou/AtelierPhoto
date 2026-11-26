"""XMP sidecars next to a photo: found, never interpreted.

Atelier only sorts. A sidecar written by Lightroom, Camera Raw or darktable
belongs to its photo: it is copied with it at export, never read or rewritten.
"""
from pathlib import Path


def companions(path):
    """Every sidecar of ``path``: Adobe replaces the extension (photo.xmp),
    darktable appends it (photo.nef.xmp). Each convention is probed once,
    including on case-insensitive volumes."""
    path = Path(path)
    found = []
    for stem in (path.stem, path.name):
        for extension in (".xmp", ".XMP"):
            candidate = path.with_name(stem + extension)
            if candidate.is_file():
                found.append(candidate)
                break
    return found
