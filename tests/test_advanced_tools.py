"""Clarté, courbe et TSL ; retouches locales écrites en masques Lightroom dans le XMP."""
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtGui import QPixmap

from atelier import lightroom
from atelier import tools as advanced
from atelier.app import Window
from atelier.imaging import (
    IDENTITY_RECIPE,
    IDENTITY_STYLE,
    digest,
    features,
    render_pixels,
)
from atelier.pipeline import export_one
from atelier.prompt import parse
from atelier.store import uid
from atelier.xmp import read_settings, read_tools, sidecar
from tests.test_local_edits import scene

CRS = "http://ns.adobe.com/camera-raw-settings/1.0/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


def tools(**changes):
    result = advanced.identity()
    for key, value in changes.items():
        if key in advanced.CURVE:
            result["curve"][key] = value
        elif key in advanced.COLORS:
            result["hsl"][key] = list(value)
        else:
            result[key] = value
    return result


def rendered(pixels, value=None, **kw):
    return render_pixels(pixels, IDENTITY_RECIPE, {}, bit_depth=16, tools=value, **kw).astype(np.float64) / 65535


def test_clarity_adds_local_contrast_without_shifting_the_mean():
    rng = np.random.default_rng(3)
    base = np.full((200, 300, 3), .45, np.float32)
    base += (rng.normal(0, .04, (200, 300, 1)) + np.linspace(-.1, .1, 300)[None, :, None]).astype(np.float32)
    plain, crisp, soft = (rendered(base, tools(clarity=c)) for c in (0., .8, -.8))
    detail = [np.std(x - np.mean(x, axis=(0, 1))) for x in (plain, crisp, soft)]
    assert detail[1] > detail[0] * 1.15 > detail[2] * 1.15
    assert abs(crisp.mean() - plain.mean()) < .01 and abs(soft.mean() - plain.mean()) < .01


def test_parametric_curve_moves_its_tone_range_and_stays_monotone():
    ramp = np.repeat(np.linspace(0, 1, 512, dtype=np.float32)[None, :, None], 3, axis=2).repeat(4, 0)
    lifted = rendered(ramp, tools(shadows=1.))[0, :, 0]
    plain = rendered(ramp)[0, :, 0]
    assert lifted[64] > plain[64] + .05 and abs(lifted[-20] - plain[-20]) < .005
    assert np.all(np.diff(lifted) >= -1e-6)
    master, _ = advanced.curve_tables(advanced.normalize(tools(darks=-1., lights=1.)))
    assert np.all(np.diff(master) >= 0)
    points = advanced.normalize({"points": {"master": [[0, 0], [.25, .15], [.75, .85], [1, 1]]}})
    master, _ = advanced.curve_tables(points)
    assert master[1024] == pytest.approx(.15, abs=.01) and np.all(np.diff(master) >= 0)


def test_hsl_touches_only_the_chosen_colour_and_never_greys():
    # Vert à 120°, bleu pur à 240° (centres des couleurs de Lightroom), gris, rouge.
    patches = np.array([[[.2, .6, .2], [.2, .2, .8], [.5, .5, .5], [.8, .3, .25]]], np.float32).repeat(8, 0)
    plain = rendered(patches)
    shifted = rendered(patches, tools(verts=(-1., 0., 0.)))
    green, blue, grey, red = (shifted[0, i] for i in range(4))
    assert green[0] > plain[0, 0][0] + .1  # vert → jaune : plus de rouge
    np.testing.assert_allclose(blue, plain[0, 1], atol=2e-3)
    np.testing.assert_allclose(grey, plain[0, 2], atol=1e-4)
    np.testing.assert_allclose(red, plain[0, 3], atol=2e-3)
    desaturated = rendered(patches, tools(bleus=(0., -1., 0.)))[0, 1]
    assert np.ptp(desaturated) < .01
    darker = rendered(patches, tools(rouges=(0., 0., -1.)))[0, 3]
    assert darker.max() < plain[0, 3].max() - .1


def test_preview_and_full_resolution_tools_agree():
    small, _, _ = scene(150, 200)
    large = np.repeat(np.repeat(small, 4, 0), 4, 1)
    value = tools(clarity=.7, shadows=.5, verts=(.5, .4, -.3))
    edits = parse("plus de clarté sur le sujet, les verts vers le jaune")[0]
    preview = rendered(small, value, local=edits)
    export = rendered(large, value, local=edits).reshape(150, 4, 200, 4, 3).mean((1, 3))
    assert np.abs(export - preview).mean() < 2 / 255


def test_active_tools_follow_the_batch_filter():
    proposal = tools(clarity=.4)
    data = {"tools": tools(clarity=.6, verts=(0., .2, 0.)), "initial_tools": proposal}
    assert advanced.active(data, True)["clarity"] == pytest.approx(.6)
    manual = advanced.active(data, False)
    assert manual["clarity"] == pytest.approx(.2) and manual["hsl"]["verts"] == pytest.approx([0., .2, 0.])
    assert advanced.active({"tools": proposal, "initial_tools": proposal}, False) is None
    assert advanced.active({}, True) is None
    assert advanced.normalize({"clarity": 7, "hsl": {"verts": [2]}})["hsl"]["verts"] == [1., 0., 0.]


@pytest.mark.parametrize(("prompt", "expected"), [
    ("adoucis la peau", (["peau"], {"clarity": -.3})),
    ("plus de clarté", (["image"], {"clarity": .3})),
    ("fais ressortir les détails du sujet", (["sujet"], {"clarity": .3})),
    ("lisse légèrement le visage", (["peau"], {"clarity": -.15})),
    ("les verts vers le jaune", (["verts"], {"hue": -.5})),
    ("verts plus jaunes", (["verts"], {"hue": -.5})),
    ("ciel tirant sur le turquoise", (["ciel"], {"hue": -.5})),
    ("peau vers le rouge", (["peau"], {"hue": -.5})),
    ("adoucis l'image", (["image"], {"contrast": -.15})),
])
def test_prompt_clarity_and_hue(prompt, expected):
    [edit], unknown = parse(prompt)
    values = {k: round(edit[k], 2) for k in ("exposure", "temperature", "contrast", "saturation", "clarity", "hue")
              if edit[k]}
    assert (edit["zones"], values) == expected and unknown == []


def test_xmp_round_trip_of_clarity_curves_and_hsl(tmp_path):
    value = tools(clarity=.25, shadows=.4, highlights=-.3, verts=(-.2, .3, .1))
    value["points"] = {"master": [[0, 0], [.25, .2], [1, 1]], "blue": [[0, .05], [1, 1]]}
    path = tmp_path / "a.xmp"
    path.write_bytes(sidecar(dict(IDENTITY_RECIPE), {}, tools=value))
    ET.parse(path)
    settings = read_settings(path)
    assert settings["crs:Clarity2012"] == "+25" and settings["crs:HueAdjustmentGreen"] == "-20"
    back = read_tools(settings)
    assert back["clarity"] == pytest.approx(.25) and back["curve"]["highlights"] == pytest.approx(-.3)
    assert back["hsl"]["verts"] == pytest.approx([-.2, .3, .1])
    assert back["points"]["master"][1] == pytest.approx([64 / 255, 51 / 255])
    assert back["points"]["blue"][0] == pytest.approx([0, 13 / 255])


def test_nested_look_and_masks_do_not_override_global_settings(tmp_path):
    path = tmp_path / "b.xmp"
    path.write_text(f"""<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="{RDF}">
<rdf:Description xmlns:crs="{CRS}" crs:Version="16.0">
 <crs:Look><rdf:Description crs:Name="Vivid"><crs:Parameters><rdf:Description crs:Clarity2012="+90">
  <crs:ToneCurvePV2012><rdf:Seq><rdf:li>0, 40</rdf:li><rdf:li>255, 255</rdf:li></rdf:Seq></crs:ToneCurvePV2012>
 </rdf:Description></crs:Parameters></rdf:Description></crs:Look>
 <crs:Clarity2012>+10</crs:Clarity2012>
</rdf:Description></rdf:RDF></x:xmpmeta>""", encoding="utf-8")
    back = read_tools(read_settings(path))
    assert back["clarity"] == pytest.approx(.1) and "points" not in back


def components(xml):
    root = ET.fromstring(f'<root xmlns:crs="{CRS}" xmlns:rdf="{RDF}">{xml}</root>')
    result = []
    for correction in root.findall("./crs:MaskGroupBasedCorrections/rdf:Seq/rdf:li/rdf:Description", {"crs": CRS, "rdf": RDF}):
        masks = []
        for item in correction.findall(f"./{{{CRS}}}CorrectionMasks/{{{RDF}}}Seq/{{{RDF}}}li"):
            node = item.find(f"{{{RDF}}}Description") if item.find(f"{{{RDF}}}Description") is not None else item
            masks.append({k.split("}")[1]: v for k, v in node.attrib.items()} | {"node": node})
        result.append(({k.split("}")[1]: v for k, v in correction.attrib.items()}, masks))
    return result


def test_lightroom_masks_for_each_kind_of_zone():
    small, _, _ = scene()
    edits = []
    for prompt in ("ciel plus sombre", "fond moins saturé", "les verts vers le jaune", "débouche les ombres à gauche",
                   "assombris tout sauf le centre", "réchauffe la peau", "plus de clarté", "noir et blanc sauf la peau"):
        edits += parse(prompt)[0]
    found = components(lightroom.corrections(edits, small=small))
    assert len(found) == len(edits)
    kinds = [[m["What"] for m in masks] for _, masks in found]
    assert kinds == [["Mask/Image"], ["Mask/Image"], ["Mask/RangeMask"], ["Mask/RangeMask", "Mask/Gradient"],
                     ["Mask/CircularGradient"], ["Mask/RangeMask"], ["Mask/Gradient"], ["Mask/RangeMask"]]
    settings = [s for s, _ in found]
    assert float(settings[0]["LocalExposure2012"]) == pytest.approx(-.1)  # −0,4 IL / 4
    assert float(settings[2]["LocalHue"]) == pytest.approx(-.5)
    assert float(settings[6]["LocalClarity2012"]) == pytest.approx(.3)
    sky, background = found[0][1][0], found[1][1][0]
    assert (sky["MaskSubType"], sky["MaskInverted"]) == ("2", "false")
    assert (background["MaskSubType"], background["MaskInverted"]) == ("1", "true")
    shadows, left = found[3][1]
    assert (shadows["MaskBlendMode"], left["MaskBlendMode"]) == ("0", "2")  # intersection
    lum = shadows["node"].find(f"{{{CRS}}}CorrectionRangeMask")
    assert lum.get(f"{{{CRS}}}LumRange") == "0.000000 0.000000 0.120000 0.450000"
    assert float(left["FullX"]) < float(left["ZeroX"])
    centre = found[4][1][0]
    assert centre["MaskInverted"] == "true" and centre["Flipped"] == "false"
    green = found[2][1][0]["node"].find(f".//{{{RDF}}}li")
    r, g, b, x, y, zero = (float(v) for v in green.text.split())
    assert g > r and g > b and y > .38 and zero == 0  # échantillon pris dans l'herbe, sous l'horizon
    assert found[7][1][0]["MaskInverted"] == "true"


def test_mask_coordinates_follow_crop_and_sensor_orientation():
    frame = lightroom.Frame((.2, 0., .8, 1.), flip=0)
    assert frame.point(0, .5) == pytest.approx((.2, .5))
    rotated = lightroom.Frame(None, flip=5)
    # flip 5 = transposition puis miroir horizontal, comme raw_crop.
    from atelier.xmp import raw_crop
    assert rotated.point(.1, .3) == pytest.approx(raw_crop((.1, .3, .1, .3), 5)[:2])


def test_combined_inverted_zones_use_de_morgan():
    [edit] = parse("assombris tout sauf le ciel en haut")[0]
    [(_, masks)] = components(lightroom.corrections([edit]))
    assert [(m["MaskInverted"], m["MaskBlendMode"]) for m in masks] == [("true", "0"), ("true", "0")]


class Raw:
    def __init__(self, *args):
        self.sizes = type("Sizes", (), {"flip": 0})()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def postprocess(self, **options):
        pixels, _, _ = scene()
        return np.round(pixels * 65535).astype(np.uint16)


def test_raw_export_keeps_the_raw_and_writes_masks_and_tools(tmp_path, monkeypatch):
    import rawpy
    monkeypatch.setattr(rawpy, "imread", Raw)
    source = tmp_path / "photo.nef"
    source.write_bytes(b"synthetic raw")
    row = {"path": str(source), "data": {"digest": digest(source), "style": {}, "recipe": dict(IDENTITY_RECIPE),
           "local_edits": parse("ciel plus sombre et sature les verts")[0], "tools": tools(clarity=.3)}}
    target = Path(export_one(row, tmp_path / "out", "RAW"))
    assert target.suffix == ".nef" and target.read_bytes() == source.read_bytes()
    xmp = target.with_suffix(".xmp")
    ET.parse(xmp)
    settings = read_settings(xmp)
    assert settings["local"] == "True" and settings["crs:Clarity2012"] == "+30"
    # Une retouche désactivée ou retirée n'est pas écrite.
    row["data"]["local_edits"] = [dict(e, enabled=False) for e in row["data"]["local_edits"]]
    row["data"]["tools"] = {}
    target = Path(export_one(row, tmp_path / "off", "RAW"))
    assert not target.with_suffix(".xmp").exists()


def test_tools_are_learned_at_validation_and_proposed(store):
    from atelier.analysis import propose
    profile = store.create_profile("Clarté")
    batch = store.create_batch(profile, "Appris", {"model": "m"}, .5)
    store.save_photo(uid(), batch, "a.png", {
        "decision": "keep", "reasons": [], "style": IDENTITY_STYLE, "embedding": [1., 0.],
        "recipe": dict(IDENTITY_RECIPE), "initial_recipe": dict(IDENTITY_RECIPE),
        "tools": tools(clarity=.4, verts=(0., -.3, 0.)), "initial_tools": {}})
    assert store.snapshot(profile, "m")["tools_feedback"] == []
    store.validate(batch)
    snapshot = store.snapshot(profile, "m")
    pixels, _, _ = scene()
    proposal = propose(features(pixels), [1., 0.], snapshot, small=pixels)
    assert proposal["tools"]["clarity"] == pytest.approx(.4)
    assert proposal["tools"]["hsl"]["verts"] == pytest.approx([0., -.3, 0.])
    assert proposal["initial_tools"] == proposal["tools"]
    assert propose(features(pixels), [0., 1.], snapshot, small=pixels)["tools"] == {}


def test_editor_tool_sliders_edit_the_selection(qapp, store, monkeypatch):
    profile = store.create_profile("A")
    batch = store.create_batch(profile, "Outils", {}, .5)
    for i in range(2):
        store.save_photo(uid(), batch, f"{i}.png", {"decision": "keep", "reasons": [], "style": IDENTITY_STYLE,
                                                   "recipe": dict(IDENTITY_RECIPE), "initial_recipe": dict(IDENTITY_RECIPE),
                                                   "initial_tools": tools(clarity=.2)})
    monkeypatch.setattr(Window, "request_preview", lambda *_: None)
    window = Window(store.root)
    try:
        window.show()
        qapp.processEvents()
        window.pixmap = QPixmap(300, 200)
        window.gallery.selectAll()
        window.tool_sliders[("clarity",)].setValue(50)
        window.hsl_color.setCurrentIndex(advanced.COLORS.index("bleus"))
        window.tool_sliders[("hsl", 1)].setValue(-40)
        window.tool_sliders[("curve", "shadows")].setValue(30)
        for row in store.photos(batch):
            saved = row["data"]["tools"]
            assert saved["clarity"] == pytest.approx(.5) and saved["hsl"]["bleus"][1] == pytest.approx(-.4)
            assert saved["curve"]["shadows"] == pytest.approx(.3)
        assert "bleus" in window.tools_summary.text()
        window.hsl_color.setCurrentIndex(advanced.COLORS.index("verts"))
        assert window.tool_sliders[("hsl", 1)].value() == 0
        window.tool_sliders[("clarity",)].reset.emit()
        assert all(r["data"]["tools"]["clarity"] == pytest.approx(.2) for r in store.photos(batch))
        window.reset_tools_button.click()
        assert all(r["data"]["tools"] == advanced.normalize(tools(clarity=.2)) for r in store.photos(batch))
    finally:
        window.close()


def test_export_task_carries_zone_edits_and_tools(store, tmp_path):
    """The batch export task (not only export_one) must render zone edits and tools."""
    import queue
    import threading

    from PIL import Image

    from atelier.pipeline import export_job, run_job
    pixels, _, _ = scene()
    source = tmp_path / "scene.jpg"
    Image.fromarray(np.round(pixels * 255).astype(np.uint8)).save(source, quality=95)
    profile = store.create_profile("Export")
    batch = store.create_batch(profile, "Lot", {"model": "m"}, .5)
    store.save_photo(uid(), batch, str(source), {
        "decision": "keep", "validated": True, "digest": digest(source), "style": {}, "reasons": [],
        "recipe": dict(IDENTITY_RECIPE), "initial_recipe": dict(IDENTITY_RECIPE),
        "local_edits": parse("ciel beaucoup plus sombre")[0], "tools": tools(bleus=(0., -1., 0.)),
        "initial_tools": {}})
    job = export_job(store, batch, tmp_path / "out", "PNG")
    run_job(store.root, job, queue.SimpleQueue(), threading.Event())
    [output] = store.job(job)["payload"]["outputs"]
    with Image.open(output) as exported:
        top = np.asarray(exported, dtype=np.float32)[:60] / 255
    sky = pixels[:60]
    assert top.mean() < sky.mean() - .1  # ciel assombri par la consigne
    assert np.ptp(top.mean((0, 1))) < np.ptp(sky.mean((0, 1))) / 2  # bleus désaturés par la TSL
