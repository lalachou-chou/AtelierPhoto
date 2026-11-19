from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from atelier.app import FILTERS, Gallery, GalleryModel, Window
from atelier.store import uid
from atelier.workspace_ui import stylesheet


def test_gallery_grid_settles_when_isolating_three_variants(qapp, tmp_path):
    gallery = Gallery()
    gallery.setStyleSheet(stylesheet("Atelier"))
    model = GalleryModel(gallery)
    gallery.setModel(model)
    rows = [{"id": str(i), "path": f"photo-{i}.jpg", "data": {"decision": "reject", "group": "4"}}
            for i in range(120)]
    for i in range(3):
        thumbnail = QPixmap(80 if i == 2 else 180, 120)
        thumbnail.fill()
        assert thumbnail.save(str(tmp_path / f"{i}.jpg"))

    def positions():
        return tuple(gallery.visualRect(model.index(i)).topLeft().toTuple() for i in range(3))

    try:
        gallery.resize(350, 428)
        model.replace(rows, tmp_path)
        gallery.show()
        QTest.qWait(50)
        assert gallery.verticalScrollBar().maximum() > 0
        model.replace(rows[:3], tmp_path)
        gallery.setCurrentIndex(model.index(1))
        gallery.center_on(model.index(1))
        for width, columns in ((350, 2), (220, 1), (450, 3), (350, 2)):
            gallery.resize(width, 428)
            QTest.qWait(50)
            layout = positions()
            assert sum(y == layout[0][1] for _, y in layout) == columns
            for _ in range(30):
                qapp.processEvents()
                assert positions() == layout
            assert gallery.currentIndex().row() == 1
        model.replace(rows, tmp_path)
        QTest.qWait(50)
        assert gallery.verticalScrollBar().maximum() > 0
    finally:
        gallery.close()


def test_filter_counts_follow_batch_decisions_and_variant_scope(qapp, store, monkeypatch):
    monkeypatch.setattr(Window, "photo_changed", lambda *_: None)
    profile = store.create_profile("Compteurs")
    batch = store.create_batch(profile, "Photos", {}, .5)
    for index, (status, group) in enumerate((("keep", "a"), ("keep", "b"), ("review", "a"), ("reject", "b"), ("error", None))):
        store.save_photo(uid(), batch, f"photo-{index}.jpg", {"decision": status, "group": group, "reasons": []})
    window = Window(store.root)

    def counts(values):
        assert [window.filter.itemText(i) for i in range(len(FILTERS))] == [
            f"{title} ({value})" for (title, _), value in zip(FILTERS, values, strict=True)]

    try:
        counts([5, 2, 1, 1, 1])
        window.filter.setCurrentIndex(1)
        assert len(window.model.rows) == 2
        counts([5, 2, 1, 1, 1])
        window.gallery.setCurrentIndex(window.model.index(0))
        window.decide("reject")
        counts([5, 1, 1, 2, 1])
        assert FILTERS[window.filter.currentIndex()][1] == "keep"
        assert len(window.model.rows) == 1
        window.group_filter = "a"
        window.filter.setCurrentIndex(0)
        counts([2, 0, 1, 1, 0])
        assert len(window.model.rows) == 2
        window.clear_group()
        counts([5, 1, 1, 2, 1])
        empty = store.create_batch(profile, "Vide", {}, .5)
        window.profile_changed()
        assert window.current_batch == empty
        counts([0, 0, 0, 0, 0])
    finally:
        window.close()


def test_import_formats_are_in_tooltips_and_profile_button_is_explicit(qapp, store):
    window = Window(store.root)
    try:
        assert window.import_button.text() == "Importer…"
        assert window.rename_button.text() == "Renommer le profil"
        assert "RAW · JPEG · PNG" in window.import_button.toolTip()
        assert all("RAW · JPEG · PNG" not in label.text() for label in window.findChildren(QLabel))
        assert window.filter.itemText(0) == "Toutes les photos (0)"
    finally:
        window.close()
