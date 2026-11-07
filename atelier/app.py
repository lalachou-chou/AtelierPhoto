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
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .config import (
    APP_NAME,
    PHOTO_FILTER,
    QUARANTINE_DIR,
    data_directory,
    discover,
    resource_directory,
)
from .imaging import LIMITS
from .pipeline import (
    analysis_job,
    export_job,
    preview_worker,
    run_job,
    selection_job,
    training_update_job,
)
from .progress import remaining_time_text
from .store import Store
from .task_dialog import TaskDialog
from .training_dialog import TrainingDialog

LABELS = {"keep": "Retenue", "review": "À vérifier", "reject": "Écartée", "error": "Erreur", "pending": "Tri en attente"}
COLORS = {"keep": "#91dec7", "review": "#f5cc83", "reject": "#b2b7c5", "error": "#ff9999", "pending": "#9aa3b5"}
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
QTextBrowser#helpContent QScrollBar:vertical { background: #202530; width: 8px; border: none; border-radius: 4px; margin: 0; }
QTextBrowser#helpContent QScrollBar::handle:vertical { background: #536173; min-height: 32px; border-radius: 4px; }
QTextBrowser#helpContent QScrollBar::handle:vertical:hover { background: #91dec7; }
QTextBrowser#helpContent QScrollBar::add-line:vertical, QTextBrowser#helpContent QScrollBar::sub-line:vertical { height: 0; border: none; background: transparent; }
QTextBrowser#helpContent QScrollBar::add-page:vertical, QTextBrowser#helpContent QScrollBar::sub-page:vertical { background: transparent; }
QScrollArea#profilePanel QScrollBar:vertical { background: #202530; width: 8px; border: none; margin: 0; }
QScrollArea#profilePanel QScrollBar::handle:vertical { background: #536173; min-height: 32px; border-radius: 4px; }
QScrollArea#profilePanel QScrollBar::add-line:vertical, QScrollArea#profilePanel QScrollBar::sub-line:vertical { height: 0; }
QScrollArea#profilePanel QScrollBar::add-page:vertical, QScrollArea#profilePanel QScrollBar::sub-page:vertical { background: transparent; }
"""


def quarantine_message(entries):
    """Corrupt RAW files set aside by a finished task; the task itself succeeded."""
    moved = [e for e in entries if e.get("to")]
    lines = [f"{len(entries)} fichier(s) RAW corrompu(s) ignoré(s) ; les autres photos ont bien été traitées."]
    if moved:
        lines.append(f"Déplacé(s) dans un sous-dossier « {QUARANTINE_DIR} » à côté de l’original :")
    lines += [f"• {e['file']}" + ("" if e.get("to") else " (non déplacé : dossier en lecture seule)") for e in entries[:12]]
    if len(entries) > 12:
        lines.append(f"… et {len(entries) - 12} autre(s).")
    return "\n".join(lines)


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


def selection_status(data):
    return "pending" if data.get("selection_pending") else data["decision"]


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
            return f"{Path(row['path']).name}\n{LABELS[selection_status(d)]}" + (" · variantes" if d.get("group") else "")
        if role == Qt.ItemDataRole.ToolTipRole:
            return d.get("error") or "\n".join(d["reasons"])
        if role == Qt.ItemDataRole.ForegroundRole:
            return QColor(COLORS[selection_status(d)])
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


class FileDropTarget:
    """Accept local files as copies; web links and internal drags are ignored."""

    def dragEnterEvent(self, event):
        if self.isEnabled() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if self.isEnabled() and paths:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.filesDropped.emit(paths)
        else:
            event.ignore()


class ImportDropZone(FileDropTarget, QLabel):
    filesDropped = Signal(list)

    def __init__(self):
        super().__init__("Déposez un dossier ou des photos ici")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setAcceptDrops(True)
        self.setStyleSheet("QLabel { border: 1px dashed #91dec7; border-radius: 8px; padding: 14px; color: #91dec7; }"
                          "QLabel:disabled { border-color: #394251; color: #626a79; }")
        self.setToolTip("Glissez depuis l’Explorateur ou le Finder pour importer un nouveau lot.\n"
                        "Vous pouvez aussi utiliser « Importer un dossier ».")


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
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
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
        FileDropTarget.dragEnterEvent(self, event)

    def dragMoveEvent(self, event):
        FileDropTarget.dragMoveEvent(self, event)

    def dropEvent(self, event):
        FileDropTarget.dropEvent(self, event)


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
        self.setWindowIcon(QIcon(str(resource_directory() / "app-icon.png")))
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
        self.import_button = button("+ Importer des photos", self.import_files, True)
        self.import_button.setToolTip("Formats acceptés : RAW · JPEG · PNG.")
        self.folder_button = button("Importer un dossier", self.import_folder)
        self.folder_button.setToolTip("Formats acceptés : RAW · JPEG · PNG ; les sous-dossiers sont inclus.")
        header.addWidget(self.folder_button)
        header.addWidget(self.import_button)
        self.help_button = button("?  Aide", self.show_help)
        self.help_button.setAccessibleName("Aide")
        self.help_button.setToolTip("Comprendre l’application et les étapes à suivre")
        header.addWidget(self.help_button)
        outer.addLayout(header)
        outer.addSpacing(14)
        split = QSplitter()
        side = QWidget()
        sidebar = QVBoxLayout(side)
        sidebar.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        sidebar.setContentsMargins(0, 0, 12, 0)
        sidebar.addWidget(label("VOTRE PROFIL", "eyebrow"))
        self.profiles = QComboBox()
        self.profiles.currentIndexChanged.connect(self.profile_changed)
        sidebar.addWidget(self.profiles)
        self.profile_info = label("", "muted")
        self.profile_info.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        sidebar.addWidget(self.profile_info)
        self.new_button = button("Créer un profil", self.new_profile)
        self.new_button.setToolTip("Crée un profil indépendant pour apprendre vos choix de sélection et de retouche.")
        self.learn_button = button("Apprendre de reportages triés", self.learn_reportage)
        self.learn_button.setToolTip("Gérez vos reportages triés et vos groupes de références pour personnaliser la sélection et les retouches.")
        self.rename_button = button("Renommer le profil", self.rename_profile)
        self.rename_button.setToolTip("Change uniquement le nom du profil sélectionné.")
        self.clear_feedback_button = button("Effacer les corrections apprises", self.clear_feedback)
        self.clear_feedback_button.setToolTip("Oublie les corrections mémorisées par « Valider le lot », sans modifier les reportages d’apprentissage.")
        self.delete_button = button("Supprimer le profil", self.delete_profile)
        self.delete_button.setToolTip("Supprime ce profil et le travail associé dans l’application, sans toucher à vos fichiers photo.")
        for b in (self.new_button, self.learn_button, self.rename_button, self.clear_feedback_button, self.delete_button):
            sidebar.addWidget(b)
        sidebar.addSpacing(14)
        selectivity_title = label("SÉLECTIVITÉ", "eyebrow")
        selectivity_help = ("À droite : moins de photos retenues. À gauche : davantage.\n"
                            "Profil par défaut au centre : environ 16 % de retenues ; jusqu’à 35 % à vérifier.\n"
                            "S’applique au lot affiché et aux prochains imports ; vos choix manuels et retouches sont conservés.")
        selectivity_title.setToolTip(selectivity_help)
        sidebar.addWidget(selectivity_title)
        self.selectivity = ResettableSlider()
        self.selectivity.setToolTip(selectivity_help + "\nDouble-clic : revenir au réglage central.")
        self.selectivity.setRange(0, 100)
        self.selectivity.setValue(50)
        self.selectivity.setTracking(False)
        self.selectivity.valueChanged.connect(self.change_selectivity)
        self.selectivity.reset.connect(lambda: self.selectivity.setValue(50))
        sidebar.addWidget(self.selectivity)
        selectivity_ends = QHBoxLayout()
        for text, alignment in (("+ de photos", Qt.AlignmentFlag.AlignLeft),
                                ("− de photos", Qt.AlignmentFlag.AlignRight)):
            endpoint = label(text, "muted")
            endpoint.setWordWrap(False)
            endpoint.setAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
            selectivity_ends.addWidget(endpoint, 1)
        sidebar.addLayout(selectivity_ends)
        sidebar.addSpacing(14)
        sidebar.addWidget(label("VOS LOTS EN COURS", "eyebrow"))
        self.batches = QListWidget()
        self.batches.currentItemChanged.connect(self.batch_changed)
        sidebar.addWidget(self.batches, 1)
        self.delete_batch_button = button("Supprimer le lot sélectionné", self.delete_selected_batch)
        self.delete_batch_button.setEnabled(False)
        sidebar.addWidget(self.delete_batch_button)
        self.resume_button = button("Gérer les tâches", self.manage_jobs)
        self.resume_button.setToolTip("Reprenez ou supprimez une tâche en attente, suspendue ou interrompue.")
        sidebar.addWidget(self.resume_button)
        profile_scroll = QScrollArea()
        profile_scroll.setObjectName("profilePanel")
        profile_scroll.setWidgetResizable(True)
        profile_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        profile_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        profile_scroll.setMinimumWidth(225)
        profile_scroll.setWidget(side)
        split.addWidget(profile_scroll)
        middle = QWidget()
        layout = QVBoxLayout(middle)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = label("Créez un profil pour commencer", "muted")
        layout.addWidget(self.summary)
        self.filter_button = button("Retirer la retouche sur tout le lot", self.toggle_filter)
        self.filter_button.setCheckable(True)
        self.filter_button.setChecked(True)
        self.filter_button.setToolTip("Active ou désactive la retouche appliquée sur toutes les photos du lot (aperçu et export)")
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
        self.drop_zone = ImportDropZone()
        self.drop_zone.filesDropped.connect(self.start_analysis)
        layout.addWidget(self.drop_zone)
        self.gallery = Gallery()
        self.model = GalleryModel(self)
        self.gallery.setModel(self.model)
        # QListView disables viewport drops when the model has no drop actions.
        # Our external import handler does not insert rows through the model.
        self.gallery.viewport().setAcceptDrops(True)
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
        layout.addWidget(label("Double-clic : variantes · Ctrl / Cmd + clic : sélection multiple", "muted"))
        split.addWidget(middle)
        right = QWidget()
        editor = QVBoxLayout(right)
        editor.setContentsMargins(10, 0, 0, 0)
        self.photo_title = label("Votre sélection, votre signature.", "eyebrow")
        editor.addWidget(self.photo_title)
        self.preview = label("Importez un lot, avec le profil par défaut ou après ajout de reportages ou de références.\n\nL’aperçu de la photo sélectionnée apparaîtra ici.", "preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(260, 240)
        editor.addWidget(self.preview, 1)
        compare = QHBoxLayout()
        self.before_button = button("Afficher l’original (sans retouche)", self.request_preview)
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
            if key == "intensity":
                explanation = "Dose l’effet du style sur les photos sélectionnées, de zéro à son intensité complète."
                name.setToolTip(explanation)
                slider.setToolTip(explanation + "\nDouble-clic : revenir à la valeur initiale.")
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
        self.progress_label.setToolTip("L’estimation concerne les photos restant à traiter ; la durée du calcul final du profil ou du tri peut varier.")
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
        self.mutators = [self.import_button, self.folder_button, self.drop_zone, self.profiles, self.batches, self.new_button, self.learn_button,
                         self.rename_button, self.clear_feedback_button, self.delete_button,
                         self.selectivity, self.resume_button, self.validate_button, self.export_button,
                         self.restore_button, self.delete_batch_button, self.filter_button,
                         *self.decision_buttons, *self.sliders.values()]
        for shortcut, status in (("1", "keep"), ("2", "review"), ("3", "reject")):
            action = QAction(self)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda checked=False, s=status: self.decide(s))
            self.addAction(action)

    def show_help(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Aide — Atelier Photo")
        dialog.resize(600, 650)
        dialog.setMinimumSize(480, 360)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(label("Vos photos, du tri à l’export", "title"))
        introduction = (
            "Atelier Photo propose une sélection et une première retouche de vos photos. "
            "Vous gardez le dernier mot. Tout se fait sur votre ordinateur, sans modifier les originaux.")
        steps = (
            ("1. Créez ou choisissez un profil",
             "Il mémorise vos préférences de sélection et de retouche."),
            ("2. Apprenez-lui vos goûts (facultatif)",
             "Ouvrez « Apprendre de reportages triés ».\n\n"
             "« Ajouter un reportage » : fournissez le rush complet, puis les photos retenues, retouchées ou non.\n\n"
             "« Ajouter des références » : choisissez des photos exemples sans leur rush associé. "
             "Leur sujet et leur rendu guident le tri et les retouches.\n\n"
             "Chaque ajout forme une ligne cochable. Décochez un groupe pour ne plus l’utiliser, "
             "puis appliquez les changements. Vous pourrez le recocher plus tard."),
            ("Quand mes nouveaux exemples sont-ils utilisés ?",
             "Lancez l’apprentissage et attendez le message de fin. Importez ensuite les photos à trier : "
             "elles bénéficieront de vos nouveaux exemples.\n\n"
             "Les lots déjà importés gardent leurs propositions de tri et de retouche. "
             "Ajouter ou décocher des exemples ne refait pas leur analyse.\n\n"
             "L’apprentissage personnalise les préférences de votre profil. "
             "Les références seules ne montrent pas quelles photos vous avez écartées ni les étapes exactes de vos retouches."),
            ("3. Importez un nouveau lot",
             "Cliquez sur « Importer des photos » ou « Importer un dossier », puis attendez la fin de l’analyse."),
            ("4. Vérifiez et ajustez",
             "Parcourez les photos retenues, à vérifier et écartées. Corrigez les choix et ajustez les retouches si besoin."),
            ("5. Validez et exportez",
             "Cliquez sur « Valider le lot », puis « Exporter… ». Choisissez le format et le dossier. "
             "Seules les photos retenues sont exportées."),
            ("Sélectivité",
             "À gauche, plus de photos retenues ; à droite, un tri plus strict.\n\n"
             "Avec le profil par défaut, partez du centre : l’objectif est d’environ 16 % de retenues, "
             "avec jusqu’à 35 % de photos à vérifier. Ces dernières ne sont pas exportées.\n\n"
             "Les doublons et défauts techniques peuvent réduire le nombre de retenues. "
             "Un profil appris sur vos reportages conserve son propre taux de sélection.\n\n"
             "Le réglage agit sur le lot affiché et les prochains imports. "
             "Vos choix manuels et retouches sont conservés ; validez à nouveau après le tri."),
            ("Retirer la retouche sur tout le lot",
             "Ce bouton désactive les retouches pour l’aperçu et l’export, pour tout le lot. "
             "Cliquez à nouveau pour les réappliquer."),
            ("Comparer les variantes",
             "Ce sont les photos d’une même scène regroupées pour faciliter votre choix. "
             "Double-cliquez sur une photo ou cliquez sur « Voir les variantes » pour les comparer. "
             "« Tout afficher » revient au lot complet."),
        )
        content = QTextBrowser()
        content.setObjectName("helpContent")
        content.setFrameStyle(0)
        sections = [f"<p>{introduction}</p>"]
        for title, description in steps:
            sections.append(f"<h3>{title}</h3>")
            sections.extend(f"<p>{paragraph}</p>" for paragraph in description.split("\n\n"))
        content.setHtml("<style>h3 { margin-top: 20px; margin-bottom: 8px; } "
                        "p { margin-top: 0; margin-bottom: 10px; }</style>" + "".join(sections))
        layout.addWidget(content, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Fermer")
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

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
        self.analysis_incomplete = False
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
        else:
            self.profile_info.setText("Un profil mémorise votre sélection, votre filtre et vos corrections.")
            self.clear_feedback_button.setEnabled(False)
        count = len(self.store.unfinished_jobs(self.profile())) if self.profile() else 0
        self.resume_button.setText(f"Gérer les tâches ({count})")
        self.update_filter_ui()

    def new_profile(self):
        name, ok = QInputDialog.getText(self, "Nouveau profil", "Nom du profil")
        if ok and name.strip():
            self.reload_profiles(self.store.create_profile(name))

    def refresh_profile_info(self):
        if not self.profile():
            return
        references = len(self.store.references(self.profile(), active_only=True))
        count = self.store.learning_count(self.profile())
        self.clear_feedback_button.setEnabled(bool(count) and not self.busy())
        learned = self.store.model(self.profile())
        if learned:
            text = (f"Appris sur {learned['reportages']} reportage(s) : {learned['photos']} photos, {learned['kept']} retenues"
                    + (f", filtre sur {learned['pairs']} retouches" if learned.get("look") else ""))
        else:
            text = "Sélection et filtre par défaut"
        text += f"\n{count} corrections mémorisées"
        text += f"\n{references} référence(s) actives"
        self.profile_info.setText(text)

    def clear_feedback(self):
        if self.busy() or not self.profile() or not self.store.learning_count(self.profile()):
            return
        message = ("Effacer les corrections apprises lors de la validation des lots pour ce profil ?\n\n"
                   "Les reportages d’apprentissage et les lots existants seront conservés. "
                   "Valider à nouveau un lot pourra mémoriser ses corrections à nouveau.")
        if QMessageBox.question(self, "Effacer les corrections apprises", message,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.clear_feedback(self.profile())
            self.refresh_profile_info()
            self.progress_label.setText("Corrections apprises effacées pour les prochains lots.")
        except (ValueError, sqlite3.Error) as exc:
            self.error(exc)

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
        name, ok = QInputDialog.getText(self, "Renommer le profil", "Nom du profil", text=self.profiles.currentText())
        if ok and name.strip():
            self.store.rename_profile(self.profile(), name)
            self.reload_profiles()

    def delete_profile(self):
        if not self.profile():
            return
        message = ("Supprimer ce profil, ses choix appris et le travail de tri et de retouche associé dans l’application ?\n\n"
                   "Les photos sur votre disque, y compris celles déjà exportées, seront conservées.")
        result = QMessageBox.question(self, "Supprimer le profil", message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if result == QMessageBox.StandardButton.Yes:
            try:
                self.stop_preview()
                self.store.wipe(self.profile(), delete=True)
                self.reload_profiles()
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                self.error(exc)

    def select_files(self, title):
        return QFileDialog.getOpenFileNames(self, title, "", PHOTO_FILTER)[0]

    def learn_reportage(self):
        if self.busy():
            return
        if not self.profile():
            self.new_profile()
            if not self.profile():
                return
        dialog = TrainingDialog(self, self.store.reportages(self.profile()), self.store.reference_groups(self.profile()))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.launch(training_update_job(self.store, self.profile(), dialog.reportages(), dialog.reference_groups()))
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            self.error(exc)

    def import_files(self):
        paths = self.select_files("Importer des photos")
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

    def change_selectivity(self, value):
        if not self.current_batch or self.busy():
            return
        previous = self.store.batch(self.current_batch)["selectivity"]
        if abs(value / 100 - previous) < 1e-6:
            return
        try:
            self.launch(selection_job(self.store, self.current_batch, value / 100))
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            self.selectivity.blockSignals(True)
            self.selectivity.setValue(round(previous * 100))
            self.selectivity.blockSignals(False)
            self.error(exc)

    def batch_changed(self, item, previous=None):
        self.current_batch = item.data(Qt.ItemDataRole.UserRole) if item else None
        batch = self.store.batch(self.current_batch) if self.current_batch else None
        self.delete_batch_button.setEnabled(bool(self.current_batch) and not self.busy())
        self.group_filter = None
        self.variants_origin = None
        self.rows = self.store.photos(self.current_batch) if self.current_batch else []
        self.analysis_incomplete = bool(self.current_batch and self.store.rows(
            "SELECT id FROM jobs WHERE batch=? AND kind='analysis' AND state NOT IN ('done','superseded')",
            (self.current_batch,)))
        # Includes interrupted batches created before pending states were shown.
        for row in self.rows:
            data = row["data"]
            if self.analysis_incomplete and "error" not in data and "score" not in data:
                data["selection_pending"] = True
        self.batch_look = batch["snapshot"].get("look") if batch else None
        if batch:
            self.selectivity.blockSignals(True)
            self.selectivity.setValue(round(batch["selectivity"] * 100))
            self.selectivity.blockSignals(False)
        self.filter_button.setChecked(batch["filter_enabled"] if batch else True)
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
        scoped = [r for r in self.rows if not self.group_filter or r["data"].get("group") == self.group_filter]
        scoped_counts = {s: sum(selection_status(r["data"]) == s for r in scoped) for s in LABELS}
        blocked = self.filter.blockSignals(True)
        for i, (title, value) in enumerate(FILTERS):
            count = len(scoped) if value is None else scoped_counts[value]
            self.filter.setItemText(i, f"{title} ({count})")
        self.filter.blockSignals(blocked)
        rows = [r for r in scoped if not status or selection_status(r["data"]) == status]
        directory = self.store.private_dir(self.profile(), "batches", self.current_batch) if self.current_batch else self.store.root
        self.model.replace(rows, directory)
        counts = {s: sum(selection_status(r["data"]) == s for r in self.rows) for s in LABELS}
        self.summary.setText(f"{len(self.rows)} photos · {counts['keep']} retenues · {counts['review']} à vérifier · {counts['reject']} écartées · {counts['error']} erreurs")
        if counts["pending"]:
            self.summary.setText(self.summary.text() + f" · {counts['pending']} en attente de tri")
        if self.analysis_incomplete:
            self.summary.setText(self.summary.text() + "\nImport incomplet · Tri provisoire sur les photos déjà analysées · Reprise via « Gérer les tâches »")
        if rows:
            row = next((i for i, photo in enumerate(rows) if photo["id"] == photo_id), 0)
            index = self.model.index(row)
            self.gallery.setCurrentIndex(index)
            self.gallery.center_on(index)

    def filter_enabled(self):
        return self.filter_button.isChecked()

    def update_filter_ui(self):
        enabled = self.filter_enabled()
        self.filter_button.setText("Retirer la retouche sur tout le lot" if enabled else "Réappliquer la retouche sur tout le lot")
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
        self.before_button.setText("Afficher la retouche" if self.before_button.isChecked() else "Afficher l’original (sans retouche)")
        if not self.current_photo or "error" in self.current_photo["data"]:
            return
        if self.preview_process is None:
            self.preview_process = self.context.Process(target=preview_worker, args=(self.preview_in, self.preview_out), daemon=True)
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
                row["data"]["manual_decision"] = True
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
            self.error("Reprenez et terminez l’analyse ou le tri de ce lot avant de le valider.")
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
        self.gallery.setAcceptDrops(False)
        self.gallery.viewport().setAcceptDrops(False)
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

    def manage_jobs(self):
        if not self.profile() or self.busy():
            return
        jobs = self.store.unfinished_jobs(self.profile())
        if not jobs:
            QMessageBox.information(self, "Gérer les tâches", "Aucune tâche en attente, suspendue ou interrompue.")
            return
        while jobs:
            dialog = TaskDialog(jobs, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            job = dialog.selected_job()
            if dialog.action == "resume":
                self.launch(job["id"])
                return
            message = "Supprimer cette tâche ? Elle ne pourra plus être reprise."
            if job["kind"] == "analysis" and job["batch"]:
                message += "\n\nLe lot incomplet et ses aperçus seront aussi supprimés ; vos fichiers photo seront conservés."
            elif job["kind"] == "export":
                message += "\n\nLe lot et les fichiers déjà exportés seront conservés."
            else:
                message += "\n\nLes reportages enregistrés, les apprentissages du profil et vos photos seront conservés."
            if QMessageBox.question(self, "Supprimer une tâche", message,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                try:
                    selected_batch = self.current_batch
                    self.stop_preview()
                    self.store.delete_job(job["id"], self.profile())
                    self.profile_changed()
                    for i in range(self.batches.count()):
                        if self.batches.item(i).data(Qt.ItemDataRole.UserRole) == selected_batch:
                            self.batches.setCurrentRow(i)
                            break
                    self.update_export_control()
                    self.progress_label.setText("Tâche supprimée.")
                except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                    self.error(exc)
            jobs = self.store.unfinished_jobs(self.profile())

    def poll(self):
        if self.process is not None:
            try:
                while True:
                    event = self.events.get_nowait()
                    if event["type"] == "progress":
                        self.progress.setRange(0, event["total"])
                        self.progress.setValue(event["current"])
                        if not self.cancel_event.is_set():
                            estimate = remaining_time_text(event.get("remaining_seconds"))
                            self.progress_label.setText(f"{event['current']} / {event['total']} · {event['label']}"
                                                        + (f" · {estimate}" if estimate else ""))
                    elif event["type"] == "phase":
                        self.progress.setRange(0, 0)
                        if not self.cancel_event.is_set():
                            self.progress_label.setText(event["label"] + " · Durée restante non estimable")
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
                self.gallery.setAcceptDrops(True)
                self.gallery.viewport().setAcceptDrops(True)
                self.update_filter_ui()
                self.cancel_button.setEnabled(False)
                self.progress.setRange(0, 100)
                self.progress.setValue(100 if job["state"] == "done" else 0)
                self.progress_label.setText({"done": "Traitement terminé", "paused": "Tâche suspendue · reprise disponible", "failed": "Traitement interrompu · reprise disponible"}.get(job["state"], job["state"]))
                selected_batch = job["payload"]["batch"] if job["kind"] == "selection" else self.current_batch
                self.reload_profiles()
                if job["kind"] in ("export", "selection"):
                    for i in range(self.batches.count()):
                        if self.batches.item(i).data(Qt.ItemDataRole.UserRole) == selected_batch:
                            self.batches.setCurrentRow(i)
                            break
                self.update_export_control()
                if job["error"]:
                    self.error(job["error"])
                if job["payload"].get("errors"):
                    self.error("Certains fichiers n’ont pas été traités :\n" + "\n".join(f"{e['file']} : {e['error']}" for e in job["payload"]["errors"][:12]))
                if job["payload"].get("quarantined"):
                    QMessageBox.information(self, APP_NAME, quarantine_message(job["payload"]["quarantined"]))
                if job["kind"] == "training" and job["state"] == "done":
                    summary = job["payload"].get("summary") or {}
                    message = (f"Profil appris : {summary.get('photos')} photos dont {summary.get('kept')} retenues"
                               f" ({summary.get('reportages')} reportage(s)), filtre appris sur {summary.get('pairs') or 0} retouches.")
                    if not summary.get("reportages"):
                        message = "Exemples mis à jour · Sélection et filtre par défaut."
                    if "reference_groups" in summary:
                        message += f" {summary['reference_groups']} groupe(s) de références actifs pour les prochains imports."
                    self.progress_label.setText(message)
                    if job["payload"].get("warnings"):
                        QMessageBox.information(self, APP_NAME, message + "\n\n" + "\n".join(job["payload"]["warnings"]))
                elif job["kind"] == "export" and job["state"] == "done":
                    self.progress_label.setText(f"{len(job['payload']['outputs'])} photos exportées dans {job['payload']['destination']}")
                elif job["kind"] == "selection" and job["state"] == "done":
                    self.progress_label.setText("Tri mis à jour · Choix manuels et retouches conservés · Validez à nouveau le lot avant l’export.")
                elif job["kind"] == "references" and job["state"] == "done":
                    self.progress_label.setText("Ajout des références terminé · Les exemples lisibles guident le tri et les retouches des prochains lots.")
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
    from .windows_lifecycle import mark_running
    mark_running()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("AtelierPhoto")
    app.setWindowIcon(QIcon(str(resource_directory() / "app-icon.png")))
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
