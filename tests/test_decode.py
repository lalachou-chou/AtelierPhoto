"""Analysis copy: what every import, reportage and reference goes through."""
import numpy as np
import pytest
from PIL import Image

from atelier.imaging import ANALYSIS_SIZE, CorruptPhoto, decode, features

TECHNICAL = {"luma", "spread", "saturation", "sharpness", "peak", "noise", "black", "white"}


def test_large_photo_is_oriented_and_reduced(tmp_path):
    path = tmp_path / "portrait.jpg"
    image = Image.new("RGB", (3000, 2000), "red")
    exif = image.getexif()
    exif[274] = 6  # rotate 90° clockwise to display
    image.save(path, exif=exif)
    copy = decode(path)
    assert copy.mode == "RGB"
    assert copy.width < copy.height and max(copy.size) == ANALYSIS_SIZE


def test_transparency_is_composed_on_white(tmp_path):
    path = tmp_path / "logo.png"
    Image.new("RGBA", (40, 30), (0, 0, 0, 0)).save(path)
    assert decode(path).getpixel((5, 5)) == (255, 255, 255)


def test_damaged_and_unreadable_files_are_told_apart(tmp_path):
    damaged = tmp_path / "damaged.jpg"
    Image.new("RGB", (200, 200), "blue").save(damaged)
    damaged.write_bytes(damaged.read_bytes()[:300])
    with pytest.raises(CorruptPhoto):
        decode(damaged)
    text = tmp_path / "notes.jpg"
    text.write_text("not a photo", encoding="utf-8")
    with pytest.raises(ValueError, match="illisible") as failure:
        decode(text)
    assert not isinstance(failure.value, CorruptPhoto)
    with pytest.raises(ValueError, match="Format non pris en charge"):
        decode(tmp_path / "photo.gif")


def test_features_are_the_sorting_measures_only(tmp_path):
    rng = np.random.default_rng(0)
    image = Image.fromarray(rng.integers(0, 255, (300, 400, 3), dtype=np.uint8))
    stats = features(image)
    assert set(stats) == TECHNICAL
    assert image.size == (400, 300)  # measured on a copy
    with pytest.raises(ValueError, match="trop petite"):
        features(Image.new("RGB", (6, 6)))
