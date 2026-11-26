import copy
import queue
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QTextBrowser

from atelier.analysis import finalize, propose
from atelier.app import Window
from atelier.imaging import digest
from atelier.pipeline import run_job, training_update_job
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

    identifier = training_update_job(store, profile, [], [{"name": "Exemples", "paths": paths}])
    assert execute(store, identifier, PauseAfterFirst())["state"] == "paused"
    assert store.job(identifier)["cursor"] == 1
    assert len(store.references(profile)) == 1
    assert execute(store, identifier)["state"] == "done"
    groups = store.reference_groups(profile)
    assert execute(store, training_update_job(store, profile, [], groups))["state"] == "done"
    # The third file duplicates the first one: two distinct references.
    assert len(store.references(profile)) == 2
    assert len(store.snapshot(profile, Encoder.version)["references"]) == 2
    assert store.batch(batch)["snapshot"] == before
    assert not store.references(other)
    store.clear_feedback(profile)
    reopened = Store(store.root)
    try:
        assert len(reopened.references(profile)) == 2
    finally:
        reopened.close()




@pytest.mark.parametrize("source", ["profil par défaut", "profil"])
def test_references_influence_compatible_selector_without_overriding_technical_rejects(source):
    stats = {"luma": .5, "spread": .2, "saturation": .2, "sharpness": .01,
             "peak": .02, "noise": .001, "black": 0., "white": 0.}
    dimension = len(TECH_KEYS) + 8 + 2
    weights = [0.] * dimension
    weights[-2] = 1.  # The selector initially favours the first embedding direction.
    selector = {"mu": [0.] * dimension, "sd": [1.] * dimension, "w": weights, "b": 0.,
                "feature_version": FEATURE_VERSION, "dimension": 2, "encoder": "test",
                "rate": .1, "source": source}
    snapshot = {"model": "test", "selector": selector, "references": [], "feedback": []}
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


STATS = {"luma": .5, "spread": .2, "saturation": .2, "sharpness": .01,
         "peak": .02, "noise": .001, "black": 0., "white": 0.}


def burst(snapshot, embeddings):
    """One scene: frames one second apart, technically identical."""
    rows = []
    for i, embedding in enumerate(embeddings):
        data = propose(STATS, embedding, snapshot)
        data.update(features=STATS, embedding=embedding, time=1000. + i, digest=str(i))
        rows.append({"id": str(i), "path": f"{i}.jpg", "data": data})
    return finalize(rows, snapshot)


def test_references_choose_the_variant_kept_in_a_scene():
    # Three close variants of the same moment, which the selection model cannot separate.
    embeddings = [[float(np.cos(a)), float(np.sin(a))] for a in (0., .12, .24)]
    dimension = len(TECH_KEYS) + 8 + 2
    selector = {"mu": [0.] * dimension, "sd": [1.] * dimension, "w": [0.] * dimension, "b": 0.,
                "feature_version": FEATURE_VERSION, "dimension": 2, "encoder": "test", "rate": .1, "source": "profil"}
    snapshot = {"model": "test", "selector": selector, "references": [], "feedback": []}
    plain = burst(snapshot, embeddings)
    assert len({r["data"]["group"] for r in plain}) == 1 and plain[0]["data"]["group"]
    snapshot["references"] = [{"embedding": [float(np.cos(.6)), float(np.sin(.6))], "features": STATS}]
    guided = burst(snapshot, embeddings)
    kept = [r["id"] for r in guided if r["data"]["decision"] == "keep"]
    assert kept == ["2"]
    assert [r["id"] for r in plain if r["data"]["decision"] == "keep"] != kept
    assert guided[2]["data"]["reasons"][0].startswith("Meilleure image de la scène")
    assert any(reason.startswith("Proche de vos références") for reason in guided[2]["data"]["reasons"])


def test_photo_far_from_references_is_reviewed_without_learned_selector():
    snapshot = {"model": "test", "references": [{"embedding": [1., 0.], "features": STATS}], "feedback": []}
    close = propose(STATS, [1., 0.], snapshot)
    far = propose(STATS, [0., 1.], snapshot)
    assert close["proposed"] == "keep" and close["similarity"] == pytest.approx(1.)
    assert far["proposed"] == "review"
    assert "Éloignée des références : décision à confirmer" in far["reasons"]
    # Proposals carry only sorting data: nothing to render, crop or retouch.
    assert set(close) == {"proposed", "decision", "reasons", "similarity", "preference", "blocked", "validated", "group"}


def test_reference_ignores_its_sidecar(store, tmp_path):
    profile = store.create_profile("XMP")
    path = tmp_path / "ref.png"
    Image.new("RGB", (32, 32), "orange").save(path)
    path.with_suffix(".xmp").write_text("<x:xmpmeta crs:Exposure2012=\"+4\"/>", encoding="utf-8")
    assert execute(store, training_update_job(store, profile, [], [{"name": "R", "paths": [str(path)]}]))["state"] == "done"
    data = store.references(profile)[0]["data"]
    assert set(data) == {"features", "embedding", "model"}
    assert store.references(profile)[0]["digest"] == digest(path)


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
            advanced = dialog.findChild(QTextBrowser, "advancedHelp")
            text = advanced.toPlainText()
            assert "sans leur rush associé" in text
            assert "Ajouter des références" in text
            assert "Les lots déjà importés gardent leurs propositions" in text
            assert "poids DINOv3" not in text
            assert "à l’identique" in text and "JPEG" in text and "XMP" in text
            assert "Retouche par consigne" not in text and "Recadrer" not in text
            assert advanced.document().blockCount() > 20
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
