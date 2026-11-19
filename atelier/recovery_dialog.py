from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class RecoveryDialog(QDialog):
    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Récupérer les photos corrompues")
        self.resize(740, 420)
        layout = QVBoxLayout(self)
        description = QLabel(
            "Cochez les photos à récupérer, puis choisissez où enregistrer les copies. "
            "Pour un RAW, Atelier Photo extrait l’aperçu du boîtier quand il est lisible. "
            "Un JPEG endommagé peut donner une image partielle.")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.list = QListWidget()
        self.list.setAccessibleName("Photos mises à l’écart dans le profil")
        self.list.setWordWrap(True)
        layout.addWidget(self.list)
        for entry in entries:
            lines = [Path(entry["original"]).name, entry["path"]]
            if entry["output"]:
                lines.append(f"Copie enregistrée dans {entry['output']}")
            if entry["error"]:
                lines.append(f"Dernier essai infructueux · {entry['error']}")
            item = QListWidgetItem("\n".join(lines), self.list)
            item.setData(Qt.ItemDataRole.UserRole, entry["path"])
            item.setCheckState(Qt.CheckState.Unchecked)
        buttons = QDialogButtonBox()
        self.recover = buttons.addButton("Récupérer la sélection…", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Fermer", QDialogButtonBox.ButtonRole.RejectRole)
        self.recover.setEnabled(False)
        self.list.itemChanged.connect(lambda: self.recover.setEnabled(bool(self.paths())))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def paths(self):
        items = (self.list.item(i) for i in range(self.list.count()))
        return [item.data(Qt.ItemDataRole.UserRole) for item in items if item.checkState() == Qt.CheckState.Checked]
