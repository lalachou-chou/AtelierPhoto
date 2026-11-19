"""References imported as JPEG, RAW alone or RAW + XMP sidecar."""
import queue
import threading

import numpy as np
import pytest
from PIL import Image

from atelier import xmp
from atelier.analysis import propose
from atelier.imaging import features
from atelier.pipeline import run_job, training_update_job
from atelier.training_dialog import reference_kinds


class Encoder:
    version = "reference-xmp-test"

    def encode(self, image):
        return [1., 0., 0.]


def lightroom(path, body="", **settings):
    attributes = "\n".join(f'   crs:{k}="{v}"' for k, v in settings.items())
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="" xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   crs:Version="15.0" crs:HasSettings="True"
{attributes}>{body}
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
""", encoding="utf-8")
    return path


class Raw:
    """rawpy stand-in: a flat mid-grey 16-bit development."""
    flip = 0

    def __init__(self, *args):
        self.sizes = type("Sizes", (), {"flip": Raw.flip})()
        self.camera_whitebalance = [2., 1., 1.5, 0.]
        self.rgb_xyz_matrix = np.eye(4, 3)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def postprocess(self, **options):
        pixels = np.full((48, 64, 3), 22000, dtype=np.uint16)
        pixels[:, :8] = 6000
        return pixels


@pytest.fixture
def fake_raw(monkeypatch):
    import rawpy
    monkeypatch.setattr(rawpy, "imread", Raw)


def test_read_settings_accepts_attributes_and_elements_first_wins(tmp_path):
    path = lightroom(tmp_path / "a.xmp", body="""
   <crs:Saturation>-20</crs:Saturation>
   <crs:MaskGroupBasedCorrections><rdf:Seq><rdf:li crs:Exposure2012="3"/></rdf:Seq></crs:MaskGroupBasedCorrections>""",
                     Exposure2012="+0.80")
    settings = xmp.read_settings(path)
    assert settings["crs:Exposure2012"] == "+0.80"
    assert settings["crs:Saturation"] == "-20"
    assert settings["local"] == "True"
    developed = xmp.development(settings, tmp_path / "a.jpg")
    assert developed["style"]["exposure"] == pytest.approx(.8)
    assert "Retouches locales" in developed["ignored"]


def test_development_maps_basic_panel(tmp_path):
    settings = xmp.read_settings(lightroom(
        tmp_path / "b.xmp", Exposure2012="-0.5", Contrast2012="+40", Saturation="+10", Vibrance="+20",
        IncrementalTemperature="+20", Shadows2012="+60", Highlights2012="-40", Clarity2012="+15",
        HasCrop="True", CropLeft="0.1", CropTop="0", CropRight="0.9", CropBottom="1"))
    developed = xmp.development(settings, tmp_path / "b.jpg")
    style = developed["style"]
    assert style == pytest.approx({"exposure": -.5, "contrast": .2, "saturation": .2, "temperature": .5})
    assert developed["tones"] == pytest.approx({"Shadows": .6, "Highlights": -.4})
    assert developed["crop"] == pytest.approx((.1, 0, .9, 1))
    assert developed["ignored"] == []
    assert developed["tools"]["clarity"] == pytest.approx(.15)
    monochrome = xmp.development({"crs:ConvertToGrayscale": "True"}, tmp_path / "c.jpg")
    assert monochrome["style"]["saturation"] == -1


def test_atelier_sidecar_is_read_exactly(tmp_path):
    path = tmp_path / "d.xmp"
    path.write_bytes(xmp.sidecar({"intensity": 1., "exposure": .3, "temperature": .1, "contrast": .05,
                                  "saturation": -.2}, {}, raw=False))
    style = xmp.development(xmp.read_settings(path), tmp_path / "d.jpg")["style"]
    assert style == pytest.approx({"exposure": .3, "temperature": .1, "contrast": .05, "saturation": -.2}, abs=1e-4)


@pytest.mark.parametrize("flip", range(8))
def test_display_crop_inverts_raw_crop(flip):
    crop = (.1, .2, .7, .95)
    assert xmp.raw_to_display(xmp.raw_crop(crop, flip), flip) == pytest.approx(crop)


def test_raw_white_balance_relative_to_as_shot(tmp_path, monkeypatch):
    monkeypatch.setattr(xmp, "as_shot_kelvin", lambda path: 5000.)
    source = tmp_path / "e.nef"

    def warmth(kelvin):
        return xmp.development({"crs:WhiteBalance": "Custom", "crs:Temperature": str(kelvin)}, source)["style"]["temperature"]

    assert warmth(5000) == pytest.approx(0, abs=1e-3)
    assert warmth(6500) > .05 > -.05 > warmth(4000)
    assert xmp.development({"crs:WhiteBalance": "As Shot", "crs:Temperature": "9000"}, source)["style"]["temperature"] == 0


def test_find_sidecar_both_conventions(tmp_path):
    adobe, darktable, alone = tmp_path / "a.nef", tmp_path / "b.cr3", tmp_path / "c.arw"
    for path in (adobe, darktable, alone):
        path.write_bytes(b"raw")
    lightroom(tmp_path / "a.xmp")
    lightroom(tmp_path / "b.cr3.xmp")
    assert xmp.find_sidecar(adobe).name == "a.xmp"
    assert xmp.find_sidecar(darktable).name == "b.cr3.xmp"
    assert xmp.find_sidecar(alone) is None
    jpeg = tmp_path / "d.jpg"
    Image.new("RGB", (8, 8)).save(jpeg)
    assert reference_kinds([adobe, darktable, alone, jpeg]) == (
        "2 RAW + XMP · 1 RAW seul (ressemblance et cadrage) · 1 JPEG/PNG")


def test_raw_xmp_reference_teaches_the_edit_and_raw_alone_only_resemblance(store, tmp_path, fake_raw):
    profile = store.create_profile("RAW")
    edited, plain = tmp_path / "edited.nef", tmp_path / "plain.nef"
    edited.write_bytes(b"raw-1")
    plain.write_bytes(b"raw-2")
    lightroom(tmp_path / "edited.xmp", Exposure2012="+1.00",
              HasCrop="True", CropLeft="0.25", CropTop="0", CropRight="1", CropBottom="1")
    job = training_update_job(store, profile, [], [{"name": "Exemples", "paths": [str(edited), str(plain)]}])
    run_job(store.root, job, queue.SimpleQueue(), threading.Event(), Encoder)
    assert store.job(job)["state"] == "done"
    references = {r["name"]: r["data"] for r in store.references(profile)}
    developed, alone = references["edited.nef"], references["plain.nef"]
    assert developed["source"] == "raw+xmp" and alone["source"] == "raw"
    assert developed["after"]["luma"] > developed["before"]["luma"] + .1
    # The crop removed the dark left strip and set the delivered aspect.
    assert developed["features"]["aspect"] == pytest.approx(1., rel=.05)
    assert alone["render"] is False and "before" not in alone

    pixels = np.full((40, 40, 3), .35, dtype=np.float32)
    stats = features(pixels)
    snapshot = {"references": [alone], "feedback": []}
    assert propose(stats, [1., 0., 0.], snapshot)["style"]["exposure"] == 0
    snapshot = {"references": [developed, alone], "feedback": []}
    assert propose(stats, [1., 0., 0.], snapshot)["style"]["exposure"] > .3

    # Editing the sidecar makes a new reference instead of reusing the old one.
    lightroom(tmp_path / "edited.xmp", Exposure2012="-1.00")
    store.db.execute("DELETE FROM reference_members")
    job = training_update_job(store, profile, [], store.reference_groups(profile))
    run_job(store.root, job, queue.SimpleQueue(), threading.Event(), Encoder)
    darker = [r["data"] for r in store.references(profile) if r["data"].get("after")
              and r["data"]["after"]["luma"] < r["data"]["before"]["luma"]]
    assert darker
