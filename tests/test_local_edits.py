from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from atelier import local
from atelier.app import Window
from atelier.imaging import (
    IDENTITY_RECIPE,
    IDENTITY_STYLE,
    digest,
    features,
    render_pixels,
)
from atelier.pipeline import export_one
from atelier.prompt import describe, parse
from atelier.store import uid


def scene(height=300, width=400):
    """Ciel bleu en haut, herbe texturée en bas, visage au centre."""
    rng = np.random.default_rng(1)
    pixels = np.zeros((height, width, 3), np.float32)
    horizon = int(height * .38)
    pixels[:horizon] = [.45, .62, .88]
    pixels[horizon:] = [.25, .45, .18]
    pixels[horizon:] += rng.normal(0, .06, (height - horizon, width, 1)).astype(np.float32)
    y, x = np.mgrid[:height, :width]
    face = ((y - height * .55) / (height * .15)) ** 2 + ((x - width / 2) / (width * .085)) ** 2 < 1
    pixels[face] = [.85, .62, .52]
    return np.clip(pixels, 0, 1), face, horizon


def zone_mask(pixels, zones, invert=False):
    prepared = local.prepare([{"zones": zones, "invert": invert, "exposure": .5}], local.proxy(pixels))[0]
    return prepared.mask(pixels, 0, pixels.shape)


def labels(prompt):
    edits, unknown = parse(prompt)
    return [(e["zones"], e["invert"], {k: round(e[k], 2) for k in local.ADJUSTMENTS if e[k]}) for e in edits], unknown


@pytest.mark.parametrize(("prompt", "expected"), [
    ("Éclaircis légèrement les visages", [(["peau"], False, {"exposure": .2})]),
    ("ciel trop blanc", [(["ciel", "hautes_lumieres"], False, {"exposure": -.4})]),
    ("Fond plus sombre pour faire ressortir le sujet", [(["fond"], False, {"exposure": -.4})]),
    ("peau moins rouge", [(["peau", "rouges"], False, {"saturation": -.3})]),
    ("herbe moins fluo et réchauffe le bas", [(["verts"], False, {"saturation": -.3}),
                                              (["bas"], False, {"temperature": .35})]),
    ("assombris le ciel et les bords", [(["ciel"], False, {"exposure": -.4}), (["bords"], False, {"exposure": -.4})]),
    ("éclaircis le visage et réchauffe-le", [(["peau"], False, {"exposure": .4}), (["peau"], False, {"temperature": .35})]),
    ("débouche les ombres à gauche", [(["ombres", "gauche"], False, {"exposure": .4})]),
    ("baisse les hautes lumières", [(["hautes_lumieres"], False, {"exposure": -.4})]),
    ("assombris tout sauf le sujet", [(["sujet"], True, {"exposure": -.4})]),
    ("noir et blanc sauf la peau", [(["peau"], True, {"saturation": -1.})]),
    ("+0,7 IL sur le sujet", [(["sujet"], False, {"exposure": .7})]),
    ("sature les verts de 20 %", [(["verts"], False, {"saturation": .2})]),
    ("photo trop jaune", [(["image"], False, {"temperature": -.35})]),
    ("image un peu trop sombre", [(["image"], False, {"exposure": .2})]),
    ("moins lumineux en haut", [(["haut"], False, {"exposure": -.4})]),
    ("augmente le contraste du ciel", [(["ciel"], False, {"contrast": .15})]),
    ("trop foncé", [(["image"], False, {"exposure": .4})]),
])
def test_prompt_vocabulary(prompt, expected):
    assert labels(prompt) == (expected, [])


def test_prompt_reports_what_it_cannot_do():
    assert parse("enlève le poteau") == ([], ["enleve le poteau"])
    edits, unknown = parse("assombris le ciel, change le décor en plage")
    assert [e["zones"] for e in edits] == [["ciel"]] and unknown
    assert parse("   ") == ([], [])
    assert "Ciel" in parse("ciel plus sombre")[0][0]["label"]


def test_zone_masks_separate_sky_skin_subject_and_greens():
    pixels, face, horizon = scene()
    sky, grass = (slice(0, horizon - 20), slice(None)), (slice(-60, None), slice(0, 100))
    for zones, inside, outside in [(["ciel"], sky, face), (["peau"], face, sky), (["sujet"], face, sky),
                                   (["verts"], grass, face), (["haut"], sky, grass)]:
        mask = zone_mask(pixels, zones)
        assert mask[inside].mean() > .8, zones
        assert mask[outside].mean() < .1, zones
    background = zone_mask(pixels, ["fond"])
    assert background[sky].mean() > .9 and background[face].mean() < .1
    np.testing.assert_allclose(zone_mask(pixels, ["peau"], invert=True), 1 - zone_mask(pixels, ["peau"]), atol=1e-6)


def test_missing_zone_changes_nothing():
    pixels = np.full((120, 160, 3), [.25, .45, .18], np.float32)
    assert local.coverage([{"zones": ["ciel"], "exposure": 1.}], pixels) == [0.]
    plain = render_pixels(pixels, IDENTITY_RECIPE, {})
    edited = render_pixels(pixels, IDENTITY_RECIPE, {}, local=[{"zones": ["ciel"], "exposure": 1.}])
    np.testing.assert_array_equal(plain, edited)


def test_local_edit_only_changes_its_zone_and_can_be_disabled():
    pixels, face, horizon = scene()
    plain = render_pixels(pixels, IDENTITY_RECIPE, {}).astype(np.int64)
    edit = {"zones": ["ciel"], "exposure": -.7, "enabled": True, "strength": 1.}
    darker = render_pixels(pixels, IDENTITY_RECIPE, {}, local=[edit]).astype(np.int64)
    assert (darker[:horizon - 20] < plain[:horizon - 20]).all()
    # Outside the sky, at a distance from the horizon, the pixels are exactly preserved.
    np.testing.assert_array_equal(darker[horizon + 30:], plain[horizon + 30:])
    for change in ({"enabled": False}, {"strength": 0.}):
        np.testing.assert_array_equal(render_pixels(pixels, IDENTITY_RECIPE, {}, local=[dict(edit, **change)]), plain)
    stronger = render_pixels(pixels, IDENTITY_RECIPE, {}, local=[dict(edit, strength=2.)]).astype(np.int64)
    assert stronger[:50].mean() < darker[:50].mean()


def test_preview_and_full_resolution_masks_agree():
    small, _, _ = scene(300, 400)
    large = np.repeat(np.repeat(small, 4, 0), 4, 1)
    edits = [{"zones": ["sujet"], "exposure": .6}, {"zones": ["peau"], "temperature": .5}]
    preview = render_pixels(small, IDENTITY_RECIPE, {}, local=edits, bit_depth=8).astype(np.float32)
    export = render_pixels(large, IDENTITY_RECIPE, {}, local=edits, bit_depth=8).astype(np.float32)
    reduced = export.reshape(300, 4, 400, 4, 3).mean((1, 3))
    assert np.abs(reduced - preview).mean() < 2.


def test_export_contains_local_edits_and_never_copies_source(tmp_path):
    pixels, _, _ = scene()
    path = tmp_path / "scene.jpg"
    Image.fromarray(np.round(pixels * 255).astype(np.uint8)).save(path, quality=95)
    row = {"path": str(path), "data": {"digest": digest(path), "style": {}, "recipe": dict(IDENTITY_RECIPE),
                                       "local_edits": [{"zones": ["ciel"], "exposure": -1., "enabled": True}]}}
    for format in ("JPEG", "RAW"):
        target = Path(export_one(row, tmp_path / format, format))
        assert target.suffix == ".jpg" and target.read_bytes() != path.read_bytes()
        with Image.open(target) as exported, Image.open(path) as source:
            assert np.asarray(exported)[:60].mean() < np.asarray(source)[:60].mean() - 20
    tiff = Path(export_one(row, tmp_path / "TIFF", "TIFF"))
    import tifffile
    assert tifffile.imread(tiff).dtype == np.uint16
    row["data"]["local_edits"][0]["enabled"] = False
    copy = Path(export_one(row, tmp_path / "copy", "JPEG"))
    assert copy.read_bytes() == path.read_bytes()


def test_prompt_editor_applies_to_selection_and_removes(qapp, store, monkeypatch):
    profile = store.create_profile("A")
    batch = store.create_batch(profile, "Consignes", {}, .5)
    for i in range(2):
        store.save_photo(uid(), batch, f"{i}.png", {"decision": "keep", "reasons": [], "style": IDENTITY_STYLE,
                                                   "recipe": dict(IDENTITY_RECIPE), "initial_recipe": dict(IDENTITY_RECIPE)})
    monkeypatch.setattr(Window, "request_preview", lambda *_: None)
    window = Window(store.root)
    try:
        window.show()
        qapp.processEvents()
        window.pixmap = QPixmap(300, 200)
        window.gallery.selectAll()
        window.prompt_input.setText("ciel trop blanc, fond plus sombre, enlève le poteau")
        window.apply_prompt()
        stored = [r["data"]["local_edits"] for r in store.photos(batch)]
        assert all([e["zones"] for e in edits] == [["ciel", "hautes_lumieres"], ["fond"]] for edits in stored)
        assert "poteau" in window.prompt_feedback.text() and window.prompt_input.text() == ""
        assert window.local_list.count() == 2 and window.local_list.currentRow() == 1
        window.local_strength.setValue(150)
        assert all(r["data"]["local_edits"][1]["strength"] == 1.5 for r in store.photos(batch))
        window.local_list.item(0).setCheckState(Qt.CheckState.Unchecked)
        assert all(not r["data"]["local_edits"][0]["enabled"] for r in store.photos(batch))
        window.local_list.setCurrentRow(0)
        window.remove_local_button.click()
        assert all([e["zones"] for e in r["data"]["local_edits"]] == [["fond"]] for r in store.photos(batch))
        window.clear_local_button.click()
        assert all(r["data"]["local_edits"] == [] for r in store.photos(batch))
        assert window.local_list.count() == 0 and not window.clear_local_button.isEnabled()
    finally:
        window.close()


def validated_batch(store, profile, embedding, local_edits, initial=None):
    batch = store.create_batch(profile, "Appris", {"model": "m"}, .5)
    identifier = uid()
    store.save_photo(identifier, batch, "a.png", {
        "decision": "keep", "reasons": [], "style": IDENTITY_STYLE, "embedding": embedding,
        "recipe": dict(IDENTITY_RECIPE), "initial_recipe": dict(IDENTITY_RECIPE),
        "local_edits": local_edits, "initial_local_edits": initial or []})
    return batch, identifier


def test_local_edits_are_learned_only_at_validation_and_proposed_on_similar_photos(store):
    from atelier.analysis import propose
    profile = store.create_profile("Mariages")
    skin = parse("éclaircis légèrement les visages")[0]
    skin[0]["strength"] = 1.5
    batch, _ = validated_batch(store, profile, [1., 0.], skin)
    assert store.snapshot(profile, "m")["local_feedback"] == []
    store.validate(batch)
    snapshot = store.snapshot(profile, "m")
    [learned] = snapshot["local_feedback"][0]["local"]
    assert learned["zones"] == ["peau"] and learned["exposure"] == pytest.approx(.3)

    pixels, _, _ = scene()
    stats = features(pixels)
    similar = propose(stats, [1., 0.], snapshot, small=pixels)
    [proposal] = similar["local_edits"]
    assert proposal["proposed"] and proposal["zones"] == ["peau"] and proposal["exposure"] == pytest.approx(.3)
    assert "(appris)" in proposal["label"] and similar["initial_local_edits"] == [proposal]
    assert propose(stats, [0., 1.], snapshot, small=pixels)["local_edits"] == []


def test_refused_proposals_are_unlearned_and_kept_ones_add_nothing(store):
    from atelier.analysis import learned_local_edits
    profile = store.create_profile("Portraits")
    batch, _ = validated_batch(store, profile, [1., 0.], parse("fond plus sombre")[0])
    store.validate(batch)
    snapshot = store.snapshot(profile, "m")
    [proposal] = learned_local_edits([1., 0.], snapshot)

    # Kept unchanged: nothing new to learn.
    accepted, _ = validated_batch(store, profile, [1., 0.], [dict(proposal)], [dict(proposal)])
    store.validate(accepted)
    assert len(store.snapshot(profile, "m")["local_feedback"]) == 1

    # Unchecked: remembered as a refusal, which outweighs the single example.
    refused, _ = validated_batch(store, profile, [1., 0.], [dict(proposal, enabled=False)], [dict(proposal)])
    store.validate(refused)
    snapshot = store.snapshot(profile, "m")
    refusals = [f["local_refused"] for f in snapshot["local_feedback"] if "local_refused" in f]
    assert refusals == [[[["fond"], False, [-1, 0, 0, 0]]]]
    assert learned_local_edits([1., 0.], snapshot) == []


def test_learned_proposals_follow_the_batch_look_but_typed_prompts_stay(store, tmp_path):
    pixels, _, horizon = scene()
    path = tmp_path / "scene.jpg"
    Image.fromarray(np.round(pixels * 255).astype(np.uint8)).save(path, quality=95)
    proposal = dict(parse("ciel beaucoup plus sombre")[0][0], proposed=True)
    row = {"path": str(path), "data": {"digest": digest(path), "style": {}, "recipe": dict(IDENTITY_RECIPE),
                                       "local_edits": [proposal]}}
    copy = Path(export_one(row, tmp_path / "off", "JPEG", enabled=False))
    assert copy.read_bytes() == path.read_bytes()
    row["data"]["local_edits"] = [dict(proposal, proposed=False)]
    with Image.open(export_one(row, tmp_path / "typed", "JPEG", enabled=False)) as edited:
        assert np.asarray(edited)[:horizon - 20].mean() < pixels[:horizon - 20].mean() * 255 - 20
    # Hidden proposals are neither learned nor refused while the batch look is off.
    from atelier.local import lessons
    assert lessons([dict(proposal, enabled=False)], [proposal], batch_filter=False) == ([], [])


def test_prompt_quality_reports_kept_definition_and_jpeg_reencoding(tmp_path):
    from atelier.app import prompt_quality_text

    jpeg = tmp_path / "a.jpg"
    Image.new("RGB", (600, 400)).save(jpeg)
    text, warning = prompt_quality_text(jpeg, None)
    assert warning and "réencodé" in text and "600 × 400 px" in text and "aucune réduction" in text
    text, warning = prompt_quality_text(jpeg, (0, 0, .5, 1))
    assert "300 × 400 px" in text and "600 × 400 px" in text
    png = tmp_path / "a.png"
    Image.new("RGB", (6000, 4000)).save(png)
    text, warning = prompt_quality_text(png, None)
    assert not warning and "Sans perte" in text and "6 000 × 4 000 px (24,0 Mpx)" in text
    text, warning = prompt_quality_text(tmp_path / "missing.png", None)
    assert not warning and "ne réduit jamais" in text


def test_setting_values_never_wrap_away_from_their_unit(qapp):
    from atelier.app import SettingLabel

    widget = SettingLabel("Température")
    widget.set_value("7 500 K")
    assert widget.value.text() == "7 500 K" and not widget.value.wordWrap()
    assert widget.text() == "Température  7 500 K"
    assert " IL" in describe({"zones": ["ciel"], "exposure": -.4})
