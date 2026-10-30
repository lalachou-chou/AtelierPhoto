import copy
import queue
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QTextBrowser

from atelier.analysis import LEARNED_NEUTRAL, finalize, propose
from atelier.app import Window
from atelier.imaging import color_features, features, render
from atelier.pipeline import reference_job, run_job, training_update_job
from atelier.selection import FEATURE_VERSION, TECH_KEYS
from atelier.store import Store
from atelier.training_dialog import TrainingDialog


class Encoder:
    version = "reference-test"

    def encode(self, image):
        vector = np.asarray(image).mean(axis=(0, 1))
        return (vector / np.linalg.norm(vector)).tolist()


def execute(store, identifier, cancel=None):
    run_job(store.root, identifier, queue.SimpleQueue(), cancel or threading.Event(), Encoder)
    return store.job(identifier)


def test_reference_import_resume_duplicates_and_frozen_batches(store, tmp_path):
    profile = store.create_profile("Références")
    other = store.create_profile("Autre")
    store.set_model(profile, {"previous": True})
    before = store.snapshot(profile, Encoder.version)
    batch = store.create_batch(profile, "Avant ajout", before, .5)
    paths = []
    for i, color in enumerate(((100, 80, 60), (60, 80, 100), (100, 80, 60))):
        path = tmp_path / f"reference-{i}.png"
        Image.new("RGB", (32, 32), color).save(path)
        paths.append(str(path))

    class PauseAfterFirst:
        calls = 0

        def is_set(self):
            self.calls += 1
            return self.calls > 1

    identifier = reference_job(store, profile, paths)
    assert execute(store, identifier, PauseAfterFirst())["state"] == "paused"
    assert store.job(identifier)["cursor"] == 1
    assert len(store.references(profile)) == 1
    assert execute(store, identifier)["state"] == "done"
    assert execute(store, reference_job(store, profile, paths))["state"] == "done"
    assert len(store.references(profile)) == 2
    assert len(store.snapshot(profile, Encoder.version)["references"]) == 2
    assert store.batch(batch)["snapshot"] == before
    assert store.model(profile) == {"previous": True}
    assert not store.references(other)
    store.clear_feedback(profile)
    reopened = Store(store.root)
    try:
        assert len(reopened.references(profile)) == 2
    finally:
        reopened.close()


def test_bad_reference_is_reported_and_good_reference_is_kept(store, tmp_path):
    profile = store.create_profile("Photos lisibles")
    bad, good = tmp_path / "bad.jpg", tmp_path / "good.png"
    bad.write_text("not an image", encoding="utf-8")
    Image.new("RGB", (32, 32), "orange").save(good)
    job = execute(store, reference_job(store, profile, [str(bad), str(good)]))
    assert job["state"] == "done"
    assert [error["file"] for error in job["payload"]["errors"]] == [bad.name]
    assert len(store.references(profile)) == 1


@pytest.mark.parametrize("source", ["profil par défaut", "profil"])
def test_references_influence_compatible_selector_without_overriding_technical_rejects(source):
    stats = {"luma": .5, "spread": .2, "saturation": .2, "sharpness": .01,
             "peak": .02, "noise": .001, "black": 0., "white": 0., "rgb": [.5] * 3}
    dimension = len(TECH_KEYS) + 8 + 2
    weights = [0.] * dimension
    weights[-2] = 1.  # The selector initially favours the first embedding direction.
    selector = {"mu": [0.] * dimension, "sd": [1.] * dimension, "w": weights, "b": 0.,
                "feature_version": FEATURE_VERSION, "dimension": 2, "encoder": "test",
                "rate": .1, "source": source}
    snapshot = {"model": "test", "selector": selector, "look": None, "references": [], "feedback": []}
    rows = []
    for i, angle in enumerate(np.linspace(0., np.pi / 2, 12)):
        embedding = [float(np.cos(angle)), float(np.sin(angle))]
        data = propose(stats, embedding, snapshot)
        data.update(features=stats, embedding=embedding, time=i * 1000., digest=str(i))
        rows.append({"id": str(i), "path": str(i), "data": data})
    baseline = finalize(copy.deepcopy(rows), snapshot)
    snapshot["references"] = [{"features": stats, "embedding": [0., 1.]}]
    for row in rows:
        row["data"].update(propose(stats, row["data"]["embedding"], snapshot))
    # The closest photo is unusable and must stay rejected despite the reference.
    rows[-1]["data"].update(proposed="reject", decision="reject", blocked=True)
    result = finalize(rows, snapshot)
    assert result[-1]["data"]["decision"] == "reject"
    before = {row["id"] for row in baseline if row["data"]["decision"] == "keep"}
    after = {row["id"] for row in result if row["data"]["decision"] == "keep"}
    assert before != after
    assert sum(int(i) for i in after) > sum(int(i) for i in before)


def learned_look():
    grid = np.stack(np.meshgrid(*[[0., 1.]] * 3, indexing="ij"), -1).reshape(-1, 3)
    coef = np.zeros((16, 9))
    coef[0] = .1
    return {"lut_size": 2, "lut": grid.tolist(),
            "tone": {"mu": [0.] * 15, "sd": [1.] * 15, "coef": coef.tolist()}}


@pytest.mark.parametrize("with_look", [False, True])
def test_references_change_render_and_preserve_learned_look(with_look):
    pixels = np.random.default_rng(4).uniform(.1, .4, (32, 48, 3)).astype(np.float32)
    stats = features(pixels)
    snapshot = {"references": [], "feedback": [], "look": learned_look() if with_look else None}
    baseline = propose(stats, [1., 0.], snapshot, small=pixels)
    target = dict(stats, luma=.6, spread=.4, saturation=.7, rgb=[.7, .5, .3])
    snapshot["references"] = [{"embedding": [1., 0.], "features": target}]
    result = propose(stats, [1., 0.], snapshot, small=pixels)
    assert all(result["style"][key] > 0 for key in ("exposure", "temperature", "contrast", "saturation"))
    if with_look:
        assert result["style"]["knots"] == baseline["style"]["knots"]
    original = render(pixels, baseline["recipe"], baseline["style"], snapshot["look"])
    changed = render(pixels, result["recipe"], result["style"], snapshot["look"])
    assert not np.array_equal(original, changed)


def test_references_already_matching_learned_render_do_not_double_correction():
    pixels = np.full((32, 48, 3), .25, dtype=np.float32)
    snapshot = {"references": [], "feedback": [], "look": learned_look()}
    stats = features(pixels)
    initial = propose(stats, [1., 0.], snapshot, small=pixels)
    target = color_features(render(pixels, LEARNED_NEUTRAL, initial["style"], snapshot["look"]))
    snapshot["references"] = [{"embedding": [1., 0.], "features": target}]
    result = propose(stats, [1., 0.], snapshot, small=pixels)
    for key in ("exposure", "temperature", "contrast", "saturation"):
        assert result["style"][key] == pytest.approx(0., abs=1e-6)
    assert result["style"]["knots"] == initial["style"]["knots"]


def test_reference_button_creates_job_and_help_explains_unpaired_photos(qapp, store, tmp_path, monkeypatch):
    profile = store.create_profile("Interface")
    path = tmp_path / "reference.png"
    Image.new("RGB", (32, 32), "orange").save(path)
    launched = []
    monkeypatch.setattr(Window, "launch", lambda self, identifier: launched.append(identifier))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: ([str(path)], ""))

    def choose_references(dialog):
        assert "sans leur rush associé" in dialog.add_references.toolTip()
        dialog.add_references.click()
        assert dialog.list.count() == 1
        assert "Références" in dialog.list.item(0).text()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TrainingDialog, "exec", choose_references)
    window = Window(store.root)
    try:
        assert not hasattr(window, "references_button")
        window.learn_button.click()
        assert len(launched) == 1
        job = store.job(launched[0])
        assert job["kind"] == "training" and job["profile"] == profile
        assert job["payload"]["reference_catalog"][0]["paths"] == [str(path)]
        assert execute(store, launched[0])["state"] == "done"
        window.refresh_profile_info()
        assert "1 référence(s)" in window.profile_info.text()
        monkeypatch.setattr(TrainingDialog, "exec", lambda *args: QDialog.DialogCode.Rejected)
        window.learn_button.click()
        assert len(launched) == 1

        def inspect_help(dialog):
            text = dialog.findChild(QTextBrowser).toPlainText()
            assert "sans leur rush associé" in text
            assert "Ajouter des références" in text
            assert "Les lots déjà importés gardent leurs propositions" in text
            assert "poids DINOv3" not in text
            assert dialog.findChild(QTextBrowser).document().blockCount() > 20
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(QDialog, "exec", inspect_help)
        window.show_help()
    finally:
        window.close()


def reference_group(tmp_path, name, color="orange"):
    folder = tmp_path / name
    folder.mkdir()
    path = folder / "photo.png"
    Image.new("RGB", (32, 32), color).save(path)
    return {"name": name, "paths": [str(path)], "enabled": True}


def test_reference_groups_toggle_persist_and_reuse_cache_without_sources(store, tmp_path):
    profile = store.create_profile("Groupes")
    groups = [reference_group(tmp_path, "A"), reference_group(tmp_path, "B", "blue")]
    assert execute(store, training_update_job(store, profile, [], groups))["state"] == "done"
    before = store.snapshot(profile, Encoder.version)
    batch = store.create_batch(profile, "Avant désactivation", before, .5)
    saved = store.reference_groups(profile)
    assert len(saved) == 2 and all(g["enabled"] and g["ready"] and g["count"] == 1 for g in saved)
    saved[0]["enabled"] = False
    assert execute(store, training_update_job(store, profile, [], saved))["state"] == "done"
    assert len(store.snapshot(profile, Encoder.version)["references"]) == 1
    assert store.batch(batch)["snapshot"] == before
    assert len(store.references(profile)) == 2
    for group in groups:
        Path(group["paths"][0]).unlink()
    saved = store.reference_groups(profile)
    saved[0]["enabled"] = True
    identifier = training_update_job(store, profile, [], saved)
    assert not store.job(identifier)["payload"]["items"]

    def no_encoder():
        raise AssertionError("Cached groups must not need image analysis")

    run_job(store.root, identifier, queue.SimpleQueue(), threading.Event(), no_encoder)
    assert store.job(identifier)["state"] == "done"
    reopened = Store(store.root)
    try:
        assert len(reopened.snapshot(profile, Encoder.version)["references"]) == 2
        assert all(g["enabled"] for g in reopened.reference_groups(profile))
    finally:
        reopened.close()


def test_same_reference_in_two_groups_is_active_once_and_survives_removing_one(store, tmp_path):
    profile = store.create_profile("Partage")
    groups = [reference_group(tmp_path, "A"), reference_group(tmp_path, "B")]
    assert execute(store, training_update_job(store, profile, [], groups))["state"] == "done"
    assert len(store.references(profile)) == 1
    assert len(store.snapshot(profile, Encoder.version)["references"]) == 1
    saved = store.reference_groups(profile)
    saved[0]["enabled"] = False
    assert execute(store, training_update_job(store, profile, [], saved))["state"] == "done"
    assert len(store.snapshot(profile, Encoder.version)["references"]) == 1
    assert execute(store, training_update_job(store, profile, [], saved[1:]))["state"] == "done"
    assert len(store.reference_groups(profile)) == len(store.references(profile)) == 1
    proxy = store.private_dir(profile, "references") / f"{store.references(profile)[0]['id']}.png"
    assert proxy.exists()
    assert execute(store, training_update_job(store, profile, [], []))["state"] == "done"
    assert not store.reference_groups(profile) and not store.references(profile)
    assert not proxy.exists()


def test_reference_group_failure_does_not_publish_checkbox_changes(store, tmp_path):
    profile = store.create_profile("Échec")
    good = reference_group(tmp_path, "Bon")
    assert execute(store, training_update_job(store, profile, [], [good]))["state"] == "done"
    before = store.snapshot(profile, Encoder.version)
    saved = store.reference_groups(profile)
    saved[0]["enabled"] = False
    bad = tmp_path / "bad.jpg"
    bad.write_text("broken", encoding="utf-8")
    another = reference_group(tmp_path, "Nouveau", "blue")
    identifier = training_update_job(store, profile, [], saved + [{"name": "Mauvais", "paths": [*another["paths"], str(bad)]}])
    assert execute(store, identifier)["state"] == "failed"
    assert store.snapshot(profile, Encoder.version) == before
    assert store.reference_groups(profile)[0]["enabled"]
    assert not store.reference_groups(profile)[1]["enabled"]


def test_migration_preserves_old_references_as_a_toggleable_group(store, tmp_path):
    profile = store.create_profile("Anciennes références")
    group = reference_group(tmp_path, "Ancien")
    assert execute(store, reference_job(store, profile, group["paths"]))["state"] == "done"
    before = store.snapshot(profile, Encoder.version)
    with store.db:
        store.db.execute("DROP TABLE reference_members")
        store.db.execute("DROP TABLE reference_groups")
        store.db.execute("PRAGMA user_version=5")
    migrated = Store(store.root)
    try:
        groups = migrated.reference_groups(profile)
        assert len(groups) == 1 and groups[0]["count"] == 1
        assert groups[0]["enabled"] and groups[0]["ready"]
        assert migrated.snapshot(profile, Encoder.version) == before
        groups[0]["enabled"] = False
        assert execute(migrated, training_update_job(migrated, profile, [], groups))["state"] == "done"
        assert not migrated.snapshot(profile, Encoder.version)["references"]
        groups = migrated.reference_groups(profile)
        groups[0]["enabled"] = True
        assert execute(migrated, training_update_job(migrated, profile, [], groups))["state"] == "done"
        assert migrated.snapshot(profile, Encoder.version)["references"] == before["references"]
    finally:
        migrated.close()


def test_dialog_reference_group_is_one_checkbox_and_cancel_keeps_original(qapp, tmp_path, monkeypatch):
    group = reference_group(tmp_path, "Exemples")
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: (group["paths"], ""))
    dialog = TrainingDialog()
    try:
        dialog.add_references.click()
        assert dialog.list.count() == 1 and not dialog.reportages()
        assert dialog.reference_groups()[0]["enabled"]
        dialog.list.item(0).setCheckState(Qt.CheckState.Unchecked)
        assert not dialog.reference_groups()[0]["enabled"]
        assert "0 / 1 groupe(s)" in dialog.summary.text()
        assert dialog.start.isEnabled()  # Can save a new unchecked group for later.
        dialog.reject()
        assert group["enabled"]
    finally:
        dialog.close()


def test_reference_group_pause_keeps_partial_examples_inactive_until_completion(store, tmp_path):
    profile = store.create_profile("Reprise")
    first = reference_group(tmp_path, "A")
    second = reference_group(tmp_path, "B", "blue")
    group = {"name": "Deux exemples", "paths": first["paths"] + second["paths"]}

    class PauseAfterFirst:
        calls = 0

        def is_set(self):
            self.calls += 1
            return self.calls > 1

    identifier = training_update_job(store, profile, [], [group])
    assert execute(store, identifier, PauseAfterFirst())["state"] == "paused"
    assert len(store.references(profile)) == 1
    assert not store.snapshot(profile, Encoder.version)["references"]
    assert not store.reference_groups(profile)[0]["enabled"]
    assert execute(store, identifier)["state"] == "done"
    assert len(store.snapshot(profile, Encoder.version)["references"]) == 2


def test_reference_group_publication_rolls_back_with_failed_task_completion(store, tmp_path):
    profile = store.create_profile("Transaction")
    first = reference_group(tmp_path, "A")
    assert execute(store, training_update_job(store, profile, [], [first]))["state"] == "done"
    before = store.snapshot(profile, Encoder.version)
    saved = store.reference_groups(profile)
    saved[0]["enabled"] = False
    second = reference_group(tmp_path, "B", "blue")
    identifier = training_update_job(store, profile, [], saved + [second])
    with store.db:
        store.db.execute("CREATE TRIGGER block_completion BEFORE UPDATE OF state ON jobs "
                         "WHEN NEW.state='done' BEGIN SELECT RAISE(ABORT, 'interrupted'); END")
    assert execute(store, identifier)["state"] == "failed"
    assert store.snapshot(profile, Encoder.version) == before
    assert store.reference_groups(profile)[0]["enabled"]
    assert not store.reference_groups(profile)[1]["enabled"]
