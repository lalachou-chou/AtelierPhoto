import multiprocessing as mp
import queue
import sqlite3
import sys
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel,
    QLockFile,
    QModelIndex,
    QPersistentModelIndex,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .config import APP_NAME, data_directory, discover
from .imaging import LIMITS
from .pipeline import (
    analysis_job,
    export_job,
    preview_worker,
    run_job,
    training_job,
)
from .store import Store

LABELS = {"keep": "Retenue", "review": "À vérifier", "reject": "Écartée", "error": "Erreur"}
COLORS = {"keep": "#91dec7", "review": "#f5cc83", "reject": "#b2b7c5", "error": "#ff9999"}
EMPTY_INDEX = QModelIndex()
FILTERS = [("Toutes les photos", None), ("Retenues", "keep"), ("À vérifier", "review"), ("Écartées", "reject"), ("Erreurs de lecture", "error")]
STYLE = """
QWidget { background: #171a21; color: #e7e8ed; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow { background: #171a21; }
QLabel#title { font-size: 25px; font-weight: 650; color: #faf9f6; }
QLabel#eyebrow { color: #91dec7; font-size: 11px; font-weight: 700; }
QLabel#muted { color: #9aa3b5; }
QLabel#preview { background: #101218; border-radius: 12px; color: #7f899e; }
QPushButton { background: #292f3b; padding: 9px 13px; border: 1px solid #394251; border-radius: 7px; }
QPushButton:hover { background: #354052; }
QPushButton:disabled { color: #626a79; border-color: #292e38; }
QPushButton#primary { background: #91dec7; color: #122c27; font-weight: 650; border: none; }
QPushButton#primary:hover { background: #b3ecda; }
QPushButton:checked { border: 1px solid #91dec7; color: #91dec7; }
QComboBox { padding: 9px; background: #232833; border: 1px solid #394251; border-radius: 6px; }
QComboBox QAbstractItemView { background: #232833; selection-background-color: #38594f; }
QListView, QListWidget { background: #1c2029; border: 1px solid #2d3441; border-radius: 8px; outline: none; }
QListView::item { padding: 7px; border-radius: 6px; }
QListView::item:selected { background: #314c47; }
QSlider::groove:horizontal { height: 4px; background: #394251; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #91dec7; border-radius: 7px; }
QProgressBar { border: none; background: #292f3b; border-radius: 4px; height: 8px; text-align: center; }
QProgressBar::chunk { background: #91dec7; border-radius: 4px; }
QSplitter::handle { background: #171a21; width: 10px; }
QToolTip { background: #303746; color: #fafafa; padding: 5px; }
"""


def label(text, name=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    if primary:
        widget.setObjectName("primary")
    return widget


class GalleryModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.directory = None
        self.cache = OrderedDict()

    def replace(self, rows, directory):
        self.beginResetModel()
        self.rows, self.directory = rows, directory
        self.cache.clear()
        self.endResetModel()

    def rowCount(self, parent=EMPTY_INDEX):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        d = row["data"]
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{Path(row['path']).name}\n{LABELS[d['decision']]}" + (" · variantes" if d.get("group") else "")
        if role == Qt.ItemDataRole.ToolTipRole:
            return d.get("error") or "\n".join(d["reasons"])
        if role == Qt.ItemDataRole.ForegroundRole:
            return QColor(COLORS[d["decision"]])
        if role == Qt.ItemDataRole.DecorationRole:
            identifier = row["id"]
            if identifier not in self.cache:
                path = self.directory / f"{identifier}.jpg"
                self.cache[identifier] = QIcon(str(path)) if path.exists() else QIcon()
                if len(self.cache) > 160:
                    self.cache.popitem(last=False)
            self.cache.move_to_end(identifier)
            return self.cache[identifier]
        if role == Qt.ItemDataRole.SizeHintRole:
            return QSize(172, 160)


class ResettableSlider(QSlider):
    """Double-click returns the setting to its initial value."""
    reset = Signal()

    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.setToolTip("Double-clic : revenir à la valeur initiale")

    def mouseDoubleClickEvent(self, event):
        if self.isEnabled():
            self.reset.emit()
        event.accept()


class Gallery(QListView):
    filesDropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(60)
        self.setUniformItemSizes(True)
        self.setIconSize(QSize(150, 108))
        self.setGridSize(QSize(174, 164))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setMovement(QListView.Movement.Static)
        self.setWordWrap(False)
        self.setAcceptDrops(True)
        self.pending_scroll = QPersistentModelIndex()
        self.verticalScrollBar().rangeChanged.connect(self.finish_scroll)

    def center_on(self, index):
        # Icon layout is batched: a distant item may not have a rectangle yet.
        self.pending_scroll = QPersistentModelIndex(index)
        self.finish_scroll()

    def finish_scroll(self, *_):
        if not self.pending_scroll.isValid():
            return
        index = QModelIndex(self.pending_scroll)
        self.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        rect = self.visualRect(index)
        if rect.isValid() and self.viewport().rect().contains(rect.center()):
            self.pending_scroll = QPersistentModelIndex()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        self.filesDropped.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
        event.acceptProposedAction()


class Window(QMainWindow):
    def __init__(self, root=None):
        super().__init__()
        self.store = Store(root or data_directory())
        self.context = mp.get_context("spawn")
        self.process = None
        self.active_job = None
        self.preview_process = None
        self.preview_in = self.context.Queue()
        self.preview_out = self.context.Queue()
        self.token = 0
        self.current_photo = None
        self.current_batch = None
        self.rows = []
        self.pixmap = None
        self.group_filter = None
        self.variants_origin = None
        self.resumable_export = None
        self.batch_look = None
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 920)
        self.setMinimumSize(1120, 740)
        self.setStyleSheet(STYLE)
        self.build_ui()
        self.reload_profiles()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(100)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.request_preview)
        self.statusBar().showMessage("Tout reste sur cet ordinateur · Originaux préservés")

    def build_ui(self):
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(24, 20, 24, 16)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label("ATELIER PHOTO  /  LOCAL", "eyebrow"))
        headline = label("Moins de tri. Plus de regard.", "title")
        headline.setWordWrap(False)
        titles.addWidget(headline)
        header.addLayout(titles)
        header.addStretch()
        self.import_button = button("+ Importer un lot", self.import_files, True)
        self.folder_button = button("Importer un dossier", self.import_folder)
        header.addWidget(self.folder_button)
        header.addWidget(self.import_button)
        outer.addLayout(header)
        outer.addSpacing(14)
        split = QSplitter()
        side = QWidget()
        sidebar = QVBoxLayout(side)
        sidebar.setContentsMargins(0, 0, 12, 0)
        sidebar.addWidget(label("VOTRE PROFIL", "eyebrow"))
        self.profiles = QComboBox()
        self.profiles.currentIndexChanged.connect(self.profile_changed)
        sidebar.addWidget(self.profiles)
        self.profile_info = label("", "muted")
        sidebar.addWidget(self.profile_info)
        self.new_button = button("Créer un profil", self.new_profile)
        self.learn_button = button("Apprendre d’un reportage trié", self.learn_reportage)
        self.learn_button.setToolTip("Rush complet + photos que vous avez gardées et retouchées :\n"
                                     "le profil apprend votre sélection et votre filtre.")
        self.rename_button = button("Renommer", self.rename_profile)
        self.reset_button = button("Réinitialiser la mémoire", self.reset_profile)
        self.delete_button = button("Supprimer le profil", lambda: self.reset_profile(True))
        for b in (self.new_button, self.learn_button, self.rename_button, self.reset_button, self.delete_button):
            sidebar.addWidget(b)
        sidebar.addSpacing(14)
        sidebar.addWidget(label("SÉLECTIVITÉ DU PROCHAIN LOT", "eyebrow"))
        self.selectivity = ResettableSlider()
        self.selectivity.setRange(0, 100)
        self.selectivity.setValue(50)
        self.selectivity.reset.connect(lambda: self.selectivity.setValue(50))
        sidebar.addWidget(self.selectivity)
        sidebar.addWidget(label("Prudente                         Exigeante", "muted"))
        sidebar.addSpacing(14)
        sidebar.addWidget(label("VOS LOTS", "eyebrow"))
        self.batches = QListWidget()
        self.batches.currentItemChanged.connect(self.batch_changed)
        sidebar.addWidget(self.batches, 1)
        self.delete_batch_button = button("Supprimer le lot sélectionné", self.delete_selected_batch)
        self.delete_batch_button.setEnabled(False)
        sidebar.addWidget(self.delete_batch_button)
        self.resume_button = button("Reprendre une tâche", self.resume_job)
        sidebar.addWidget(self.resume_button)
        sidebar.addWidget(label("RAW · JPEG · PNG\nAucun envoi dans le cloud", "muted"))
        split.addWidget(side)
        middle = QWidget()
        layout = QVBoxLayout(middle)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = label("Créez un profil pour commencer", "muted")
        layout.addWidget(self.summary)
        self.filter_button = button("Retirer le filtre sur tout le lot", self.toggle_filter)
        self.filter_button.setCheckable(True)
        self.filter_button.setChecked(True)
        self.filter_button.setToolTip("Active ou désactive le filtre appliqué sur toutes les photos du lot (aperçu et export)")
        layout.addWidget(self.filter_button)
        filter_row = QHBoxLayout()
        self.filter = QComboBox()
        for title, value in FILTERS:
            self.filter.addItem(title, value)
        self.filter.currentIndexChanged.connect(self.apply_filter)
        filter_row.addWidget(self.filter, 1)
        self.variants_button = button("Voir les variantes", self.show_variants)
        filter_row.addWidget(self.variants_button)
        self.all_button = button("Tout afficher", self.clear_group)
        filter_row.addWidget(self.all_button)
        layout.addLayout(filter_row)
        self.gallery = Gallery()
        self.model = GalleryModel(self)
        self.gallery.setModel(self.model)
        self.gallery.selectionModel().currentChanged.connect(self.photo_changed)
        self.gallery.doubleClicked.connect(lambda index: self.show_variants())
        self.gallery.filesDropped.connect(self.start_analysis)
        layout.addWidget(self.gallery, 1)
        actions = QHBoxLayout()
        self.decision_buttons = []
        for title, status in (("Retenir · 1", "keep"), ("À vérifier · 2", "review"), ("Écarter · 3", "reject")):
            b = button(title, lambda checked=False, s=status: self.decide(s))
            actions.addWidget(b)
            self.decision_buttons.append(b)
        layout.addLayout(actions)
        layout.addWidget(label("Double-clic : variantes · Ctrl / Cmd + clic : sélection multiple · Déposez un dossier ici", "muted"))
        split.addWidget(middle)
        right = QWidget()
        editor = QVBoxLayout(right)
        editor.setContentsMargins(10, 0, 0, 0)
        self.photo_title = label("Votre sélection, votre signature.", "eyebrow")
        editor.addWidget(self.photo_title)
        self.preview = label("Apprenez un reportage trié, puis importez un lot.\n\nL’aperçu de la photo sélectionnée apparaîtra ici.", "preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(260, 240)
        editor.addWidget(self.preview, 1)
        compare = QHBoxLayout()
        self.before_button = button("Afficher l’original", self.request_preview)
        self.before_button.setCheckable(True)
        compare.addWidget(self.before_button)
        editor.addLayout(compare)
        self.reasons = label("Les propositions restent modifiables avant export.", "muted")
        editor.addWidget(self.reasons)
        self.sliders = {}
        form = QFormLayout()
        names = {"intensity": "Intensité du style", "exposure": "Exposition (IL)", "temperature": "Température", "contrast": "Contraste", "saturation": "Saturation"}
        self.slider_labels = {}
        for key, bounds in LIMITS.items():
            slider = ResettableSlider()
            slider.setRange(round(bounds[0] * 100), round(bounds[1] * 100))
            slider.valueChanged.connect(lambda value, k=key: self.adjust(k, value / 100))
            slider.reset.connect(lambda k=key: self.reset_setting(k))
            self.sliders[key] = slider
            name = label(names[key])
            self.slider_labels[key] = (name, names[key])
            form.addRow(name, slider)
        editor.addLayout(form)
        self.restore_button = button("Rétablir la proposition de retouche", self.restore_recipe)
        editor.addWidget(self.restore_button)
        editor.addWidget(label("Le filtre reproduit vos retouches apprises (intensité 1 = fidèle).\nLes réglages s’appliquent à toutes les photos sélectionnées.\nDouble-clic sur un curseur : valeur initiale.", "muted"))
        footer = QHBoxLayout()
        self.validate_button = button("Valider le lot", self.validate_batch)
        self.export_button = button("Exporter…", self.export, True)
        footer.addWidget(self.validate_button)
        footer.addWidget(self.export_button)
        editor.addLayout(footer)
        split.addWidget(right)
        split.setSizes([225, 625, 500])
        outer.addWidget(split, 1)
        progress_row = QHBoxLayout()
        self.progress_label = label("Prêt", "muted")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumWidth(230)
        self.progress.setValue(0)
        self.cancel_button = button("Suspendre", self.cancel_job)
        self.cancel_button.setEnabled(False)
        progress_row.addWidget(self.progress_label, 1)
        progress_row.addWidget(self.progress)
        progress_row.addWidget(self.cancel_button)
        outer.addLayout(progress_row)
        self.setCentralWidget(central)
        self.mutators = [self.import_button, self.folder_button, self.profiles, self.batches, self.new_button, self.learn_button,
                         self.rename_button, self.reset_button, self.delete_button,
                         self.selectivity, self.resume_button, self.validate_button, self.export_button,
                         self.restore_button, self.delete_batch_button, self.filter_button,
                         *self.decision_buttons, *self.sliders.values()]
        for shortcut, status in (("1", "keep"), ("2", "review"), ("3", "reject")):
            action = QAction(self)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda checked=False, s=status: self.decide(s))
            self.addAction(action)

    def profile(self):
        return self.profiles.currentData()

    def busy(self):
        return self.process is not None

    def error(self, exc):
        QMessageBox.warning(self, APP_NAME, str(exc))

    def reload_profiles(self, selected=None):
        selected = selected or self.profile()
        self.profiles.blockSignals(True)
        self.profiles.clear()
        for row in self.store.profiles():
            self.profiles.addItem(row["name"], row["id"])
        index = self.profiles.findData(selected)
        self.profiles.setCurrentIndex(max(0, index))
        self.profiles.blockSignals(False)
        self.profile_changed()

    def profile_changed(self):
        self.batches.clear()
        self.current_batch = None
        self.rows = []
        self.apply_filter()
        if self.profile():
            self.refresh_profile_info()
            for row in self.store.batches(self.profile()):
                item = QListWidgetItem(f"{row['name']}\n{row['created']}")
                item.setData(Qt.ItemDataRole.UserRole, row["id"])
                self.batches.addItem(item)
            if self.batches.count():
                self.batches.setCurrentRow(0)
            self.resume_button.setText(f"Reprendre une tâche ({len(self.store.unfinished_jobs(self.profile()))})")
        else:
            self.profile_info.setText("Un profil mémorise votre sélection, votre filtre et vos corrections.")
        self.update_filter_ui()

    def new_profile(self):
        name, ok = QInputDialog.getText(self, "Nouveau profil", "Nom du profil")
        if ok and name.strip():
            self.reload_profiles(self.store.create_profile(name))

    def refresh_profile_info(self):
        if not self.profile():
            return
        stats = self.store.rows("SELECT json_extract(data,'$.features.saturation') AS saturation, json_extract(data,'$.features.spread') AS spread FROM refs WHERE profile=?", (self.profile(),))
        count = self.store.learning_count(self.profile())
        learned = self.store.model(self.profile())
        if learned:
            text = (f"Appris sur {learned['reportages']} reportage(s) : {learned['photos']} photos, {learned['kept']} retenues"
                    + (f", filtre sur {learned['pairs']} retouches" if learned.get("look") else ""))
        else:
            text = "Sélection et filtre par défaut · apprenez un reportage trié pour les personnaliser"
        text += f"\n{count} corrections mémorisées"
        if stats:
            text += f" · {len(stats)} anciennes références conservées"
        if stats:
            import statistics
            saturation = statistics.median(r["saturation"] for r in stats)
            spread = statistics.median(r["spread"] for r in stats)
            text += f"\nSaturation {saturation:.0%} · contraste {spread:.0%}"
        self.profile_info.setText(text)

    def delete_selected_batch(self):
        if self.busy() or not self.current_batch:
            return
        answer = QMessageBox.question(self, "Supprimer le lot", "Supprimer ce lot, ses aperçus et ses tâches associées ?\n\nLes corrections déjà apprises par le profil, les originaux et les exports seront conservés. Les corrections non validées seront perdues.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.stop_preview()
            self.store.delete_batch(self.current_batch, self.profile())
            self.profile_changed()
            self.progress_label.setText("Lot supprimé · Les apprentissages validés sont conservés dans le profil.")
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            self.error(exc)
            self.profile_changed()

    def rename_profile(self):
        if not self.profile():
            return
        name, ok = QInputDialog.getText(self, "Renommer", "Nom", text=self.profiles.currentText())
        if ok and name.strip():
            self.store.rename_profile(self.profile(), name)
            self.reload_profiles()

    def reset_profile(self, delete=False):
        if not self.profile():
            return
        title = "Supprimer le profil" if delete else "Réinitialiser la mémoire"
        result = QMessageBox.question(self, title, "Effacer les références internes, apprentissages, lots et aperçus de ce profil ?\n\nVos originaux et vos exports seront conservés.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if result == QMessageBox.StandardButton.Yes:
            try:
                self.stop_preview()
                self.store.wipe(self.profile(), delete)
                self.reload_profiles()
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                self.error(exc)

    def select_files(self, title):
        return QFileDialog.getOpenFileNames(self, title, "", "Photos (*.jpg *.jpeg *.png *.arw *.cr2 *.cr3 *.nef *.nrw *.dng *.raf *.orf *.rw2 *.pef *.srw *.3fr *.iiq *.rwl *.x3f);;Tous les fichiers (*)")[0]

    def learn_reportage(self):
        if self.busy():
            return
        if not self.profile():
            self.new_profile()
            if not self.profile():
                return
        QMessageBox.information(self, "Apprendre d’un reportage trié",
                                "Choisissez d’abord le dossier du rush complet (toutes les photos du reportage),\n"
                                "puis le dossier des photos que vous avez gardées et retouchées.\n\n"
                                "Les retenues sont reliées au rush par leur nom de fichier (DSC0123.jpg ↔ DSC0123.ARW,\n"
                                "y compris « DSC0123 N&B.jpg ») ou, à défaut, par ressemblance.")
        rush = QFileDialog.getExistingDirectory(self, "Dossier du rush complet")
        if not rush:
            return
        kept = QFileDialog.getExistingDirectory(self, "Dossier des photos retenues et retouchées")
        if not kept:
            return
        try:
            rush_files, kept_files = discover([rush]), discover([kept])
            if not rush_files or not kept_files:
                raise ValueError("Aucune photo compatible dans l’un des deux dossiers.")
            self.launch(training_job(self.store, self.profile(), rush_files, kept_files, Path(rush).name))
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            self.error(exc)

    def import_files(self):
        paths = self.select_files("Importer un nouveau lot")
        if paths:
            self.start_analysis(paths)

    def import_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Importer un dossier")
        if path:
            self.start_analysis([path])

    def start_analysis(self, paths):
        if self.busy():
            return
        if not self.profile():
            self.error("Créez un profil avant d’importer un lot.")
            return
        try:
            files = discover(paths)
            if not files:
                raise ValueError("Aucune photo compatible trouvée.")
            self.launch(analysis_job(self.store, self.profile(), files, self.selectivity.value() / 100))
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            self.error(exc)

    def batch_changed(self, item, previous=None):
        self.current_batch = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.delete_batch_button.setEnabled(bool(self.current_batch) and not self.busy())
        self.group_filter = None
        self.variants_origin = None
        self.rows = self.store.photos(self.current_batch) if self.current_batch else []
        self.batch_look = self.store.batch(self.current_batch)["snapshot"].get("look") if self.current_batch else None
        self.filter_button.blockSignals(True)
        self.filter_button.setChecked(self.store.batch(self.current_batch)["filter_enabled"] if self.current_batch else True)
        self.filter_button.blockSignals(False)
        self.update_filter_ui()
        self.apply_filter()
        self.update_export_control()

    def apply_filter(self, _index=None, *, photo_id=None):
        photo_id = photo_id or (self.current_photo["id"] if self.current_photo else None)
        self.current_photo = None
        self.token += 1
        self.pixmap = None
        self.preview.clear()
        self.preview.setText("Sélectionnez une photo pour voir l’aperçu.")
        self.photo_title.setText("Votre sélection, votre signature.")
        self.reasons.setText("Les originaux restent intacts.")
        status = self.filter.currentData()
        rows = [r for r in self.rows if (not status or r["data"]["decision"] == status) and (not self.group_filter or r["data"].get("group") == self.group_filter)]
        directory = self.store.private_dir(self.profile(), "batches", self.current_batch) if self.current_batch else self.store.root
        self.model.replace(rows, directory)
        counts = {s: sum(r["data"]["decision"] == s for r in self.rows) for s in LABELS}
        self.summary.setText(f"{len(self.rows)} photos · {counts['keep']} retenues · {counts['review']} à vérifier · {counts['reject']} écartées · {counts['error']} erreurs")
        if rows:
            row = next((i for i, photo in enumerate(rows) if photo["id"] == photo_id), 0)
            index = self.model.index(row)
            self.gallery.setCurrentIndex(index)
            self.gallery.center_on(index)

    def filter_enabled(self):
        return self.filter_button.isChecked()

    def update_filter_ui(self):
        enabled = self.filter_enabled()
        self.filter_button.setText("Retirer le filtre sur tout le lot" if enabled else "Réappliquer le filtre sur tout le lot")
        self.filter_button.setEnabled(bool(self.current_batch) and not self.busy())
        # Settings would be invisible while the filter is off.
        for widget in (*self.sliders.values(), self.restore_button):
            widget.setEnabled(enabled and not self.busy())

    def toggle_filter(self):
        if not self.current_batch or self.busy():
            self.filter_button.setChecked(not self.filter_button.isChecked())
            return
        self.store.set_filter(self.current_batch, self.filter_enabled())
        self.update_filter_ui()
        self.progress_label.setText("Filtre réactivé sur toutes les photos du lot." if self.filter_enabled()
                                    else "Filtre désactivé sur toutes les photos du lot : aperçu et export sans retouche.")
        self.request_preview()

    def selected_rows(self):
        return [self.model.rows[i.row()] for i in self.gallery.selectionModel().selectedIndexes()]

    def editable(self):
        return bool(self.current_batch and not self.busy() and self.store.batch_ready(self.current_batch))

    def photo_changed(self, index, previous=None):
        self.gallery.pending_scroll = QPersistentModelIndex()
        if not index.isValid():
            return
        self.current_photo = self.model.rows[index.row()]
        d = self.current_photo["data"]
        self.photo_title.setText(Path(self.current_photo["path"]).name)
        self.reasons.setText(d.get("error") or " · ".join(d["reasons"]))
        self.pixmap = None
        self.preview.clear()
        if "error" in d:
            self.token += 1
            self.preview.setText("Impossible de lire cette photo.")
            return
        self.preview.setText("Préparation de l’aperçu…")
        for key, slider in self.sliders.items():
            slider.blockSignals(True)
            slider.setValue(round(d["recipe"][key] * 100))
            slider.blockSignals(False)
            widget, title = self.slider_labels[key]
            widget.setText(f"{title}  {d['recipe'][key]:.2f}")
        self.request_preview()

    def request_preview(self):
        self.before_button.setText("Afficher la retouche" if self.before_button.isChecked() else "Afficher l’original")
        if not self.current_photo or "error" in self.current_photo["data"]:
            return
        if self.preview_process is None:
            self.preview_process = self.context.Process(target=preview_worker, args=(str(self.store.root), self.preview_in, self.preview_out), daemon=True)
            self.preview_process.start()
        self.token += 1
        d = self.current_photo["data"]
        path = self.store.private_dir(self.profile(), "batches", self.current_batch) / f"{self.current_photo['id']}.png"
        before = self.before_button.isChecked() or not self.filter_enabled()
        self.preview_in.put({"token": self.token, "path": str(path), "recipe": d["recipe"], "style": d["style"],
                             "look": self.batch_look, "before": before})

    def adjust(self, key, value):
        if not self.editable():
            return
        rows = self.selected_rows()
        for row in rows:
            if "error" not in row["data"]:
                row["data"]["recipe"][key] = value
                row["data"]["validated"] = False
        self.store.save_photos(rows)
        widget, title = self.slider_labels[key]
        widget.setText(f"{title}  {value:.2f}")
        self.preview_timer.start(100)

    def reset_setting(self, key):
        if not self.editable() or not self.filter_enabled():
            return
        rows = [r for r in self.selected_rows() if "error" not in r["data"]]
        for row in rows:
            row["data"]["recipe"][key] = row["data"]["initial_recipe"][key]
            row["data"]["validated"] = False
        self.store.save_photos(rows)
        if self.current_photo and "error" not in self.current_photo["data"]:
            value = self.current_photo["data"]["recipe"][key]
            slider = self.sliders[key]
            slider.blockSignals(True)
            slider.setValue(round(value * 100))
            slider.blockSignals(False)
            widget, title = self.slider_labels[key]
            widget.setText(f"{title}  {value:.2f}")
        self.preview_timer.start(100)

    def restore_recipe(self):
        if not self.editable():
            return
        rows = self.selected_rows()
        for row in rows:
            if "error" not in row["data"]:
                row["data"]["recipe"] = dict(row["data"]["initial_recipe"])
                row["data"]["validated"] = False
        self.store.save_photos(rows)
        self.photo_changed(self.gallery.currentIndex())

    def decide(self, status):
        if not self.editable():
            return
        rows = self.selected_rows()
        for row in rows:
            if "error" not in row["data"]:
                row["data"]["decision"] = status
                row["data"]["validated"] = False
        self.store.save_photos(rows)
        self.apply_filter()

    def show_variants(self):
        if self.current_photo and self.current_photo["data"].get("group"):
            if self.group_filter is None:
                self.variants_origin = self.current_photo["id"]
            self.group_filter = self.current_photo["data"]["group"]
            self.filter.blockSignals(True)
            self.filter.setCurrentIndex(0)
            self.filter.blockSignals(False)
            self.apply_filter()

    def clear_group(self):
        photo_id = self.variants_origin
        self.group_filter = None
        self.variants_origin = None
        self.filter.blockSignals(True)
        self.filter.setCurrentIndex(0)
        self.filter.blockSignals(False)
        self.apply_filter(photo_id=photo_id)

    def validate_batch(self):
        if not self.current_batch or self.busy():
            return
        if not self.editable():
            self.error("Reprenez et terminez l’analyse de ce lot avant de le valider.")
            return
        pending = sum(r["data"]["decision"] == "review" for r in self.rows)
        if pending:
            choice = QMessageBox.question(self, "Photos à vérifier", f"{pending} photos restent à vérifier et ne seront pas exportées.\nValider les autres propositions ?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if choice != QMessageBox.StandardButton.Yes:
                return
        try:
            result = self.store.validate(self.current_batch, self.profile())
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            self.error(exc)
            return
        self.rows = self.store.photos(self.current_batch)
        self.apply_filter()
        self.refresh_profile_info()
        self.progress_label.setText(f"Lot validé · {result['corrections']} corrections dans ce lot, {result['updated']} mises à jour · Profil « {self.profiles.currentText()} » : {result['total']} corrections mémorisées.")

    def export(self):
        if not self.current_batch or self.busy():
            return
        if any(not r["data"].get("validated") for r in self.rows if "error" not in r["data"]):
            self.error("Validez le lot avant l’export.")
            return
        formats = {"JPEG": "JPEG", "PNG": "PNG", "RAW + XMP (originaux RAW, retouche en fichier annexe)": "RAW"}
        choice, ok = QInputDialog.getItem(self, "Format d’export", "Format", list(formats), 0, False)
        if not ok:
            return
        format = formats[choice]
        path = QFileDialog.getExistingDirectory(self, "Dossier de destination")
        if path:
            try:
                self.launch(export_job(self.store, self.current_batch, path, format))
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                self.error(exc)

    def launch(self, identifier):
        if self.busy():
            return
        self.active_job = identifier
        self.events = self.context.Queue()
        self.cancel_event = self.context.Event()
        self.process = self.context.Process(target=run_job, args=(str(self.store.root), identifier, self.events, self.cancel_event))
        self.process.start()
        for widget in self.mutators:
            widget.setEnabled(False)
        self.update_export_control()
        job = self.store.job(identifier)
        if job["kind"] == "export":
            total = len(job["payload"]["items"])
            self.progress.setRange(0, total)
            self.progress.setValue(job["cursor"])
            self.progress_label.setText(f"Export · {job['cursor']} / {total} · Préparation…")
        else:
            self.progress.setRange(0, 0)
            self.progress_label.setText("Préparation du traitement local…")

    def update_export_control(self):
        self.resumable_export = None
        if self.busy():
            exporting = self.store.job(self.active_job)["kind"] == "export"
            self.cancel_button.setText("Mettre l’export en pause" if exporting else "Suspendre")
            self.cancel_button.setToolTip("Attend la fin de la photo en cours et mémorise la progression.")
            self.cancel_button.setEnabled(not self.cancel_event.is_set())
            return
        jobs = self.store.unfinished_jobs(self.profile()) if self.profile() else []
        job = next((j for j in reversed(jobs) if j["kind"] == "export"
                    and j["batch"] == self.current_batch and j["state"] in ("paused", "failed")), None)
        self.cancel_button.setText("Reprendre l’export" if job else "Suspendre")
        self.cancel_button.setEnabled(job is not None)
        self.cancel_button.setToolTip("Reprend au prochain fichier, dans le même dossier et au même format." if job else "")
        if job:
            self.resumable_export = job["id"]
            job = self.store.job(job["id"])
            total = len(job["payload"]["items"])
            self.progress.setRange(0, total)
            self.progress.setValue(job["cursor"])
            state = "en pause" if job["state"] == "paused" else "interrompu"
            self.progress_label.setText(f"Export {state} · {job['cursor']} / {total} · Reprise disponible")

    def cancel_job(self):
        if self.busy():
            self.cancel_event.set()
            self.progress_label.setText("Suspension après la photo en cours…")
            self.cancel_button.setEnabled(False)
        elif self.resumable_export:
            self.launch(self.resumable_export)

    def resume_job(self):
        if not self.profile() or self.busy():
            return
        jobs = self.store.unfinished_jobs(self.profile())
        if not jobs:
            self.error("Aucune tâche à reprendre.")
            return
        names = [f"{i + 1}. {j['kind']} · {j['created']} · {j['cursor']} traitées" for i, j in enumerate(jobs)]
        name, ok = QInputDialog.getItem(self, "Reprendre", "Tâche", names, 0, False)
        if ok:
            self.launch(jobs[names.index(name)]["id"])

    def poll(self):
        if self.process is not None:
            try:
                while True:
                    event = self.events.get_nowait()
                    if event["type"] == "progress":
                        self.progress.setRange(0, event["total"])
                        self.progress.setValue(event["current"])
                        if not self.cancel_event.is_set():
                            self.progress_label.setText(f"{event['current']} / {event['total']} · {event['label']}")
            except queue.Empty:
                pass
            if not self.process.is_alive():
                self.process.join()
                self.process.close()
                self.process = None
                job = self.store.job(self.active_job)
                if job["state"] == "running":
                    self.store.update_job(self.active_job, state="failed", error="Le processus a été interrompu ; la tâche peut être reprise.")
                    job = self.store.job(self.active_job)
                for widget in self.mutators:
                    widget.setEnabled(True)
                self.update_filter_ui()
                self.cancel_button.setEnabled(False)
                self.progress.setRange(0, 100)
                self.progress.setValue(100 if job["state"] == "done" else 0)
                self.progress_label.setText({"done": "Traitement terminé", "paused": "Tâche suspendue · reprise disponible", "failed": "Traitement interrompu · reprise disponible"}.get(job["state"], job["state"]))
                selected_batch = self.current_batch
                self.reload_profiles()
                if job["kind"] == "export":
                    for i in range(self.batches.count()):
                        if self.batches.item(i).data(Qt.ItemDataRole.UserRole) == selected_batch:
                            self.batches.setCurrentRow(i)
                            break
                self.update_export_control()
                if job["error"]:
                    self.error(job["error"])
                elif job["payload"].get("errors"):
                    self.error("Certains fichiers n’ont pas été traités :\n" + "\n".join(f"{e['file']} : {e['error']}" for e in job["payload"]["errors"][:12]))
                elif job["kind"] == "training" and job["state"] == "done":
                    summary = job["payload"].get("summary") or {}
                    message = (f"Profil appris : {summary.get('photos')} photos dont {summary.get('kept')} retenues"
                               f" ({summary.get('reportages')} reportage(s)), filtre appris sur {summary.get('pairs') or 0} retouches.")
                    self.progress_label.setText(message)
                    if job["payload"].get("warnings"):
                        QMessageBox.information(self, APP_NAME, message + "\n\n" + "\n".join(job["payload"]["warnings"]))
                elif job["kind"] == "export" and job["state"] == "done":
                    self.progress_label.setText(f"{len(job['payload']['outputs'])} photos exportées dans {job['payload']['destination']}")
                self.events.close()
                self.active_job = None
        try:
            while True:
                event = self.preview_out.get_nowait()
                if event["token"] == self.token:
                    if "bytes" in event:
                        self.pixmap = QPixmap()
                        self.pixmap.loadFromData(event["bytes"])
                        self.scale_preview()
                    else:
                        self.preview.setText(event["error"])
        except queue.Empty:
            pass

    def scale_preview(self):
        if self.pixmap:
            self.preview.setPixmap(self.pixmap.scaled(self.preview.size() - QSize(16, 16), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "preview"):
            self.scale_preview()

    def stop_preview(self, recreate=True):
        self.token += 1
        if self.preview_process is not None:
            self.preview_in.put(None)
            self.preview_process.join(timeout=2)
            if self.preview_process.is_alive():
                self.preview_process.terminate()
                self.preview_process.join(timeout=2)
            self.preview_process.close()
            self.preview_process = None
        self.preview_in.close()
        self.preview_out.close()
        if recreate:
            self.preview_in = self.context.Queue()
            self.preview_out = self.context.Queue()

    def closeEvent(self, event):
        if self.busy():
            self.cancel_job()
            self.progress_label.setText("Suspension en cours. Fermez la fenêtre une fois le traitement suspendu.")
            event.ignore()
            return
        self.timer.stop()
        self.preview_timer.stop()
        self.stop_preview(recreate=False)
        self.store.close()
        event.accept()


def main():
    mp.freeze_support()
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from .diagnostics import self_test
        self_test(sys.argv[2])
        return
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("AtelierPhoto")
    root = data_directory()
    root.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(root / "application.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, "Atelier Photo est déjà ouvert pour cette bibliothèque.")
        return
    with_store = Store(root)
    with_store.recover_interrupted_jobs()
    with_store.close()
    window = Window()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
