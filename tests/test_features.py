import os
import queue
import sqlite3
import threading

import numpy as np
import pytest
from PIL import Image, ImageFilter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from atelier.analysis import finalize, propose
from atelier.imaging import IDENTITY_RECIPE, IDENTITY_STYLE, digest, features, render
from atelier.pipeline import (
    analysis_job,
    export_job,
    export_one,
    reference_job,
    run_job,
)
from atelier.store import Store
from atelier.xmp import sidecar


def execute(store, job, encoder):
    run_job(store.root, job, queue.Queue(), threading.Event(), encoder)
    return store.job(job)


def prepared(store, photos, encoder):
    profile = store.create_profile("Profil")
    execute(store, reference_job(store, profile, photos[:2]), encoder)
    job = execute(store, analysis_job(store, profile, photos), encoder)
    return profile, job["payload"]["batch"]


def scene():
    image = Image.new("RGB", (400, 300), (40, 60, 90))
    pixels = np.asarray(image).copy()
    pixels[60:240, 80:200] = (220, 200, 160)
    pixels[100:180, 250:360] = (20, 20, 20)
    return Image.fromarray(pixels)


def test_whole_frame_blur_is_rejected_unless_user_kept_similar():
    sharp = features(np.asarray(scene(), dtype=np.float32) / 255)
    blurred = features(np.asarray(scene().filter(ImageFilter.GaussianBlur(12)), dtype=np.float32) / 255)
    reference = {"embedding": [1., 0.], "features": sharp}
    snapshot = {"references": [reference], "feedback": []}
    assert propose(sharp, [1., 0.], snapshot)["decision"] != "reject"
    assert propose(blurred, [1., 0.], snapshot)["decision"] == "reject"
    snapshot["feedback"] = [{"embedding": [1., 0.], "decision": "keep", "delta": {}}]
    result = propose(blurred, [1., 0.], snapshot)
    assert result["decision"] == "review"
    assert "retenu" in " ".join(result["reasons"])


def test_scene_selection_groups_bursts_and_rejects_exact_copies():
    def row(identifier, embedding, time, digest_value, sharpness):
        stats = {"luma": .5, "spread": .5, "saturation": .3, "sharpness": sharpness, "peak": sharpness * 2,
                 "noise": .01, "black": 0., "white": 0., "aspect": 1.5}
        return {"id": identifier, "path": f"{identifier}.jpg", "data": {
            "embedding": embedding, "digest": digest_value, "time": time, "features": stats, "similarity": 0.,
            "preference": 0., "blocked": False, "proposed": "keep", "decision": "keep", "reasons": [], "group": None}}
    rows = [row("a", [1., 0.], 0., "x", .01), row("b", [1., 0.], 1., "y", .02),
            row("c", [0., 1.], 300., "z", .01), row("d", [1., 0.], 2., "x", .01)]
    finalize(rows, {"model": "test", "selector": None}, .5)
    data = {r["id"]: r["data"] for r in rows}
    assert data["a"]["group"] == data["b"]["group"] == data["d"]["group"] == "b"  # sharpest frame leads
    assert data["c"]["group"] is None
    assert data["d"]["decision"] == "reject" and "Doublon" in data["d"]["reasons"][0]
    assert data["b"]["decision"] == "keep"


def test_raw_export_copies_original_with_xmp_sidecar(tmp_path):
    source = tmp_path / "IMG_0001.NEF"
    source.write_bytes(os.urandom(4096))
    recipe = dict(IDENTITY_RECIPE, intensity=1., exposure=.5)
    style = dict(IDENTITY_STYLE, contrast=.1, saturation=.2)
    row = {"path": str(source), "data": {"digest": digest(source), "recipe": recipe, "style": style}}
    first = export_one(row, tmp_path / "out", "RAW")
    second = export_one(row, tmp_path / "out", "RAW")
    assert first.endswith("IMG_0001_Atelier_001.NEF") and second.endswith("_002.NEF")
    assert digest(first) == digest(source)
    xmp = (tmp_path / "out" / "IMG_0001_Atelier_001.xmp").read_text(encoding="utf-8")
    assert 'crs:Exposure2012="+0.50"' in xmp
    assert 'crs:Contrast2012="+20"' in xmp
    assert 'crs:Saturation="+20"' in xmp
    assert 'atelier:FilterEnabled="True"' in xmp
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "IMG_0001_Atelier_001.NEF", "IMG_0001_Atelier_001.xmp",
        "IMG_0001_Atelier_002.NEF", "IMG_0001_Atelier_002.xmp"]


def test_disabled_filter_sidecar_is_neutral():
    xmp = sidecar(dict(IDENTITY_RECIPE, intensity=1., exposure=1.), IDENTITY_STYLE, enabled=False).decode()
    assert 'crs:Exposure2012="+0.00"' in xmp and 'atelier:FilterEnabled="False"' in xmp


def test_raw_format_renders_non_raw_sources_as_jpeg(store, photos, encoder, tmp_path):
    _, batch = prepared(store, photos, encoder)
    rows = store.photos(batch)
    for row in rows:
        row["data"]["decision"] = "keep"
    store.save_photos(rows)
    store.validate(batch)
    job = execute(store, export_job(store, batch, tmp_path / "raw", "RAW"), encoder)
    assert job["state"] == "done", job["error"]
    assert all(p.endswith(".jpg") for p in job["payload"]["outputs"])


def test_filter_toggle_exports_original_pixels(store, photos, encoder, tmp_path):
    _, batch = prepared(store, photos, encoder)
    rows = store.photos(batch)
    for row in rows:
        row["data"]["decision"] = "keep"
        row["data"]["recipe"]["exposure"] = 1.
    store.save_photos(rows)
    store.validate(batch)
    store.set_filter(batch, False)
    assert store.batch(batch)["filter_enabled"] is False
    job = execute(store, export_job(store, batch, tmp_path / "plain", "PNG"), encoder)
    with Image.open(job["payload"]["outputs"][0]) as exported, Image.open(photos[0]) as original:
        np.testing.assert_array_equal(np.asarray(exported.convert("RGB")), np.asarray(original.convert("RGB")))
    store.set_filter(batch, True)
    job = execute(store, export_job(store, batch, tmp_path / "styled", "PNG"), encoder)
    with Image.open(job["payload"]["outputs"][0]) as exported, Image.open(photos[0]) as original:
        assert not np.array_equal(np.asarray(exported.convert("RGB")), np.asarray(original.convert("RGB")))


def test_identity_render_is_lossless():
    pixels = np.random.default_rng(3).integers(0, 256, (20, 30, 3)).astype(np.float32) / 255
    np.testing.assert_array_equal(np.asarray(render(pixels, IDENTITY_RECIPE, IDENTITY_STYLE)),
                                  np.round(pixels * 255).astype(np.uint8))


def test_v2_library_migrates_filter_column(tmp_path):
    Store(tmp_path / "lib").close()
    db = sqlite3.connect(tmp_path / "lib" / "library.sqlite3")
    db.execute("ALTER TABLE batches DROP COLUMN filter_enabled")
    db.execute("PRAGMA user_version=2")
    db.commit()
    db.close()
    store = Store(tmp_path / "lib")
    profile = store.create_profile("Ancien")
    assert store.batch(store.create_batch(profile, "Lot", {}, .5))["filter_enabled"] is True
    store.close()


def double_click(widget):
    point = QPointF(widget.width() / 2, widget.height() / 2)
    event = QMouseEvent(QEvent.Type.MouseButtonDblClick, point, widget.mapToGlobal(point),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)


def test_ui_double_click_reset_and_filter_toggle(tmp_path, photos, encoder):
    from atelier.app import Window
    app = QApplication.instance() or QApplication([])
    window = Window(tmp_path / "ui")
    profile, batch = prepared(window.store, photos, encoder)
    window.reload_profiles(profile)
    assert window.current_batch == batch
    window.gallery.selectAll()
    initial = window.current_photo["data"]["initial_recipe"]["exposure"]
    window.sliders["exposure"].setValue(150)
    assert all(r["data"]["recipe"]["exposure"] == pytest.approx(1.5) for r in window.store.photos(batch))
    double_click(window.sliders["exposure"])
    assert window.sliders["exposure"].value() == round(initial * 100)
    assert all(r["data"]["recipe"]["exposure"] == pytest.approx(r["data"]["initial_recipe"]["exposure"])
               for r in window.store.photos(batch))
    window.selectivity.setValue(90)
    double_click(window.selectivity)
    assert window.selectivity.value() == 50
    window.filter_button.click()
    assert window.store.batch(batch)["filter_enabled"] is False
    assert window.filter_button.text() == "Réappliquer le filtre sur tout le lot"
    assert not window.sliders["exposure"].isEnabled()
    window.filter_button.click()
    assert window.store.batch(batch)["filter_enabled"] is True
    assert window.sliders["exposure"].isEnabled()
    window.close()
    app.processEvents()
