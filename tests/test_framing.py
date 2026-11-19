from pathlib import Path
from time import monotonic
from unittest.mock import Mock

import pytest
from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox

from atelier.app import Window
from atelier.crop_dialog import FULL, CropDialog
from atelier.imaging import (
    IDENTITY_RECIPE,
    IDENTITY_STYLE,
    active_crop,
    crop_box,
    digest,
)
from atelier.pipeline import export_job, export_one
from atelier.workspace_ui import PhotoViewer
from atelier.xmp import raw_crop, sidecar


def make_batch(store, tmp_path):
    profile = store.create_profile("Portraits")
    batch = store.create_batch(profile, "Séance", {"model": "test"}, .5)
    directory = store.private_dir(profile, "batches", batch)
    for i, decision in enumerate(("keep", "review", "reject")):
        source = tmp_path / f"{i}.png"
        photo = Image.linear_gradient("L").resize((180, 120)).convert("RGB")
        photo.save(source)
        photo.resize((90, 60)).save(directory / source.name)
        photo.resize((45, 30)).save(directory / f"{i}.jpg")
        store.save_photo(str(i), batch, source, {
            "decision": decision, "proposed": decision, "validated": True, "group": "1" if i else None,
            "recipe": IDENTITY_RECIPE, "style": IDENTITY_STYLE,
            "initial_recipe": IDENTITY_RECIPE, "digest": digest(source)})
    return profile, batch


def test_variant_picker_from_unrelated_filtered_photo_and_batch_removal(qapp, store, tmp_path, monkeypatch):
    profile, batch = make_batch(store, tmp_path)
    monkeypatch.setattr(Window, "request_preview", lambda *_: None)
    window = Window(store.root)
    try:
        window.filter.setCurrentIndex(1)
        assert not window.variants_button.isEnabled() and window.group_picker.isEnabled()
        window.group_picker.activated.emit(1)
        assert [r["id"] for r in window.model.rows] == ["1", "2"]
        window.move_photo(1)
        window.prefer_button.click()
        assert [r["data"]["decision"] for r in store.photos(batch)] == ["keep", "reject", "keep"]
        window.all_button.click()
        assert window.filter.currentIndex() == 0 and window.current_photo["id"] == "0"
        assert window.model.rowCount() == 3 and window.group_picker.currentIndex() == 0
        window.move_photo(1)
        window.variants_button.click()
        assert [r["id"] for r in window.model.rows] == ["1", "2"]
        window.all_button.click()
        assert [r["id"] for r in window.model.rows] == ["0", "1", "2"]
        window.variants_button.click()
        window.batches.itemClicked.emit(window.batches.currentItem())
        assert window.group_filter is None and window.model.rowCount() == 3
        for answer in (QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes):
            monkeypatch.setattr(QMessageBox, "question", lambda *args, answer=answer: answer)
            window.delete_batch_button.click()
            assert bool(store.batches(profile)) == (answer == QMessageBox.StandardButton.No)
        assert (tmp_path / "1.png").is_file() and not window.delete_batch_button.isEnabled()
    finally:
        window.close()



def test_crop_gestures_persist_and_export_snapshot(qapp, store, tmp_path, monkeypatch):
    _, batch = make_batch(store, tmp_path)
    monkeypatch.setattr(Window, "request_preview", lambda *_: None)
    window = Window(store.root)
    def edit(dialog):
        dialog.show()
        qapp.processEvents()
        canvas = dialog.canvas
        rect = canvas.image_rect()
        def point(x, y):
            return QPointF(rect.left() + x * rect.width(), rect.top() + y * rect.height()).toPoint()
        def drag(start, end):
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(canvas, end)
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
        drag(point(.25, .25), point(.75, .75))
        assert canvas.crop == pytest.approx((.25, .25, .75, .75), abs=.005)
        drag(point(.5, .5), point(.6, .5))
        drag(canvas.frame().topRight().toPoint(), point(.9, .2))
        assert canvas.crop == pytest.approx((.35, .2, .9, .75), abs=.005)
        dialog.undo.click()
        dialog.undo.click()
        for guide in ("Grille 4 × 4", "Nombre d’or", "Spirale d’or"):
            canvas.set_guide(guide)
            assert not canvas.guide_path(canvas.frame()).isEmpty()
            assert not canvas.grab().isNull()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(CropDialog, "exec", edit)
    try:
        window.crop_button.click()
        row = store.photos(batch)[0]
        assert row["data"]["crop_history"] == [list(FULL)]
        assert not row["data"]["validated"] and "crop" not in store.photos(batch)[1]["data"]
        window.store.validate(batch)
        job = store.job(export_job(store, batch, tmp_path / "exports", "PNG"))
        item = job["payload"]["items"][0]
        source = Path(item["path"])
        with Image.open(source) as image:
            expected = image.crop(crop_box(image.size, row["data"]["crop"]))
        for enabled in (True, False):
            with Image.open(export_one(item, tmp_path / "exports", "PNG", enabled)) as output:
                assert output.size == expected.size and output.tobytes() == expected.tobytes()
        assert Path(export_one(item, tmp_path / "exports", "SOURCE")).read_bytes() == source.read_bytes()
        for result in (QDialog.DialogCode.Rejected, QDialog.DialogCode.Accepted):
            def undo(dialog, result=result):
                assert dialog.undo.isEnabled()
                dialog.undo.click()
                assert dialog.canvas.crop == FULL
                return result
            monkeypatch.setattr(CropDialog, "exec", undo)
            window.crop_button.click()
            assert bool(store.photos(batch)[0]["data"]["crop"]) == (result == QDialog.DialogCode.Rejected)
        assert item["data"]["crop"] and digest(source) == item["data"]["digest"]
    finally:
        window.close()


@pytest.mark.parametrize("kind", ["analysis", "training", "selection", "export"])
def test_import_notice_lifetime(qapp, store, tmp_path, monkeypatch, kind):
    profile, batch = make_batch(store, tmp_path)
    job = store.new_job(profile, kind, {"batch": batch, "items": []})
    monkeypatch.setattr(Window, "request_preview", lambda *_: None)
    window = Window(store.root)
    monkeypatch.setattr(window.context, "Process", Mock())
    try:
        window.launch(job)
        if kind == "export":
            assert "Export en cours" in window.import_notice.text()
            assert "en bas de la fenêtre" in window.import_notice.text()
        assert window.import_notice.isHidden() == (kind == "selection")
        assert window.notice_timer.isActive() == (kind != "selection")
        assert window.notice_timer.interval() == 10000
        window.notice_timer.timeout.emit()
        assert window.import_notice.isHidden()
    finally:
        window.process = None
        window.events.close()
        window.close()


def test_raw_portrait_crop_is_recorded_in_sensor_coordinates():
    crop = raw_crop((.1, .2, .8, .9), 6)
    assert crop == pytest.approx((.2, .2, .9, .9))
    xml = sidecar(IDENTITY_RECIPE, IDENTITY_STYLE, False, crop=crop)
    assert b'crs:HasCrop="True"' in xml and b'crs:CropBottom="0.90000000"' in xml
    assert b"crs:HasCrop" not in sidecar(IDENTITY_RECIPE, IDENTITY_STYLE)


def test_suspend_crops_in_gallery_viewer_and_batch(qapp, store, tmp_path, monkeypatch):
    profile, batch = make_batch(store, tmp_path)
    crop = [.25, .25, .75, .75]
    rows = store.photos(batch)
    for row in rows[:2]:
        row["data"].update(crop=crop, initial_crop=crop, crop_history=[list(FULL)],
                           embedding=[1., 0.], features={"aspect": 1.5})
    store.save_photos(rows)
    monkeypatch.setattr(Window, "request_preview", lambda *_: None)
    window = Window(store.root)
    def output_item():
        store.validate(batch)
        job = export_job(store, batch, tmp_path / "export", "PNG")
        return store.job(job)["payload"]["items"][0]
    def thumbnail_width():
        return window.model.data(window.model.index(0), Qt.ItemDataRole.DecorationRole).availableSizes()[0].width()
    try:
        cropped = output_item()
        assert cropped["data"]["crop"] == crop and thumbnail_width() < 45
        window.filter.setCurrentIndex(1)  # Only the retained photo is visible.
        window.batch_crop_button.click()
        uncropped = output_item()
        assert uncropped["data"]["crop"] is None and thumbnail_width() == 45
        assert store.learning_count(profile) == 0
        with Image.open(export_one(uncropped, tmp_path, "PNG")) as image:
            assert image.size == (180, 120)
        with Image.open(export_one(cropped, tmp_path, "PNG")) as image:
            assert image.size == (90, 60)
    finally:
        window.close()
    window = Window(store.root)
    try:
        assert not window.model.crops_enabled and store.photos(batch)[0]["data"]["crop_history"] == [list(FULL)]
        def reapply(dialog):
            assert dialog.toggle_crop.text() == "Réappliquer le recadrage"
            dialog.toggle_crop.click()
            assert dialog.toggle_crop.text() == "Retirer le recadrage"
            return QDialog.DialogCode.Accepted
        monkeypatch.setattr(PhotoViewer, "exec", reapply)
        window.large_button.click()
        assert output_item()["data"]["crop"] == crop
        assert active_crop(store.photos(batch)[1]["data"], False) is None
        window.batch_crop_button.click()
        window.photo_crop_button.click()
        assert output_item()["data"]["crop"] is None and store.learning_count(profile) == 1
        window.batch_crop_button.click()
        window.batch_crop_button.click()
        assert output_item()["data"]["crop"] is None and thumbnail_width() == 45
        assert active_crop(store.photos(batch)[1]["data"]) == crop
        window.photo_crop_button.click()
        assert output_item()["data"]["crop"] == crop and store.learning_count(profile) == 0
        assert window.filter_enabled()
    finally:
        window.close()


def test_manual_retouch_and_crop_from_large_view_after_batch_reset(qapp, store, tmp_path, monkeypatch):
    _, batch = make_batch(store, tmp_path)
    rows = store.photos(batch)
    for row in rows:
        recipe = dict(IDENTITY_RECIPE, exposure=-.5)
        row["data"].update(embedding=[1., 0.], recipe=recipe, initial_recipe=recipe)
    store.save_photos(rows)
    window = Window(store.root)

    def check_crop(dialog):
        assert dialog.parent() == window.viewer and dialog.isMaximized()
        dialog.canvas.crop = (.25, .25, .75, .75)
        return QDialog.DialogCode.Accepted

    def edit(dialog):
        assert dialog.isMaximized()
        dialog.show()
        dialog.retouch.click()
        assert window.editor_panel.isVisible() and window.sliders["exposure"].value() == 0
        window.sliders["exposure"].setValue(100)
        dialog.crop.click()
        deadline = monotonic() + 10
        while dialog.source is None or dialog.source.width() != 46:
            assert monotonic() < deadline, "L’aperçu recadré n’est pas arrivé"
            QTest.qWait(30)
        assert dialog.source.toImage().pixelColor(20, 15).red() > 220
        dialog.next_photo.click()
        assert window.sliders["exposure"].value() == 0
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(CropDialog, "exec", check_crop)
    monkeypatch.setattr(PhotoViewer, "exec", edit)
    try:
        window.show()
        window.options_dialog.show()
        assert window.filter_button.isVisible()
        window.filter_button.click()
        window.options_dialog.close()
        window.large_button.click()
        assert window.current_photo["id"] == "1"
        window.move_photo(-1)
        window.filter_button.click()
        assert window.sliders["exposure"].value() == -50
        window.filter_button.click()
        assert window.sliders["exposure"].value() == 100
        store.validate(batch)
        payload = store.job(export_job(store, batch, tmp_path / "exports", "PNG"))["payload"]
        assert not payload["filter"]
        item = payload["items"][0]
        with Image.open(export_one(item, tmp_path / "exports", "PNG", payload["filter"])) as exported:
            assert exported.size == (90, 60)
            assert exported.getpixel((40, 30))[0] > 220
        assert "manual_recipe" not in store.photos(batch)[1]["data"]
    finally:
        window.close()

    window = Window(store.root)
    try:
        assert not window.filter_enabled()
        assert window.sliders["exposure"].value() == 100
        assert window.current_photo["data"]["crop"] == [.25, .25, .75, .75]

        def reopened(dialog):
            assert dialog.isMaximized() and dialog.retouch.isChecked()
            window.neutral_button.click()
            assert window.sliders["exposure"].value() == 0
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(PhotoViewer, "exec", reopened)
        window.retouch_button.click()
        assert store.photos(batch)[0]["data"]["manual_recipe"] == IDENTITY_RECIPE
    finally:
        window.close()

