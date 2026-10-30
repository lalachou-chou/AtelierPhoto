from PySide6.QtWidgets import QLabel

from atelier.app import FILTERS, Window
from atelier.store import uid


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
        assert window.filter.currentData() == "keep"
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
        assert window.import_button.text() == "+ Importer des photos"
        assert window.rename_button.text() == "Renommer le profil"
        for button in (window.import_button, window.folder_button):
            assert "RAW · JPEG · PNG" in button.toolTip()
        assert all("RAW · JPEG · PNG" not in label.text() for label in window.findChildren(QLabel))
        assert window.filter.itemText(0) == "Toutes les photos (0)"
    finally:
        window.close()
