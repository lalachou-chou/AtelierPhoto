import multiprocessing as mp
import queue
import sqlite3
import sys
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QLockFile,
    QModelIndex,
    QPersistentModelIndex,
    QSettings,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import help_ui, performance
from .config import (
    APP_NAME,
    PHOTO_FILTER,
    QUARANTINE_DIR,
    data_directory,
    discover,
    resource_directory,
)
from .pipeline import (
    analysis_job,
    export_job,
    recovery_job,
    run_job,
    selection_job,
    training_update_job,
)
from .progress import remaining_time_text
from .recovery_dialog import RecoveryDialog
from .store import Store
from .task_dialog import TaskDialog
from .training_dialog import TrainingDialog
from .workspace_ui import (
    PALETTES,
    PhotoViewer,
    PrepareImport,
    PreviewLabel,
    strength,
    stylesheet,
)

LABELS = {"keep": "Retenue", "review": "À vérifier", "reject": "Écartée", "error": "Erreur", "pending": "Tri en attente"}
EMPTY_INDEX = QModelIndex()
FILTERS = [("Toutes les photos", None), ("Retenues", "keep"), ("À vérifier", "review"), ("Écartées", "reject"), ("Erreurs de lecture", "error")]


def quarantine_message(entries):
    """Corrupt RAW files set aside by a finished task; the task itself succeeded."""
    moved = [e for e in entries if e.get("to")]
    lines = [f"{len(entries)} photo(s) mise(s) à l’écart. "
             "Utilisez « Récupérer les photos corrompues » pour choisir les fichiers à traiter."]
    if moved:
        lines.append(f"Déplacé(s) dans un sous-dossier « {QUARANTINE_DIR} » à côté de l’original :")
    for entry in entries[:12]:
        detail = ""
        if not entry.get("to"):
            detail = " (fichier conservé à son emplacement)"
        lines.append(f"• {entry['file']}{detail}")
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
            return d.get("error") or "\n".join(d.get("reasons", []))
        if role == Qt.ItemDataRole.DecorationRole:
            identifier = row["id"]
            if identifier not in self.cache:
                path = self.directory / f"{identifier}.jpg"
                pixmap = QPixmap(str(path)) if path.exists() else QPixmap()
                self.cache[identifier] = QIcon(pixmap)
                if len(self.cache) > 160:
                    self.cache.popitem(last=False)
            self.cache.move_to_end(identifier)
            return self.cache[identifier]
        if role == Qt.ItemDataRole.SizeHintRole:
            return QSize(172, 160)


class SelectivitySlider(QSlider):
    """Double-click returns to the balanced selectivity."""

    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.setToolTip("Double-clic : revenir à la valeur initiale")

    def mouseDoubleClickEvent(self, event):
        if self.isEnabled():
            self.setValue(50)
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
        self.setObjectName("drop")
        self.setToolTip("Glissez depuis l’Explorateur ou le Finder pour importer un nouveau lot.\n"
                        "Vous pouvez aussi utiliser « Importer… » en haut de la fenêtre.")


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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Budget for the scrollbar even when hidden. Otherwise its appearance
        # changes the cell width, which can change the number of rows again.
        scrollbar_width = self.verticalScrollBar().sizeHint().width()
        available = max(1, self.maximumViewportSize().width() - scrollbar_width - 4)
        columns = max(1, available // 124)
        width = min(195, available // columns)
        height = max(50, (width - 14) * 2 // 3)
        grid = QSize(width, height + 54)
        if grid != self.gridSize():
            self.setIconSize(QSize(max(1, width - 14), height))
            self.setGridSize(grid)

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
        self.current_photo = None
        self.current_batch = None
        self.rows = []
        self.pixmap = None
        self.group_filter = None
        self.variants_origin = None
        self.variant_groups = {}
        self.resumable_export = None
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(resource_directory() / "app-icon.png")))
        self.resize(1330, 820)
        self.setMinimumSize(800, 600)
        self.settings = QSettings(str(self.store.root / "interface.ini"), QSettings.Format.IniFormat)
        self.theme = self.settings.value("appearance", "Atelier")
        self.set_theme(self.theme if self.theme in PALETTES else "Atelier")
        self.viewer = None
        self.build_ui()
        self.reload_profiles(self.settings.value("active_profile", None))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(100)
        self.restore_panels()

    def build_ui(self):
        central = QWidget()
        central.setObjectName("workspace")
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 12, 16, 10)
        header = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(self.windowIcon().pixmap(32, 32))
        header.addWidget(mark)
        header.addWidget(label("Atelier Photo", "brand"))
        header.addStretch()
        self.import_button = button("Importer…", self.prepare_import)
        self.import_button.setToolTip("Préparer un lot de photos RAW · JPEG · PNG.")
        self.export_button = button("Exporter…", self.export, True)
        self.help_button = button("Aide", self.show_help)
        for widget in (self.import_button, self.export_button, button("Apparence", self.appearance), self.help_button):
            header.addWidget(widget)
        outer.addLayout(header)
        toolbar = QHBoxLayout()
        self.batch_title = label("Votre premier lot", "heading")
        self.batch_meta = label("", "muted")
        batch_heading = QVBoxLayout()
        batch_heading.setSpacing(3)
        batch_heading.addWidget(self.batch_title)
        batch_heading.addWidget(self.batch_meta)
        toolbar.addLayout(batch_heading, 1)
        self.panel_menu = QMenu(self)
        panel_button = QToolButton()
        panel_button.setText("Panneaux")
        panel_button.setMenu(self.panel_menu)
        panel_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar.addWidget(panel_button)
        self.options_button = button("Options du lot", lambda: self.options_dialog.exec())
        toolbar.addWidget(self.options_button)
        outer.addLayout(toolbar)

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(7)
        self.panes = []
        self.panel_actions = []
        layouts = []
        for i, title in enumerate(("Profil et lots", "Aperçu", "Galerie")):
            panel = QWidget()
            panel.setObjectName("pane")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(12, 12, 12, 12)
            heading = QHBoxLayout()
            heading.addWidget(label(title, "heading"), 1)
            toggle = self.panel_menu.addAction(title)
            toggle.setCheckable(True)
            toggle.setChecked(True)
            toggle.toggled.connect(lambda visible, index=i: self.toggle_panel(index, visible))
            hide = button("×", toggle.toggle)
            hide.setFixedWidth(30)
            hide.setToolTip(f"Masquer le panneau {title}")
            hide.setAccessibleName(hide.toolTip())
            heading.addWidget(hide)
            layout.addLayout(heading)
            self.panel_actions.append(toggle)
            self.panes.append(panel)
            layouts.append(layout)
            self.split.addWidget(panel)
        self.panel_menu.addSeparator()
        self.panel_menu.addAction("Rétablir la disposition", self.reset_panels)
        self.layout_sizes = [225, 650, 360]
        self.split.splitterMoved.connect(self.remember_sizes)
        outer.addWidget(self.split, 1)
        self.empty_panels = button("Rouvrir les panneaux", self.reset_panels)
        outer.addWidget(self.empty_panels)
        self.empty_panels.hide()
        left, center, right = layouts

        self.profile_area = QVBoxLayout()
        self.profile_area.setSpacing(8)
        left.addLayout(self.profile_area)
        left.addWidget(label("LOTS DU PROFIL", "eyebrow"))

        self.batches = QListWidget()
        self.batches.setAccessibleName("Lots du profil")
        self.batches.currentItemChanged.connect(self.batch_changed)
        self.batches.itemClicked.connect(self.return_to_selected_batch)
        left.addWidget(self.batches, 1)
        self.delete_batch_button = button("Supprimer ce lot…", self.delete_selected_batch)
        self.delete_batch_button.setEnabled(False)
        self.filter = QComboBox()
        self.filter.setMinimumContentsLength(14)
        self.filter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.filter.setAccessibleName("Afficher les photos par décision")
        for title, _ in FILTERS:
            self.filter.addItem(title)
        self.filter.setCurrentIndex(0)
        self.filter.currentIndexChanged.connect(self.apply_filter)
        right.addWidget(label("Afficher les photos", "muted"))
        right.addWidget(self.filter)

        self.preview = PreviewLabel()
        self.preview.setMinimumSize(110, 105)
        self.preview.installEventFilter(self)
        self.preview.activated.connect(self.enlarge)
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self.preview)
        welcome = QWidget()
        welcome.setObjectName("welcome")
        welcome_layout = QVBoxLayout(welcome)
        welcome_layout.setContentsMargins(22, 18, 22, 18)
        welcome_layout.setSpacing(16)
        welcome_layout.addStretch()
        welcome_layout.addWidget(label("VOTRE PREMIÈRE SÉANCE", "eyebrow"))
        welcome_layout.addWidget(label("Tout commence par votre profil", "heading"))
        welcome_layout.addWidget(label("1  Choisissez ou créez votre profil à gauche.\n\n"
                                       "2  Ajoutez des reportages déjà triés ou des photos de référence, "
                                       "puis lancez l’apprentissage.\n\n"
                                       "3  Cliquez sur Importer… : le rush est trié automatiquement, "
                                       "variante par variante, dès la fin de l’analyse."))
        welcome_layout.addWidget(button("Configurer mon profil…", self.open_profiles, True))
        welcome_layout.addWidget(button("Voir le guide de démarrage", self.show_guide))
        welcome_layout.addStretch()
        welcome_scroll = QScrollArea()
        welcome_scroll.setFrameShape(QFrame.Shape.NoFrame)
        welcome_scroll.setWidgetResizable(True)
        welcome_scroll.setWidget(welcome)
        self.preview_stack.addWidget(welcome_scroll)
        center.addWidget(self.preview_stack, 1)
        self.photo_controls = QWidget()
        photo_controls = QVBoxLayout(self.photo_controls)
        photo_controls.setContentsMargins(0, 0, 0, 0)
        center.addWidget(self.photo_controls)
        caption = QHBoxLayout()
        self.photo_title = label("")
        caption.addWidget(self.photo_title, 1)
        self.large_button = button("Agrandir", self.enlarge)
        caption.addWidget(self.large_button)
        self.prev_button = button("‹", lambda: self.move_photo(-1))
        self.next_button = button("›", lambda: self.move_photo(1))
        for arrow, title in ((self.prev_button, "Photo précédente"), (self.next_button, "Photo suivante")):
            arrow.setFixedWidth(32)
            arrow.setAccessibleName(title)
            arrow.setToolTip(title)
            caption.addWidget(arrow)
        photo_controls.addLayout(caption)
        self.reasons = label("", "muted")
        photo_controls.addWidget(self.reasons)
        decisions = QHBoxLayout()
        self.decision_buttons = []
        for key, (title, status) in enumerate((("Retenir", "keep"), ("À vérifier", "review"), ("Écarter", "reject")), 1):
            b = button(f"{title} · {key}", lambda checked=False, s=status: self.decide(s))
            b.setCheckable(True)
            decisions.addWidget(b)
            self.decision_buttons.append(b)
            action = QAction(self)
            action.setShortcut(str(key))
            action.triggered.connect(lambda checked=False, s=status: self.decide(s))
            self.addAction(action)
        photo_controls.addLayout(decisions)

        variants = QHBoxLayout()
        self.group_picker = QComboBox()
        self.group_picker.addItem("Aucune variante détectée")
        self.group_picker.setEnabled(False)
        self.group_picker.setAccessibleName("Groupes de variantes du lot")
        self.group_picker.setMinimumContentsLength(12)
        self.group_picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.group_picker.activated.connect(self.pick_group)
        right.addWidget(self.group_picker)
        self.variants_button = button("Isoler ses variantes", self.show_variants)
        self.all_button = button("Revenir au lot", self.clear_group)
        self.prefer_button = button("Garder uniquement celle-ci", self.prefer_variant)
        self.prefer_button.setToolTip("Retenir cette photo et écarter toutes les autres variantes du groupe.")
        variants.addWidget(self.variants_button)
        variants.addWidget(self.all_button)
        right.addLayout(variants)
        right.addWidget(self.prefer_button)
        self.gallery = Gallery()
        self.model = GalleryModel(self)
        self.gallery.setModel(self.model)
        self.gallery.viewport().setAcceptDrops(True)
        self.gallery.selectionModel().currentChanged.connect(self.photo_changed)
        self.gallery.selectionModel().selectionChanged.connect(self.update_selection_scope)
        self.gallery.doubleClicked.connect(lambda index: self.enlarge())
        self.gallery.filesDropped.connect(self.prepare_import)
        right.addWidget(self.gallery, 1)
        self.drop_zone = ImportDropZone()
        self.drop_zone.filesDropped.connect(self.prepare_import)
        right.addWidget(self.drop_zone)
        self.selection_scope = label("", "muted")
        photo_controls.addWidget(self.selection_scope)
        self.summary = label("", "muted")
        outer.addWidget(self.summary)

        self.build_dialogs()
        progress = QHBoxLayout()
        self.progress_label = label("Prêt", "muted")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumWidth(150)
        self.progress.setValue(0)
        self.cancel_button = button("Suspendre", self.cancel_job)
        self.cancel_button.setEnabled(False)
        self.load_value = None
        self.load_picker = QComboBox()
        self.load_picker.setAccessibleName("Charge de l’ordinateur pendant les importations")
        for key, title in performance.MODES.items():
            self.load_picker.addItem(f"Charge : {title}", key)
        saved = performance.normalize(self.settings.value("performance/load", performance.default_mode()))
        self.load_picker.setCurrentIndex(list(performance.MODES).index(saved))
        self.load_picker.currentIndexChanged.connect(self.load_changed)
        self.describe_load()
        progress.addWidget(self.progress_label, 1)
        progress.addWidget(self.load_picker)
        progress.addWidget(self.progress)
        progress.addWidget(self.cancel_button)
        progress.addWidget(button("Tâches…", lambda: self.tasks_dialog.exec()))
        outer.addLayout(progress)
        self.setCentralWidget(central)
        self.import_notice = QLabel(central)
        self.import_notice.setObjectName("importNotice")
        self.import_notice.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.import_notice.hide()
        self.notice_timer = QTimer(self, singleShot=True, interval=10000)
        self.notice_timer.timeout.connect(self.import_notice.hide)
        self.mutators = [self.import_button, self.drop_zone, self.profiles, self.batches, self.new_button,
                         self.learn_button, self.rename_button, self.clear_feedback_button, self.delete_button,
                         self.selectivity, self.resume_button, self.recovery_button, self.validate_button,
                         self.export_button, self.delete_batch_button, self.prefer_button,
                         self.profile_learn_button, self.profile_picker, *self.decision_buttons]

    def tool_dialog(self, title):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(350)
        dialog.resize(500, 400)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        return dialog, layout

    @staticmethod
    def finish_dialog(dialog, layout):
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Fermer")
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

    def build_dialogs(self):
        self.profile_dialog, layout = self.tool_dialog("Profils et apprentissage")
        self.profiles = QComboBox()
        self.profiles.setMinimumContentsLength(12)
        self.profiles.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.profiles.setPlaceholderText("Aucun profil")
        self.profiles.setAccessibleName("Profil affiché")
        self.profiles.currentIndexChanged.connect(self.profile_changed)
        self.profile_area.addWidget(label("PROFIL ACTIF", "eyebrow"))
        self.profile_area.addWidget(self.profiles)
        self.profile_area.addWidget(button("Gérer les profils…", self.open_profiles))
        self.profile_caption = label("", "heading")
        layout.addWidget(self.profile_caption)
        self.profile_picker = QComboBox()
        self.profile_picker.setAccessibleName("Choisir le profil à gérer")
        self.profile_picker.setModel(self.profiles.model())
        self.profile_picker.currentIndexChanged.connect(self.profiles.setCurrentIndex)
        self.profiles.currentIndexChanged.connect(self.profile_picker.setCurrentIndex)
        layout.addWidget(self.profile_picker)
        self.profile_info = label("", "muted")
        layout.addWidget(self.profile_info)
        self.profile_summary = label("", "muted")
        self.new_button = button("Créer un profil", self.new_profile)
        self.learn_button = button("Reportages et références…", self.learn_reportage)
        self.learn_button.setToolTip("Personnaliser le profil : apprendre de reportages déjà triés et ajouter des photos de référence.")
        self.profile_area.addWidget(self.learn_button)
        self.profile_area.addWidget(self.profile_summary)
        self.rename_button = button("Renommer le profil", self.rename_profile)
        self.clear_feedback_button = button("Effacer les corrections apprises", self.clear_feedback)
        self.clear_feedback_button.setToolTip("Oublier les corrections mémorisées par « Valider le lot » pour ce profil.")
        self.delete_button = button("Supprimer le profil", self.delete_profile)
        layout.addWidget(label("Ce profil possède ses propres reportages, références et lots. "
                               "Le profil choisi ici devient aussi le profil actif de l’écran principal.", "muted"))
        for b in (self.new_button, self.rename_button):
            layout.addWidget(b)
        self.profile_learn_button = button("Reportages et références…", self.learn_from_profiles, True)
        layout.addWidget(self.profile_learn_button)
        layout.addSpacing(12)
        layout.addWidget(label("Gestion des données du profil", "muted"))
        for b in (self.clear_feedback_button, self.delete_button):
            layout.addWidget(b)
        self.finish_dialog(self.profile_dialog, layout)
        self.profile_dialog.resize(520, 600)

        self.options_dialog, layout = self.tool_dialog("Options du lot")
        layout.addWidget(label("Recalculer le tri du lot affiché"))
        self.selectivity = SelectivitySlider()
        self.selectivity.setAccessibleName("Sélectivité du lot affiché")
        self.selectivity.setRange(0, 100)
        self.selectivity.setValue(50)
        self.selectivity.setTracking(False)
        self.selectivity.valueChanged.connect(self.change_selectivity)
        layout.addWidget(self.selectivity)
        layout.addWidget(label("À gauche, garder davantage. À droite, garder moins.", "muted"))
        self.validate_button = button("Valider le lot", self.validate_batch)
        self.validate_button.setToolTip("Mémorise vos choix manuels pour affiner les prochains tris de ce profil.")
        for b in (self.validate_button, self.delete_batch_button):
            layout.addWidget(b)
        self.finish_dialog(self.options_dialog, layout)

        self.tasks_dialog, layout = self.tool_dialog("Tâches et récupération")
        self.resume_button = button("Gérer les tâches", self.manage_jobs)
        self.recovery_button = button("Récupérer les photos corrompues", self.recover_photos)
        layout.addWidget(self.resume_button)
        layout.addWidget(self.recovery_button)
        self.finish_dialog(self.tasks_dialog, layout)

    def set_theme(self, name):
        self.theme = name
        paper, surface, ink, muted, _, selected, accent, _ = PALETTES[name]
        palette = self.palette()
        role = QPalette.ColorRole
        for key, color in ((role.Window, paper), (role.WindowText, ink), (role.Text, ink),
                           (role.Base, surface), (role.AlternateBase, paper), (role.Button, surface),
                           (role.ButtonText, ink), (role.Link, accent), (role.LinkVisited, accent),
                           (role.Highlight, selected), (role.HighlightedText, ink), (role.PlaceholderText, muted)):
            palette.setColor(key, QColor(color))
        self.setPalette(palette)
        self.setStyleSheet(stylesheet(name))
        self.settings.setValue("appearance", name)

    def appearance(self):
        dialog, layout = self.tool_dialog("Apparence")
        for name, (_, _, _, _, _, _, accent, _) in PALETTES.items():
            b = QPushButton(name)
            swatch = QPixmap(24, 16)
            swatch.fill(QColor(accent))
            b.setIcon(QIcon(swatch))
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setChecked(name == self.theme)
            b.clicked.connect(lambda checked=False, n=name: self.set_theme(n))
            layout.addWidget(b)
        self.finish_dialog(dialog, layout)
        dialog.exec()
        dialog.deleteLater()

    def remember_sizes(self, *_):
        for i, size in enumerate(self.split.sizes()):
            if size and self.panel_actions[i].isChecked():
                self.layout_sizes[i] = size

    def toggle_panel(self, index, visible):
        self.panes[index].setVisible(visible)
        any_visible = any(a.isChecked() for a in self.panel_actions)
        self.split.setVisible(any_visible)
        self.empty_panels.setVisible(not any_visible)
        self.split.setSizes([w if a.isChecked() else 0 for w, a in zip(self.layout_sizes, self.panel_actions, strict=True)])

    def reset_panels(self):
        self.layout_sizes = [225, 650, 360]
        for action in self.panel_actions:
            action.setChecked(True)
        self.split.setSizes(self.layout_sizes)

    def restore_panels(self):
        for i, action in enumerate(self.panel_actions):
            self.layout_sizes[i] = max(1, self.settings.value(f"panels/{i}/width", self.layout_sizes[i], type=int))
            action.setChecked(self.settings.value(f"panels/{i}/visible", True, type=bool))
        self.split.setSizes([w if a.isChecked() else 0 for w, a in zip(self.layout_sizes, self.panel_actions, strict=True)])

    def enlarge(self):
        if not self.current_photo or self.viewer is not None:
            return
        viewer = PhotoViewer(self)
        self.viewer = viewer
        viewer.navigate.connect(self.move_photo)
        viewer.decided.connect(self.decide)
        viewer.setWindowState(viewer.windowState() | Qt.WindowState.WindowMaximized)
        self.update_viewer()
        viewer.exec()
        self.viewer = None
        viewer.deleteLater()

    def move_photo(self, delta):
        count = self.model.rowCount()
        if count:
            index = self.model.index((self.gallery.currentIndex().row() + delta) % count)
            self.gallery.setCurrentIndex(index)
            self.gallery.center_on(index)

    def update_viewer(self):
        if self.viewer is None:
            return
        self.viewer.setWindowTitle(self.photo_title.text())
        count = self.model.rowCount()
        self.viewer.counter.setText(f"{self.gallery.currentIndex().row() + 1} / {count}")
        self.viewer.reasons.setText(self.reasons.text())
        row = self.current_photo
        readable = bool(row) and "error" not in row["data"]
        self.viewer.show_decision(selection_status(row["data"]) if row else None, readable and self.editable())
        self.viewer.display(self.pixmap, self.preview.text())

    def eventFilter(self, widget, event):
        if widget is getattr(self, "preview", None) and event.type() == QEvent.Type.Resize:
            self.scale_preview()
        return super().eventFilter(widget, event)

    def show_help(self):
        if help_ui.show_help(self):
            self.open_profiles()

    def show_guide(self):
        if help_ui.guide(self):
            self.open_profiles()

    def open_profiles(self):
        self.profile_dialog.exec()

    def learn_from_profiles(self):
        self.profile_dialog.accept()
        self.learn_reportage()

    def first_launch(self):
        if not self.settings.value("tutorial_seen", False, type=bool):
            self.show_guide()
            self.settings.setValue("tutorial_seen", True)

    def profile(self):
        return self.profiles.currentData()

    def busy(self):
        return self.process is not None

    def error(self, exc):
        QMessageBox.warning(self, APP_NAME, str(exc))

    def reload_profiles(self, selected=None):
        selected = selected or self.profile()
        self.profiles.blockSignals(True)
        self.profile_picker.blockSignals(True)
        self.profiles.clear()
        for row in self.store.profiles():
            self.profiles.addItem(row["name"], row["id"])
        index = self.profiles.findData(selected)
        self.profiles.setCurrentIndex(max(0, index))
        self.profile_picker.setCurrentIndex(self.profiles.currentIndex())
        self.profiles.blockSignals(False)
        self.profile_picker.blockSignals(False)
        self.profile_changed()

    def profile_changed(self):
        self.settings.setValue("active_profile", self.profile() or "")
        self.profile_caption.setText(self.profiles.currentText() or "Votre premier profil")
        self.rename_button.setEnabled(bool(self.profile()) and not self.busy())
        self.delete_button.setEnabled(bool(self.profile()) and not self.busy())
        self.batches.clear()
        self.current_batch = None
        self.batch_title.setText("Votre premier lot")
        self.batch_meta.setText("Préparez votre profil et ses exemples à gauche, puis importez un lot.")
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
            self.profile_info.setText("Un profil mémorise votre sélection, vos références et vos corrections de tri.")
            self.profile_summary.setText("Créez un profil, puis ajoutez vos exemples.")
            self.clear_feedback_button.setEnabled(False)
        count = len(self.store.unfinished_jobs(self.profile())) if self.profile() else 0
        self.resume_button.setText(f"Gérer les tâches ({count})")
        self.recovery_button.setEnabled(bool(self.profile()) and not self.busy())

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
            text = f"Appris sur {learned['reportages']} reportage(s) : {learned['photos']} photos, {learned['kept']} retenues"
        else:
            text = "Sélection par défaut"
        text += f"\n{count} corrections mémorisées"
        text += f"\n{references} référence(s) actives"
        self.profile_info.setText(text)
        self.profile_summary.setText(
            f"{learned['reportages'] if learned else 0} reportage(s) appris\n"
            f"{references} référence(s) actives · {count} corrections")

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
        answer = QMessageBox.question(self, "Supprimer le lot", f"Supprimer « {self.batch_title.text()} », ses aperçus et ses tâches associées ?\n\nLes photos d’origine, les exports et les corrections déjà apprises par le profil seront conservés. Le tri de ce lot sera retiré.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
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
        message = ("Supprimer ce profil, ses choix appris et le travail de tri associé dans l’application ?\n\n"
                   "Les photos sur votre disque, y compris celles déjà exportées, seront conservées.")
        result = QMessageBox.question(self, "Supprimer le profil", message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if result == QMessageBox.StandardButton.Yes:
            try:
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
        dialog.setWindowTitle(f"Reportages et références · {self.profiles.currentText()}")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.launch(training_update_job(self.store, self.profile(), dialog.reportages(), dialog.reference_groups()))
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            self.error(exc)

    def prepare_import(self, paths=None):
        if self.busy():
            return
        dialog = PrepareImport(self, self.store.profiles(), self.profile(),
                               self.selectivity.value(), dropped=bool(paths))
        result = dialog.exec()
        source = dialog.source
        profile, selectivity = dialog.profiles.currentData(), dialog.slider.value()
        dialog.deleteLater()
        if result != QDialog.DialogCode.Accepted:
            return
        if source == "folder":
            folder = QFileDialog.getExistingDirectory(self, "Importer un dossier")
            paths = [folder] if folder else []
        elif source == "files":
            paths = self.select_files("Importer des photos")
        if not paths:
            return
        self.start_analysis(paths, profile, selectivity)

    def start_analysis(self, paths, profile, selectivity):
        try:
            files = discover(paths)
            if not files:
                raise ValueError("Aucune photo compatible trouvée.")
            if profile is None:
                profile = self.store.create_profile("Mon premier profil")
            identifier = analysis_job(self.store, profile, files, selectivity / 100)
            if profile != self.profile():
                self.reload_profiles(profile)
            self.launch(identifier)
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
        self.variant_groups = {}
        for row in self.rows:
            if row["data"].get("group"):
                self.variant_groups.setdefault(row["data"]["group"], []).append(row)
        self.group_picker.clear()
        self.group_picker.addItem(f"Lot entier · Groupes de variantes ({len(self.variant_groups)})" if self.variant_groups else "Aucune variante détectée")
        for n, (group, members) in enumerate(self.variant_groups.items(), 1):
            self.group_picker.addItem(f"Groupe {n} · {len(members)} photos · {Path(members[0]['path']).name}", group)
        self.group_picker.setEnabled(bool(self.variant_groups))
        self.analysis_incomplete = bool(self.current_batch and self.store.rows(
            "SELECT id FROM jobs WHERE batch=? AND kind='analysis' AND state NOT IN ('done','superseded')",
            (self.current_batch,)))
        # Includes interrupted batches created before pending states were shown.
        for row in self.rows:
            data = row["data"]
            if self.analysis_incomplete and "error" not in data and "score" not in data:
                data["selection_pending"] = True
        if batch:
            self.selectivity.blockSignals(True)
            self.selectivity.setValue(round(batch["selectivity"] * 100))
            self.selectivity.blockSignals(False)
        self.batch_title.setText(batch["name"] if batch else "Votre premier lot")
        self.batch_meta.setText(f"Profil · {self.profiles.currentText()}     Sélectivité · {strength(self.selectivity.value())}"
                                if batch else "Préparez votre profil et ses exemples à gauche, puis importez un lot.")
        self.apply_filter()
        self.update_export_control()

    def apply_filter(self, _index=None, *, photo_id=None):
        photo_id = photo_id or (self.current_photo["id"] if self.current_photo else None)
        self.current_photo = None
        self.pixmap = None
        self.preview.clear()
        self.preview.setText("Importer un lot pour commencer." if not self.current_batch else "Aucune photo dans cette vue.")
        self.preview_stack.setCurrentIndex(0 if self.current_batch else 1)
        self.photo_controls.setVisible(bool(self.current_batch))
        self.photo_title.clear()
        self.reasons.clear()
        self.large_button.setEnabled(False)
        self.variants_button.setVisible(not self.group_filter)
        self.variants_button.setEnabled(False)
        self.prefer_button.setVisible(bool(self.group_filter))
        self.prefer_button.setEnabled(False)
        self.all_button.setVisible(bool(self.group_filter))
        self.options_button.setEnabled(bool(self.current_batch))
        self.delete_batch_button.setEnabled(bool(self.current_batch) and not self.busy())
        self.export_button.setEnabled(bool(self.current_batch) and not self.busy())
        for b in self.decision_buttons:
            b.setEnabled(False)
            b.setChecked(False)
        status = FILTERS[self.filter.currentIndex()][1]
        scoped = [r for r in self.rows if not self.group_filter or r["data"].get("group") == self.group_filter]
        scoped_counts = {s: sum(selection_status(r["data"]) == s for r in scoped) for s in LABELS}
        blocked = self.filter.blockSignals(True)
        for i, (title, value) in enumerate(FILTERS):
            count = len(scoped) if value is None else scoped_counts[value]
            self.filter.setItemText(i, f"{title} ({count})")
            self.filter.view().setRowHidden(i, value == "error" and count == 0 and status != "error")
        self.filter.blockSignals(blocked)
        rows = [r for r in scoped if not status or selection_status(r["data"]) == status]
        for arrow in (self.prev_button, self.next_button):
            arrow.setEnabled(len(rows) > 1)
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
        self.summary.setVisible(bool(self.current_batch))
        self.update_selection_scope()
        self.update_viewer()

    def selected_rows(self):
        return [self.model.rows[i.row()] for i in self.gallery.selectionModel().selectedIndexes()]

    def update_selection_scope(self, *_):
        count = len(self.selected_rows())
        self.selection_scope.setText(
            f"{count} photos sélectionnées · Décision commune" if count > 1 else
            "1 photo sélectionnée · Ctrl / Cmd + clic pour en choisir plusieurs" if count else "")
        self.selection_scope.setVisible(bool(count))

    def editable(self):
        return bool(self.current_batch and not self.busy() and self.store.batch_ready(self.current_batch))

    def photo_changed(self, index, previous=None):
        self.gallery.pending_scroll = QPersistentModelIndex()
        if not index.isValid():
            return
        self.current_photo = self.model.rows[index.row()]
        d = self.current_photo["data"]
        readable = "error" not in d
        editable = readable and self.editable()
        self.large_button.setEnabled(readable)
        self.variants_button.setEnabled(bool(d.get("group")))
        self.prefer_button.setEnabled(editable and bool(self.group_filter))
        for status, b in zip(("keep", "review", "reject"), self.decision_buttons, strict=True):
            b.setEnabled(editable)
            b.setChecked(status == selection_status(d))
        self.photo_title.setText(Path(self.current_photo["path"]).name)
        self.reasons.setText(d.get("error") or " · ".join(d.get("reasons", [])))
        self.pixmap = None
        self.preview.clear()
        if readable:
            # The analysis copy (1 280 px at most) is the preview: nothing to render.
            path = self.store.private_dir(self.profile(), "batches", self.current_batch) / f"{self.current_photo['id']}.png"
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                self.preview.setText("Aperçu introuvable : réimportez cette photo.")
            else:
                self.pixmap = pixmap
        else:
            self.preview.setText("Impossible de lire cette photo.")
        self.scale_preview()
        self.update_viewer()

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
        # In the enlarged view, deciding moves on to the next frame, as on a light table
        # (unless the photo already left the current view, which then shows the next one).
        if (len(rows) == 1 and self.viewer is not None and self.current_photo
                and self.current_photo["id"] == rows[0]["id"]):
            self.move_photo(1)

    def show_variants(self):
        if self.current_photo and self.current_photo["data"].get("group"):
            self.pick_group(self.group_picker.findData(self.current_photo["data"]["group"]))

    def pick_group(self, index):
        group = self.group_picker.itemData(index)
        if not group:
            self.clear_group()
            return
        if self.group_filter is None:
            self.variants_origin = self.current_photo["id"] if self.current_photo else None
        self.group_filter = group
        self.group_picker.setCurrentIndex(index)
        self.filter.blockSignals(True)
        self.filter.setCurrentIndex(0)
        self.filter.blockSignals(False)
        self.apply_filter()

    def prefer_variant(self):
        if not self.editable() or not self.current_photo or not self.group_filter:
            return
        changes = []
        for row in self.variant_groups[self.group_filter]:
            status = "keep" if row["id"] == self.current_photo["id"] else "reject"
            changes.append(dict(row, data=dict(row["data"], decision=status, manual_decision=True, validated=False)))
        try:
            self.store.save_photos(changes)
        except sqlite3.Error as exc:
            self.error(exc)
            return
        for row, change in zip(self.variant_groups[self.group_filter], changes, strict=True):
            row["data"] = change["data"]
        self.apply_filter()

    def clear_group(self):
        photo_id = self.variants_origin
        self.group_filter = None
        self.variants_origin = None
        self.group_picker.setCurrentIndex(0)
        self.filter.blockSignals(True)
        self.filter.setCurrentIndex(0)
        self.filter.blockSignals(False)
        self.apply_filter(photo_id=photo_id)

    def return_to_selected_batch(self, item):
        if self.group_filter and item.data(Qt.ItemDataRole.UserRole) == self.current_batch:
            self.clear_group()

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
        return True

    def export(self):
        if not self.current_batch or self.busy():
            return
        if not self.editable():
            self.error("Terminez l’analyse du lot avant l’export.")
            return
        kept = sum(r["data"]["decision"] == "keep" and "error" not in r["data"] for r in self.rows)
        if not kept:
            self.error("Retenez au moins une photo avant d’exporter.")
            return
        unvalidated = any(not r["data"].get("validated") for r in self.rows if "error" not in r["data"])
        dialog, layout = self.tool_dialog("Exporter les photos retenues")
        layout.addWidget(label(f"{kept} photo(s) retenue(s) · {self.batch_title.text()}", "heading"))
        layout.addWidget(label("Les fichiers retenus sont copiés à l’identique, avec leurs XMP voisins, "
                               "sous leur nom d’origine. Aucun fichier existant n’est écrasé ; "
                               "les photos à vérifier et écartées ne sont pas copiées.", "muted"))
        layout.addWidget(label("Dossier de destination"))
        destination = QLineEdit()
        destination.setReadOnly(True)
        destination.setPlaceholderText("Choisir un dossier…")
        folder_row = QHBoxLayout()
        folder_row.addWidget(destination, 1)
        layout.addLayout(folder_row)
        confirm = QPushButton("Valider le lot et exporter" if unvalidated else "Exporter")
        confirm.setObjectName("primary")
        confirm.setEnabled(False)

        def browse():
            path = QFileDialog.getExistingDirectory(dialog, "Dossier de destination", destination.text())
            if path:
                destination.setText(path)
                confirm.setEnabled(True)

        folder_row.addWidget(button("Parcourir…", browse))
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        controls.rejected.connect(dialog.reject)
        controls.addButton(confirm, QDialogButtonBox.ButtonRole.AcceptRole)
        controls.accepted.connect(dialog.accept)
        layout.addWidget(controls)
        dialog.resize(540, dialog.sizeHint().height())
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if accepted and (not unvalidated or self.validate_batch()):
            try:
                self.launch(export_job(self.store, self.current_batch, destination.text()))
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                self.error(exc)
        dialog.deleteLater()

    def describe_load(self):
        key = self.load_picker.currentData()
        plan = performance.plan(key)
        note = performance.priority_note()
        self.load_picker.setToolTip(f"{performance.DESCRIPTIONS[key]}\nSur cet ordinateur : {plan.summary()}.\n"
                                    "Modifiable pendant une importation : appliqué dès la photo suivante."
                                    + (f"\n{note}" if note else ""))

    def load_changed(self, index):
        self.settings.setValue("performance/load", self.load_picker.itemData(index))
        self.describe_load()
        if self.load_value is not None:
            self.load_value.value = index

    def launch(self, identifier):
        if self.busy():
            return
        self.active_job = identifier
        self.events = self.context.Queue()
        self.cancel_event = self.context.Event()
        # Shared with the task: the user may lower or raise the load while it runs.
        self.load_value = self.context.Value("i", self.load_picker.currentIndex(), lock=False)
        self.process = self.context.Process(target=run_job, args=(str(self.store.root), identifier, self.events, self.cancel_event),
                                            kwargs={"load": self.load_value})
        self.process.start()
        for widget in self.mutators:
            widget.setEnabled(False)
        self.gallery.setAcceptDrops(False)
        self.gallery.viewport().setAcceptDrops(False)
        self.update_export_control()
        job = self.store.job(identifier)
        if job["kind"] in ("analysis", "training", "export"):
            self.profile_dialog.accept()
            self.tasks_dialog.accept()
            target = "du lot" if job["kind"] == "analysis" else "du profil"
            message = "Export en cours" if job["kind"] == "export" else f"Importation {target} en cours"
            self.import_notice.setText(f"{message}\nSuivez sa progression en bas de la fenêtre.")
            self.import_notice.adjustSize()
            self.position_import_notice()
            self.import_notice.show()
            self.import_notice.raise_()
            self.notice_timer.start()
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

    def recover_photos(self):
        if not self.profile() or self.busy():
            return
        entries = self.store.quarantined(self.profile())
        if not entries:
            QMessageBox.information(self, APP_NAME, "Aucune photo mise à l’écart dans ce profil.")
            return
        dialog = RecoveryDialog(entries, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        destination = QFileDialog.getExistingDirectory(self, "Enregistrer les copies récupérées dans…")
        if destination:
            try:
                self.launch(recovery_job(self.store, self.profile(), dialog.paths(), destination))
            except (OSError, ValueError, sqlite3.Error) as exc:
                self.error(exc)

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
                    self.store.delete_job(job["id"], self.profile())
                    self.profile_changed()
                    self.select_batch(selected_batch)
                    self.update_export_control()
                    self.progress_label.setText("Tâche supprimée.")
                except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                    self.error(exc)
            jobs = self.store.unfinished_jobs(self.profile())

    def select_batch(self, batch):
        for i in range(self.batches.count()):
            if self.batches.item(i).data(Qt.ItemDataRole.UserRole) == batch:
                self.batches.setCurrentRow(i)
                return

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
                self.import_notice.hide()
                self.notice_timer.stop()
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
                self.cancel_button.setEnabled(False)
                self.progress.setRange(0, 100)
                self.progress.setValue(100 if job["state"] == "done" else 0)
                self.progress_label.setText({"done": "Traitement terminé", "paused": "Tâche suspendue · reprise disponible", "failed": "Traitement interrompu · reprise disponible"}.get(job["state"], job["state"]))
                selected_batch = job["payload"]["batch"] if job["kind"] == "selection" else self.current_batch
                self.reload_profiles()
                if job["kind"] in ("export", "selection", "recovery"):
                    self.select_batch(selected_batch)
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
                               f" ({summary.get('reportages')} reportage(s)).")
                    if not summary.get("reportages"):
                        message = "Exemples mis à jour · Sélection par défaut."
                    # Only worth saying when references (photos without their rush) were used.
                    if summary.get("reference_groups"):
                        count = summary["reference_groups"]
                        message += (f" {count} groupe{'s' if count > 1 else ''} de références (photos sans rush) "
                                    "utilisé" + ("s" if count > 1 else "") + " pour les prochains imports.")
                    self.progress_label.setText(message)
                    if job["payload"].get("warnings"):
                        QMessageBox.information(self, APP_NAME, message + "\n\n" + "\n".join(job["payload"]["warnings"]))
                elif job["kind"] == "export" and job["state"] == "done":
                    count = len(job["payload"]["outputs"])
                    self.progress_label.setText(f"{count} photos copiées dans {job['payload']['destination']}")
                elif job["kind"] == "recovery" and job["state"] == "done":
                    successes = len(job["payload"]["outputs"])
                    total = len(job["payload"]["paths"])
                    self.progress_label.setText(f"Récupération terminée · {successes}/{total} copie(s) enregistrée(s) "
                                                f"dans {job['payload']['destination']}")
                elif job["kind"] == "selection" and job["state"] == "done":
                    self.progress_label.setText("Tri mis à jour · Choix manuels conservés · Validez à nouveau le lot avant l’export.")
                self.events.close()
                self.active_job = None

    def scale_preview(self):
        if self.pixmap:
            self.preview.setPixmap(self.pixmap.scaled(self.preview.size() - QSize(16, 16), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.update_viewer()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "preview"):
            self.scale_preview()
        if hasattr(self, "import_notice"):
            self.position_import_notice()

    def position_import_notice(self):
        self.import_notice.move((self.centralWidget().width() - self.import_notice.width()) // 2, 14)

    def closeEvent(self, event):
        if self.busy():
            self.cancel_job()
            self.progress_label.setText("Suspension en cours. Fermez la fenêtre une fois le traitement suspendu.")
            event.ignore()
            return
        self.timer.stop()
        for i, action in enumerate(self.panel_actions):
            self.settings.setValue(f"panels/{i}/width", self.layout_sizes[i])
            self.settings.setValue(f"panels/{i}/visible", action.isChecked())
        self.settings.sync()
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
    QTimer.singleShot(0, window.first_launch)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
