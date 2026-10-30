from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton

from atelier.training_dialog import TrainingDialog, reportage_files


def files(folder, count):
    folder.mkdir(parents=True)
    result = []
    for i in range(count):
        path = folder / f"photo-{i}.jpg"
        path.write_bytes(b"placeholder")
        result.append(str(path))
    return result


def test_nested_deliveries_excluded_but_selected_originals_preserved(tmp_path):
    import pytest

    root = tmp_path / "rush"
    originals = files(root, 6)
    chosen = files(root / "retouches", 3)
    record = reportage_files(root, [root / "retouches"])
    assert set(record["rush"]) == set(originals)
    assert set(record["kept"]) == set(chosen)
    record = reportage_files(root, originals[:2])
    assert set(originals[:2]) <= set(record["rush"])
    with pytest.raises(ValueError, match="distinct"):
        reportage_files(root, [root])


def test_dialog_adds_multiple_pairs_and_removes_one(qapp, tmp_path, monkeypatch):
    rush_a, rush_b = tmp_path / "A", tmp_path / "B"
    files(rush_a, 6)
    selected_a = files(tmp_path / "chosen-A", 3)
    originals_b = files(rush_b, 6)
    selected_b = files(rush_b / "retenues" / "sous-dossier", 2)
    directories = iter([str(rush_a), str(tmp_path / "chosen-A"), str(rush_b), str(rush_b / "retenues")])
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: next(directories))
    dialog = TrainingDialog()
    try:
        assert not dialog.start.isEnabled()
        assert len([b for b in dialog.findChildren(QPushButton) if b.text().startswith("Ajouter")]) == 2
        dialog.add.click()
        dialog.add.click()
        assert dialog.start.isEnabled()
        assert len(dialog.reportages()) == 2
        assert dialog.reportages()[0]["kept"] == selected_a
        assert dialog.reportages()[1]["kept"] == selected_b
        assert dialog.reportages()[1]["rush"] == originals_b
        assert "12 photos" in dialog.summary.text()
        dialog.list.setCurrentRow(0)
        dialog.remove_selected()
        assert [r["name"] for r in dialog.reportages()] == ["B"]
        dialog.list.selectAll()
        dialog.remove_selected()
        assert not dialog.start.isEnabled()
    finally:
        dialog.close()


def test_dialog_cancel_and_duplicate_do_not_add_partial_entries(qapp, tmp_path, monkeypatch):
    root = tmp_path / "rush"
    files(root, 6)
    kept = tmp_path / "retenues"
    files(kept, 2)
    directories = iter(["", str(root), "", str(root), str(kept), str(root), str(kept)])
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: next(directories))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[-1]))
    dialog = TrainingDialog()
    try:
        dialog.add_reportage()
        dialog.add_reportage()
        assert not dialog.reportages()
        dialog.add_reportage()
        dialog.add_reportage()
        assert len(dialog.reportages()) == 1
        assert warnings and "chevauche" in warnings[0]
    finally:
        dialog.close()


def test_existing_reportages_can_be_unchecked_removed_or_cancelled(qapp):
    records = [{"id": name, "name": name, "rush": [f"/{name}/photo.jpg"],
                "kept": [f"/{name}/kept.jpg"], "ready": True, "enabled": True} for name in ("A", "B")]
    dialog = TrainingDialog(reportages=records)
    try:
        assert len(dialog.reportages()) == 2
        dialog.list.item(0).setCheckState(Qt.CheckState.Unchecked)
        assert not dialog.reportages()[0]["enabled"]
        assert "1 / 2" in dialog.summary.text()
        dialog.list.selectAll()
        dialog.remove.click()
        assert dialog.reportages() == []
        assert dialog.start.isEnabled()  # Removing even the last learned reportage must be applicable.
        assert "2 à retirer" in dialog.summary.text()
        dialog.reject()
        assert all(r["enabled"] for r in records)  # Edits are staged, not written on removal/cancel.
        reopened = TrainingDialog(reportages=records)
        assert len(reopened.reportages()) == 2
        reopened.close()
    finally:
        dialog.close()
