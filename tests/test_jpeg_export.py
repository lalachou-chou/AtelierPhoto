from pathlib import Path

import pytest
from PIL import Image, JpegImagePlugin

from atelier.imaging import IDENTITY_RECIPE, digest
from atelier.pipeline import export_one


@pytest.fixture
def jpeg(tmp_path):
    path = tmp_path / "original.JPEG"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (40, 20), (80, 60, 40)).save(path, quality=72, exif=exif, comment=b"original")
    return {"path": str(path), "data": {"digest": digest(path), "style": {}, "recipe": dict(IDENTITY_RECIPE)}}


@pytest.mark.parametrize("format", ["JPEG", "RAW"])
def test_neutral_export_preserves_entire_jpeg(tmp_path, jpeg, format):
    jpeg["data"].update(crop=[0, 0, 1, 1], style={"exposure": .5, "knots": []})
    target = Path(export_one(jpeg, tmp_path, format, look={}))
    assert target.read_bytes() == Path(jpeg["path"]).read_bytes()


def test_disabled_filter_preserves_jpeg_until_manual_edits(tmp_path, jpeg):
    jpeg["data"]["recipe"]["exposure"] = 1
    target = Path(export_one(jpeg, tmp_path, "JPEG", enabled=False))
    assert target.read_bytes() == Path(jpeg["path"]).read_bytes()
    jpeg["data"]["manual_recipe"] = jpeg["data"]["recipe"]
    with Image.open(export_one(jpeg, tmp_path, "JPEG", enabled=False)) as edited:
        assert edited.size == (20, 40)
        assert edited.getpixel((5, 5))[0] > 140
        assert JpegImagePlugin.get_sampling(edited) == 0
        assert all(set(table) == {1} for table in edited.quantization.values())


def test_crop_alone_renders_jpeg(tmp_path, jpeg):
    jpeg["data"]["crop"] = [0, 0, .5, 1]
    with Image.open(export_one(jpeg, tmp_path, "JPEG", enabled=False)) as edited:
        assert edited.size == (10, 40)


def test_learned_look_alone_renders_jpeg(tmp_path, jpeg, monkeypatch):
    jpeg["data"]["recipe"]["intensity"] = 1.
    jpeg["data"]["style"]["knots"] = [0., 1.]
    monkeypatch.setattr("atelier.look.apply", lambda look, pixels, knots: pixels * 0.)
    with Image.open(export_one(jpeg, tmp_path, "JPEG", look={})) as edited:
        assert edited.getpixel((5, 5)) == (0, 0, 0)


def test_png_with_jpeg_extension_is_encoded_as_jpeg(tmp_path, jpeg):
    path = Path(jpeg["path"])
    Image.new("RGB", (20, 30), "white").save(path, format="PNG")
    jpeg["data"]["digest"] = digest(path)
    with Image.open(export_one(jpeg, tmp_path, "JPEG")) as edited:
        assert edited.format == "JPEG"
