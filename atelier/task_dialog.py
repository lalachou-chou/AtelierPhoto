"""Choose an unfinished task to resume or delete."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

KINDS = {"analysis": "Analyse d’un lot", "selection": "Sélectivité du lot", "training": "Apprentissage", "export": "Export", "references": "Références"}
STATES = {"pending": "En attente", "paused": "En pause", "failed": "Interrompue", "running": "En cours"}


class TaskDialog(QDialog):
    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gérer les tâches")
        self.resize(620, 340)
        self.action = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choisissez une tâche à reprendre ou à supprimer."))
        self.list = QListWidget()
        self.list.setWordWrap(True)
        for job in jobs:
            item = QListWidgetItem(
                f"{KINDS.get(job['kind'], job['kind'])} · {STATES.get(job['state'], job['state'])}\n"
                f"{job['created']} · {job['cursor']} photo(s) traitée(s)")
            item.setData(Qt.ItemDataRole.UserRole, job)
            if job.get("error"):
                item.setToolTip(job["error"])
            self.list.addItem(item)
        layout.addWidget(self.list)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Fermer")
        buttons.rejected.connect(self.reject)
        self.resume = buttons.addButton("Reprendre", QDialogButtonBox.ButtonRole.ActionRole)
        self.delete = buttons.addButton("Supprimer", QDialogButtonBox.ButtonRole.ActionRole)
        self.resume.clicked.connect(lambda: self.choose("resume"))
        self.delete.clicked.connect(lambda: self.choose("delete"))
        self.list.currentRowChanged.connect(self.update_actions)
        layout.addWidget(buttons)
        self.list.setCurrentRow(0)
        self.update_actions()

    def selected_job(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def update_actions(self, *_):
        job = self.selected_job()
        enabled = bool(job and job["state"] in ("pending", "paused", "failed"))
        self.resume.setEnabled(enabled)
        self.delete.setEnabled(enabled)

    def choose(self, action):
        job = self.selected_job()
        if job and job["state"] in ("pending", "paused", "failed"):
            self.action = action
            self.accept()
