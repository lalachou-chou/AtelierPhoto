from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QFileDialog, QPushButton

from atelier.app import Window
from atelier.help_ui import STEPS, GuideDialog
from atelier.imaging import digest
from atelier.pipeline import export_one
from atelier.store import uid
from atelier.training_dialog import TrainingDialog
from atelier.workspace_ui import PALETTES, PhotoViewer, PrepareImport


def test_guide_navigation_and_profiles_handoff(qapp, store, monkeypatch):
    window = Window(store.root)
    dialog = GuideDialog(window)
    try:
        dialog.show()
        assert not dialog.previous.isEnabled()
        dialog.next.click()
        assert dialog.index == 1
        dialog.previous.click()
        assert dialog.index == 0
        dialog.steps[-1].click()
        assert dialog.index == len(STEPS) - 1
        dialog.next.click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        opened = []
        monkeypatch.setattr("atelier.help_ui.guide", lambda *_: True)
        monkeypatch.setattr(window, "open_profiles", lambda: opened.append(window.profile()))
        window.first_launch()
        window.first_launch()
        assert opened == [None]
        window.show_guide()
        assert opened == [None, None]
    finally:
        dialog.close()
        window.close()


def test_visible_profile_and_manager_share_examples_and_lots(qapp, store, monkeypatch):
    first, second = (store.create_profile(name) for name in ("Portraits", "Mariages"))
    first_batch = store.create_batch(first, "Portraits du matin", {}, .5)
    second_batch = store.create_batch(second, "Mariage du soir", {}, .5)
    with store.db:
        store.db.execute("INSERT INTO reference_groups VALUES('group',?,'Exemples','[]',1,1)", (second,))
    store.add_reference(second, uid(), "unique", "Exemple", {"embedding": [1., 0.]}, group="group", path="exemple.jpg")
    window = Window(store.root)
    try:
        window.show()
        window.profiles.setCurrentIndex(window.profiles.findData(first))
        assert window.current_batch == first_batch
        window.profile_picker.setCurrentIndex(window.profile_picker.findData(second))
        assert window.profile() == second and window.current_batch == second_batch
        assert "1 référence(s)" in window.profile_summary.text()
        assert window.profiles.isVisible() and window.learn_button.isVisible()

        def inspect(dialog):
            assert "Mariages" in dialog.windowTitle()
            assert dialog.list.count() == 1 and "Références" in dialog.list.item(0).text()
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(TrainingDialog, "exec", inspect)
        window.learn_button.click()
        window.reload_profiles(second)
        assert window.profile_picker.currentData() == second and window.current_batch == second_batch
        window.profiles.setCurrentIndex(window.profiles.findData(first))
        assert window.profile_picker.currentData() == first and window.current_batch == first_batch
        assert "0 référence(s)" in window.profile_summary.text()
    finally:
        window.close()
    reopened = Window(store.root)
    try:
        assert reopened.profile() == first and reopened.current_batch == first_batch
    finally:
        reopened.close()


def test_export_copies_file_and_sidecars_identically_without_overwriting(tmp_path):
    source = tmp_path / "ma retouche.jpg"
    Image.new("RGB", (16, 12), "orange").save(source, quality=78, comment=b"mon export")
    source.with_suffix(".xmp").write_bytes(b"mes reglages")
    Path(str(source) + ".xmp").write_bytes(b"autre developpement")
    destination = tmp_path / "exports"
    destination.mkdir()
    # Only the sidecar name is taken: the whole set moves to the next free name.
    collision = destination / "ma retouche.xmp"
    collision.write_bytes(b"existant")
    row = {"path": str(source), "data": {"digest": digest(source)}}
    target = Path(export_one(row, destination))
    assert target.name == "ma retouche (2).jpg"
    assert target.read_bytes() == source.read_bytes()
    assert target.with_suffix(".xmp").read_bytes() == b"mes reglages"
    assert Path(str(target) + ".xmp").read_bytes() == b"autre developpement"
    assert collision.read_bytes() == b"existant"
    assert not (destination / "ma retouche.jpg").exists()
    again = Path(export_one(row, destination))
    assert again.name == "ma retouche (3).jpg" and again.read_bytes() == source.read_bytes()
    source.write_bytes(b"modifie")
    with pytest.raises(ValueError, match="changé"):
        export_one(row, destination)


def test_export_keeps_original_name_when_free(tmp_path):
    source = tmp_path / "DSC0001.png"
    Image.new("RGB", (8, 8), "blue").save(source)
    target = Path(export_one({"path": str(source), "data": {"digest": digest(source)}}, tmp_path / "out"))
    assert target.name == "DSC0001.png" and digest(target) == digest(source)
    assert sorted(p.name for p in target.parent.iterdir()) == ["DSC0001.png"]


@pytest.mark.parametrize("cancel", [True, False])
def test_preparing_import_leaves_current_batch_and_uses_new_profile(qapp, store, tmp_path, monkeypatch, cancel):
    old, new = (store.create_profile(name) for name in ("Avant", "Nouveau"))
    batch = store.create_batch(old, "Premier", {}, .22)
    path = tmp_path / "p.png"
    Image.new("RGB", (12, 12)).save(path)
    launched = []

    def prepare(dialog):
        assert dialog.profiles.currentData() == old and dialog.slider.value() == 22
        dialog.profiles.setCurrentIndex(dialog.profiles.findData(new))
        dialog.slider.setValue(82)
        dialog.choose("files")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(PrepareImport, "exec", prepare)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *_: ([] if cancel else [str(path)], ""))
    window = Window(store.root)
    monkeypatch.setattr(window, "launch", launched.append)
    try:
        window.import_button.click()
        assert store.batch(batch)["selectivity"] == .22
        if cancel:
            assert not launched and window.profile() == old and window.current_batch == batch
        else:
            job = store.job(launched[0])
            assert job["profile"] == new and job["payload"]["selectivity"] == .82
    finally:
        window.close()


@pytest.mark.parametrize("theme", ["Nuit", "Nuit boréale", "Nuit ambrée"])
def test_panel_preferences_and_intro_survive_restart(qapp, store, monkeypatch, theme):
    seen = []
    monkeypatch.setattr("atelier.help_ui.guide", lambda *args: seen.append(True))
    window = Window(store.root)
    window.first_launch()
    def select_theme(dialog):
        buttons = {b.text(): b for b in dialog.findChildren(QPushButton) if b.isCheckable()}
        assert buttons.keys() == PALETTES.keys()
        buttons[theme].click()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", select_theme)
    window.appearance()
    for action in window.panel_actions:
        action.setChecked(False)
    assert not window.empty_panels.isHidden()
    window.close()
    window = Window(store.root)
    try:
        window.first_launch()
        assert seen == [True] and window.theme == theme
        assert all(p.isHidden() for p in window.panes)
        window.reset_panels()
        assert all(not p.isHidden() for p in window.panes)
    finally:
        window.close()


def test_viewer_navigation_and_decisions(qapp, store, monkeypatch):
    profile = store.create_profile("A")
    batch = store.create_batch(profile, "Vue", {}, .5)
    for i in range(3):
        store.save_photo(uid(), batch, f"{i}.png", {"decision": "keep", "reasons": []})
    window = Window(store.root)
    try:
        window.show()
        qapp.processEvents()
        window.pixmap = QPixmap(300, 200)
        window.scale_preview()
        first = window.current_photo["id"]

        def inspect(dialog):
            assert dialog.source is not None
            dialog.zoom.setChecked(True)
            assert dialog.photo.width() > dialog.area.maximumViewportSize().width() or (
                dialog.photo.height() > dialog.area.maximumViewportSize().height())
            assert dialog.decisions[0].isChecked() and dialog.decisions[0].isEnabled()
            dialog.next_photo.click()
            second = window.current_photo["id"]
            # No analysis copy on disk in this test: the viewer says so instead of rendering.
            assert second != first and dialog.source is None
            dialog.decisions[2].click()
            # Deciding in the enlarged view moves on, like on a light table.
            assert window.current_photo["id"] not in (first, second)
            assert next(r for r in store.photos(batch) if r["id"] == second)["data"]["decision"] == "reject"
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(PhotoViewer, "exec", inspect)
        window.large_button.click()
        assert window.viewer is None
        assert next(r for r in store.photos(batch) if r["id"] == first)["data"]["decision"] == "keep"
    finally:
        window.close()
