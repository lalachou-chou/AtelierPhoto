"""Manage a profile's reportages and stage its next training selection."""
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .config import PHOTO_FILTER, RAW_EXTENSIONS, discover


def reference_kinds(paths):
    """'2 RAW · 3 JPEG/PNG' for a reference group."""
    raw = sum(Path(path).suffix.lower() in RAW_EXTENSIONS for path in paths)
    counts = {"RAW": raw, "JPEG/PNG": len(paths) - raw}
    return " · ".join(f"{n} {label}" for label, n in counts.items() if n)


def reportage_files(rush_directory, kept_paths):
    """Exclude delivered-export subfolders without dropping selected originals."""
    root = Path(rush_directory).resolve()
    folders = [Path(p).resolve() for p in kept_paths if Path(p).is_dir()]
    if any(root == folder or root.is_relative_to(folder) for folder in folders):
        raise ValueError("Choisissez un dossier de photos retenues distinct du rush et qui ne contient pas le dossier du rush.")
    rush = [p for p in discover([root]) if not any(Path(p).is_relative_to(folder) for folder in folders)]
    kept = discover(kept_paths)
    if not rush or not kept:
        raise ValueError("Aucune photo compatible dans le rush ou dans les photos choisies.")
    if set(rush) <= set(kept):
        raise ValueError("Le rush doit aussi contenir des photos écartées pour apprendre vos choix.")
    return {"name": root.name, "rush": rush, "kept": kept}


class TrainingDialog(QDialog):
    def __init__(self, parent=None, reportages=(), reference_groups=()):
        super().__init__(parent)
        self.initial = {("reportage", r["id"]): bool(r["enabled"]) for r in reportages}
        self.initial.update({("references", g["id"]): bool(g["enabled"]) for g in reference_groups})
        self.setWindowTitle("Reportages et références du profil")
        self.resize(880, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title = QLabel("Les exemples qui façonnent votre profil")
        title.setObjectName("heading")
        title.setWordWrap(True)
        layout.addWidget(title)
        explanation = QLabel(
            "Ajoutez l’un ou l’autre type d’exemples, ou combinez les deux. "
            "Ils seront utilisés pour les prochains lots importés avec ce profil.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.add = QPushButton("Ajouter un reportage…")
        self.add.setToolTip("Choisissez le dossier du rush complet, puis celui des photos retenues ; les sous-dossiers sont inclus.")
        self.add.clicked.connect(self.add_reportage)
        additions = QHBoxLayout()
        self.add_references = QPushButton("Ajouter des références")
        self.add_references.setToolTip("Sélectionnez des photos exemples sans leur rush associé ; elles formeront un groupe cochable.")
        self.add_references.clicked.connect(self.add_reference_group)
        for caption, text, control in (
            ("Reportages déjà triés", "Le rush complet + vos photos retenues, retouchées ou non. "
             "Atelier apprend quelles photos vous gardez et lesquelles vous écartez. Pour apprendre le tri : "
             "au moins 6 originaux, dont 2 retenus et 1 écarté. Plus vous ajoutez de reportages complets, "
             "plus le tri est fidèle.", self.add),
            ("Photos de référence", "Des photos exemples sans leur rush associé, RAW, JPEG ou PNG : "
             "le type d’images que vous aimez garder. Au tri, les photos qui leur ressemblent montent "
             "dans le classement, y compris pour choisir la meilleure variante d’une scène.", self.add_references),
        ):
            card = QFrame()
            card.setObjectName("guideCard")
            content = QVBoxLayout(card)
            content.setContentsMargins(14, 14, 14, 14)
            heading = QLabel(caption)
            heading.setObjectName("cardTitle")
            heading.setWordWrap(True)
            content.addWidget(heading)
            description = QLabel(text)
            description.setWordWrap(True)
            content.addWidget(description)
            content.addStretch()
            content.addWidget(control)
            additions.addWidget(card, 1)
        layout.addLayout(additions)
        instruction = QLabel("Ajouter des exemples  →  Cocher les groupes à utiliser  →  Appliquer l’apprentissage")
        instruction.setObjectName("eyebrow")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.list)
        self.remove = QPushButton("Retirer les éléments sélectionnés")
        self.remove.setToolTip("Retire les lignes sélectionnées du profil lors de l’application des changements, sans supprimer vos photos.")
        self.remove.clicked.connect(self.remove_selected)
        self.list.itemSelectionChanged.connect(self.update_summary)
        self.list.itemChanged.connect(self.update_summary)
        removal = QHBoxLayout()
        removal.addWidget(self.remove)
        removal.addStretch()
        layout.addLayout(removal)
        hint = QLabel("Décochez un groupe pour le garder sans l’utiliser. Annuler conserve les réglages actuels. "
                      "Après application, attendez le bilan de l’apprentissage avant d’importer.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        buttons.rejected.connect(self.reject)
        self.start = buttons.addButton("Lancer l’apprentissage", QDialogButtonBox.ButtonRole.AcceptRole)
        self.start.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        for record in reportages:
            self.add_record(record)
        for group in reference_groups:
            self.add_record(dict(group, kind="references"))
        self.update_summary()

    def entries(self):
        return [dict(self.list.item(i).data(Qt.ItemDataRole.UserRole),
                     enabled=self.list.item(i).checkState() == Qt.CheckState.Checked) for i in range(self.list.count())]

    def reportages(self):
        return [r for r in self.entries() if r.get("kind") != "references"]

    def reference_groups(self):
        return [r for r in self.entries() if r.get("kind") == "references"]

    def add_reference_group(self):
        chosen, _ = QFileDialog.getOpenFileNames(self, "Références — photos sans leur rush associé", "", PHOTO_FILTER)
        if not chosen:
            return
        try:
            # Sidecars are found next to their photo; selecting them alongside is harmless.
            paths = discover([c for c in chosen if Path(c).suffix.lower() != ".xmp"])
            if not paths:
                raise ValueError("Aucune photo compatible trouvée.")
            if any(set(g["paths"]) == set(paths) for g in self.reference_groups()):
                raise ValueError("Ce groupe de références est déjà dans la liste. Cochez sa ligne pour l’utiliser.")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        folders = {Path(p).parent for p in paths}
        name = next(iter(folders)).name if len(folders) == 1 else "Sélection de références"
        self.add_record({"kind": "references", "name": name, "paths": paths})
        self.update_summary()

    def add_reportage(self):
        rush = QFileDialog.getExistingDirectory(self, "Dossier du rush complet")
        if not rush:
            return
        kept = QFileDialog.getExistingDirectory(self, "Dossier des photos retenues", rush)
        if not kept:
            return
        try:
            record = reportage_files(rush, [kept])
            existing = {p for r in self.reportages() for p in r["rush"]}
            if existing.intersection(record["rush"]):
                raise ValueError("Ce rush chevauche un reportage déjà ajouté à la liste.")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        self.add_record(record)
        self.update_summary()

    def add_record(self, record):
        state = "Enregistré dans le profil" if record.get("ready") else "À apprendre" if record.get("id") else "Nouveau"
        if record.get("kind") == "references":
            count = record["count"] if record.get("ready") else len(record["paths"])
            text = f"Références · {record['name']} · {count} photos · {state}\nPhotos exemples sans rush associé"
            if not record.get("ready") and record.get("paths"):
                text += " · " + reference_kinds(record["paths"])
        else:
            rush = str(Path(record["rush"][0]).parent) if record["rush"] else "aucune photo lisible"
            text = (f"Reportage · {record['name']} · {len(record['rush'])} photos · {len(record['kept'])} retenues · {state}\n"
                    f"Rush : {rush}")
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, record)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if record.get("enabled", True) else Qt.CheckState.Unchecked)
        item.setToolTip("Coché : utilisé au prochain apprentissage. Décoché : conservé dans le profil sans être utilisé.")
        self.list.addItem(item)
        self.list.setCurrentItem(item, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def remove_selected(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self.update_summary()

    def update_summary(self, *_):
        entries = self.entries()
        reportages, groups = self.reportages(), self.reference_groups()
        selected = [r for r in reportages if r["enabled"]]
        selected_groups = [g for g in groups if g["enabled"]]
        remaining = {(r.get("kind", "reportage"), r["id"]): r["enabled"] for r in entries if r.get("id")}
        removed = len(self.initial.keys() - remaining.keys())
        changed = remaining != self.initial or any(not r.get("id") for r in entries)
        self.summary.setText(
            f"{len(selected)} / {len(reportages)} reportage(s) cochés · "
            f"{sum(len(r['rush']) for r in selected)} photos · "
            f"{sum(len(r['kept']) for r in selected)} retenues"
            + f"\n{len(selected_groups)} / {len(groups)} groupe(s) de références cochés"
            + (f" · {removed} à retirer du profil" if removed else "")
            + ("\nSans reportage coché : tri par défaut, complété par les références cochées." if not selected else ""))
        self.start.setText(("Appliquer et relancer l’apprentissage" if self.initial else "Lancer l’apprentissage")
                           if selected or selected_groups else "Appliquer les modifications")
        self.start.setEnabled(bool(selected or selected_groups) or changed)
        self.remove.setEnabled(bool(self.list.selectedItems()))
