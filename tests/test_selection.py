"""Scene-aware selection, learned profiles and learned colour look."""
import queue
import threading

import numpy as np
import pytest
from PIL import Image

from atelier import look as looks
from atelier import selection
from atelier.analysis import finalize
from atelier.config import discover
from atelier.imaging import IDENTITY_STYLE, NEUTRAL, capture_time, render
from atelier.pipeline import analysis_job, export_job, run_job, training_job
from atelier.training import match


def execute(store, job, encoder):
    run_job(store.root, job, queue.Queue(), threading.Event(), encoder)
    return store.job(job)


def stats(sharpness=.01, luma=.5):
    return {"luma": luma, "spread": .5, "saturation": .3, "sharpness": sharpness, "peak": sharpness * 2,
            "noise": .01, "black": 0., "white": 0., "aspect": 1.5, "rgb": [.5, .5, .5], "hash": "0" * 64}


def unit(vector):
    vector = np.asarray(vector, dtype=np.float64)
    return (vector / np.linalg.norm(vector)).tolist()


def test_scenes_split_on_time_gap_and_content():
    e = [unit([1, 0, 0]), unit([1, .05, 0]), unit([0, 1, 0]), unit([0, 1, .05]), unit([0, 1, 0])]
    labels = selection.scenes([0., 1., 2., 3., 100.], e)
    assert labels.tolist() == [0, 0, 1, 1, 2]


def test_decide_keeps_one_frame_per_moment_before_extras():
    labels = np.array([0, 0, 0, 1, 1, 2])
    embeddings = np.eye(6)
    scores = np.array([3., 2.9, 2.8, 1., .5, -1.])
    result = selection.decide(scores, labels, embeddings, keep_rate=.5, review_rate=.34)
    assert result.tolist().count("keep") == 3
    assert result[0] == "keep" and result[3] == "keep" and result[1] == "keep"
    assert result[5] == "review"  # moment without any kept frame comes first in review


def test_logistic_model_learns_a_separable_rule():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(300, 4))
    y = x[:, 0] + .2 * x[:, 1] > 0
    model = selection.fit_logistic(x, y, c=1.)
    assert np.mean((selection.score(model, x) > 0) == y) > .95


def test_match_by_name_suffix_and_by_appearance():
    rush = [{"name": "DSC08947.JPG", "embedding": unit([1, 0])}, {"name": "DSC08948.JPG", "embedding": unit([0, 1])},
            {"name": "IMG_1.JPG", "embedding": unit([1, 1])}]
    kept = [{"name": "DSC08947N&B.jpeg", "embedding": unit([0, 1])},
            {"name": "export final.jpg", "embedding": unit([0.02, 1])},
            {"name": "unrelated.jpg", "embedding": unit([-1, 0])}]
    assert match(rush, kept) == {0: 0, 1: 1}


def test_look_recovers_a_warm_contrast_edit():
    rng = np.random.default_rng(5)
    def edit(x):
        y = x.copy()
        y[..., 0] *= 1.08
        y[..., 2] *= .92
        return np.clip((y - .5) * 1.15 + .52, 0, 1)
    sources = [looks.sample(rng.random((60, 90, 3), dtype=np.float32) ** rng.uniform(.6, 1.6)) for _ in range(12)]
    targets = [edit(s) for s in sources]
    look = looks.fit(sources, targets)
    probe = looks.sample(rng.random((60, 90, 3), dtype=np.float32))
    rendered = looks.apply(look, probe, looks.knots_for(look, probe))
    assert np.mean(np.abs(rendered - edit(probe))) < .5 * np.mean(np.abs(probe - edit(probe)))


def test_rendered_look_is_resolution_independent():
    rng = np.random.default_rng(2)
    sources = [looks.sample(rng.random((40, 60, 3), dtype=np.float32)) for _ in range(6)]
    look = looks.fit(sources, [np.clip(s * 1.1, 0, 1) for s in sources])
    pixels = rng.random((80, 100, 3), dtype=np.float32)
    style = dict(IDENTITY_STYLE, knots=[0.] * looks.KNOTS)
    recipe = dict(NEUTRAL, intensity=1.)
    full = np.asarray(render(pixels, recipe, style, look))
    np.testing.assert_array_equal(full[::2, ::2], np.asarray(render(pixels[::2, ::2], recipe, style, look)))
    assert not np.array_equal(full, np.asarray(render(pixels, recipe, IDENTITY_STYLE)))


def test_discover_ignores_macos_metadata_files(tmp_path):
    Image.new("RGB", (8, 8)).save(tmp_path / "DSC1.jpg")
    (tmp_path / "._DSC1.jpg").write_bytes(b"\0\5\26\7")
    assert [p.split("/")[-1].split("\\")[-1] for p in discover([tmp_path])] == ["DSC1.jpg"]


def test_capture_time_reads_exif_subseconds(tmp_path):
    exif = Image.Exif()
    details = exif.get_ifd(34665)
    details[36867] = "2025:11:29 14:25:55"
    details[37521] = "743"
    Image.new("RGB", (8, 8)).save(tmp_path / "a.jpg", exif=exif)
    Image.new("RGB", (8, 8)).save(tmp_path / "b.png")
    first = capture_time(tmp_path / "a.jpg")
    assert first % 1 == pytest.approx(.743)
    assert capture_time(tmp_path / "b.png") is not None  # file time fallback


def burst_reportage(tmp_path):
    """Three moments of three frames; the photographer kept the sharp frame of each, slightly warmed."""
    rng = np.random.default_rng(9)
    rush, kept = [], []
    (tmp_path / "rush").mkdir()
    (tmp_path / "kept").mkdir()
    for moment in range(3):
        base = rng.integers(30, 220, (48, 64, 3)).astype(np.uint8)
        for frame in range(3):
            pixels = base if frame == 1 else np.asarray(Image.fromarray(base).resize((16, 12)).resize((64, 48)))
            exif = Image.Exif()
            exif.get_ifd(34665)[36867] = f"2025:11:29 14:{10 * moment:02d}:{frame:02d}"
            path = tmp_path / "rush" / f"DSC{moment}{frame}.jpg"
            Image.fromarray(pixels).save(path, exif=exif, quality=95)
            rush.append(str(path))
            if frame == 1:
                warm = np.clip(pixels.astype(np.float32) * [1.06, 1., .94], 0, 255).astype(np.uint8)
                target = tmp_path / "kept" / f"DSC{moment}{frame}.jpg"
                Image.fromarray(warm).save(target, quality=95)
                kept.append(str(target))
    return rush, kept


def test_training_job_learns_profile_then_selects_per_moment(store, encoder, tmp_path):
    rush, kept = burst_reportage(tmp_path)
    profile = store.create_profile("Mariages")
    job = execute(store, training_job(store, profile, rush, kept, "Mariage"), encoder)
    assert job["state"] == "done", job["error"]
    model = store.model(profile)
    assert model["photos"] == 9 and model["kept"] == 3
    assert model["selector"]["encoder"] == encoder.version
    snapshot = store.snapshot(profile, encoder.version)
    assert snapshot["selector"]["source"] == "profil"
    # Re-running is idempotent.
    assert execute(store, job["id"], encoder)["state"] == "done"
    analysis = execute(store, analysis_job(store, profile, rush), encoder)
    assert analysis["state"] == "done", analysis["error"]
    rows = store.photos(analysis["payload"]["batch"])
    assert {r["data"]["scene"] for r in rows} == {0, 1, 2}
    for scene in range(3):
        members = [r for r in rows if r["data"]["scene"] == scene]
        assert len({r["data"]["group"] for r in members}) == 1
    assert any("Modèle de sélection : profil" in r["data"]["reasons"] for r in rows)
    store.wipe(profile)
    assert store.model(profile) is None and store.training(profile) == []


def test_learned_look_is_exported(store, encoder, tmp_path):
    rush, kept = burst_reportage(tmp_path)
    profile = store.create_profile("Filtre")
    snapshot_look = {"version": 1, "lut_size": 2, "lut": [[0, 0, 0], [0, 0, 1], [0, 1, 0], [0, 1, 1],
                                                           [1, 0, 0], [1, 0, 1], [1, 1, 0], [1, 1, 1]],
                     "tone": {"mu": [0.] * 15, "sd": [1.] * 15, "coef": [[.1] * looks.KNOTS] + [[0.] * looks.KNOTS] * 15}}
    store.set_model(profile, {"reportages": 1, "photos": 9, "kept": 3, "pairs": 3, "selector": None, "look": snapshot_look})
    job = execute(store, analysis_job(store, profile, rush[:3]), encoder)
    batch = job["payload"]["batch"]
    rows = store.photos(batch)
    assert all(r["data"]["style"]["knots"] == pytest.approx([.1] * looks.KNOTS) for r in rows)
    for row in rows:
        row["data"]["decision"] = "keep"
    store.save_photos(rows)
    store.validate(batch)
    exported = execute(store, export_job(store, batch, tmp_path / "out", "PNG"), encoder)
    with Image.open(exported["payload"]["outputs"][0]) as image, Image.open(rows[0]["path"]) as original:
        brighter = np.asarray(image.convert("L"), dtype=np.float32).mean() - np.asarray(original.convert("L"), dtype=np.float32).mean()
    assert brighter > 15  # +0.1 tone shift ≈ +25 levels


def test_profile_without_references_can_analyse(store, photos, encoder):
    profile = store.create_profile("Neuf")
    job = execute(store, analysis_job(store, profile, photos), encoder)
    assert job["state"] == "done", job["error"]
    rows = store.photos(job["payload"]["batch"])
    assert {r["data"]["decision"] for r in rows} & {"keep", "review"}
    assert all(r["data"]["reasons"] for r in rows)


def test_finalize_without_valid_rows_is_harmless():
    rows = [{"id": "e", "path": "e.jpg", "data": {"error": "x", "decision": "error", "proposed": "error"}}]
    assert finalize(rows, {"model": "m"}, .5) == rows
