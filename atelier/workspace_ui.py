"""Presentation widgets for the desktop workspace."""
from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
)

PALETTES = {
    # workspace, surface, text, secondary text, divider, selection, accent, on accent
    "Atelier": ("#f7f6f2", "#fffefa", "#232a27", "#56615b", "#cbd1c9", "#dfebe2", "#245746", "#ffffff"),
    "Sable": ("#f3e9db", "#fff8ef", "#35291f", "#69584a", "#d6c4ae", "#f2dcca", "#864323", "#fff8ef"),
    "Brume": ("#e9eff2", "#f6fafb", "#1f3340", "#4b6270", "#bdcdd4", "#d9e8f1", "#315e79", "#f7fbfc"),
    "Nuit": ("#191a1d", "#242529", "#e4e3e6", "#b4b1ba", "#46454c", "#39333f", "#c2b5d6", "#25212c"),
    "Nuit boréale": ("#111c23", "#1b2a33", "#e3eff0", "#aec4c9", "#445c68", "#26454c", "#8bd9cb", "#112d2a"),
    "Nuit ambrée": ("#201a18", "#2c2522", "#f1e8df", "#cdbbb0", "#665249", "#49372b", "#edba7e", "#362518"),
}


def stylesheet(name):
    paper, surface, ink, muted, line, selected, accent, on_accent = PALETTES[name]
    return f"""
    QWidget {{ color: {ink}; font-family: 'Segoe UI'; font-size: 13px; }}
    QMainWindow, QDialog, QWidget#workspace, QTabWidget::pane {{ background: {paper}; }}
    QWidget#pane, QWidget#canvas, QMenu, QComboBox QAbstractItemView {{ background: {surface}; }}
    QLabel#heading {{ font-family: Georgia; font-size: 21px; }}
    QLabel#brand {{ font-size: 19px; font-weight: 600; }}
    QLabel#muted {{ color: {muted}; }}
    QLabel#preview {{ background: #1b201e; color: #eceeeb; border-radius: 5px; }}
    QLabel#drop {{ border: 1px dashed {line}; color: {muted}; padding: 10px; border-radius: 6px; }}
    QLabel#guideTitle {{ font-family: Georgia; font-size: 28px; }}
    QLabel#eyebrow {{ color: {accent}; font-weight: 600; font-size: 12px; }}
    QLabel#cardTitle {{ font-size: 16px; font-weight: 600; }}
    QLabel#flowArrow {{ color: {accent}; font-size: 23px; }}
    QFrame#guideCard {{ background: {surface}; border: 1px solid {line}; border-radius: 10px; }}
    QLabel#guideTip {{ background: {selected}; padding: 14px; border-radius: 8px; }}
    QWidget#welcome {{ background: {paper}; border-radius: 8px; }}
    QLineEdit {{ padding: 5px 7px; }}
    QLabel#importNotice {{ background: {accent}; color: {on_accent}; padding: 10px 18px; border-radius: 6px; }}
    QPushButton, QComboBox, QToolButton, QTabBar::tab {{ background: {surface}; color: {ink};
        padding: 6px 9px; border: 1px solid {line}; border-radius: 5px; }}
    QPushButton:hover, QToolButton:hover, QTabBar::tab:selected {{ background: {selected}; }}
    QPushButton:checked {{ background: {selected}; border-color: {accent}; }}
    QPushButton:focus, QComboBox:focus, QToolButton:focus {{ border-color: {accent}; }}
    QPushButton#primary {{ background: {accent}; color: {on_accent}; border-color: {accent}; }}
    QPushButton:disabled, QPushButton#primary:disabled {{ color: {muted}; background: {paper}; border-color: {line}; }}
    QListView, QTextBrowser, QLineEdit, QTableView, QTreeView {{ background: {surface}; color: {ink};
        border: 1px solid {line}; border-radius: 5px; selection-background-color: {selected}; selection-color: {ink}; }}
    QListView::item {{ padding: 5px; }} QListView::item:selected {{ background: {selected}; color: {ink}; }}
    QMenu::item:selected {{ background: {selected}; color: {ink}; }}
    QToolTip {{ background: {surface}; color: {ink}; border: 1px solid {line}; padding: 4px; }}
    QSlider::groove:horizontal, QProgressBar {{ background: {line}; border: 0; border-radius: 2px; height: 4px; }}
    QSlider::handle:horizontal {{ background: {accent}; width: 14px; margin: -5px 0; border-radius: 7px; }}
    QProgressBar::chunk {{ background: {accent}; }} QSplitter::handle {{ background: {line}; }}
    """


def strength(value):
    name = "Souple" if value < 35 else "Stricte" if value > 65 else "Équilibrée"
    return f"{name} · {value}/100"


class PrepareImport(QDialog):
    """Keep proposed settings local until the user confirms a source."""

    def __init__(self, parent, profiles, current, value, dropped=False):
        super().__init__(parent)
        self.setWindowTitle("Préparer le lot")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        hint = QLabel("Choisissez le profil et la sélectivité avant d’importer les photos.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.profiles = QComboBox()
        for row in profiles:
            self.profiles.addItem(row["name"], row["id"])
        if not profiles:
            self.profiles.addItem("Mon premier profil", None)
        self.profiles.setCurrentIndex(max(0, self.profiles.findData(current)))
        caption = QLabel("Profil de tri")
        caption.setBuddy(self.profiles)
        layout.addWidget(caption)
        layout.addWidget(self.profiles)
        profile_hint = QLabel("Les reportages et références se préparent dans la colonne de gauche, avant l’import. "
                              "Sans apprentissage, ce profil utilise les réglages fournis.")
        profile_hint.setWordWrap(True)
        profile_hint.setObjectName("muted")
        layout.addWidget(profile_hint)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(value)
        self.slider.setAccessibleName("Sélectivité du nouveau lot")
        caption = QLabel("Sélectivité · " + strength(value))
        self.slider.valueChanged.connect(lambda n: caption.setText("Sélectivité · " + strength(n)))
        layout.addWidget(caption)
        layout.addWidget(self.slider)
        ends = QHBoxLayout()
        ends.addWidget(QLabel("Garder davantage"))
        ends.addStretch()
        ends.addWidget(QLabel("Garder moins"))
        layout.addLayout(ends)
        self.source = None
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        controls.rejected.connect(self.reject)
        choices = [("Importer le dépôt", "drop")] if dropped else [("Choisir un dossier…", "folder"), ("Choisir des photos…", "files")]
        for title, source in choices:
            b = controls.addButton(title, QDialogButtonBox.ButtonRole.ActionRole)
            b.clicked.connect(lambda checked=False, s=source: self.choose(s))
        layout.addWidget(controls)

    def choose(self, source):
        self.source = source
        self.accept()


class PreviewLabel(QLabel):
    activated = Signal()

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setObjectName("preview")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setWordWrap(True)
        self.setToolTip("Agrandir la photo")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
        super().mouseReleaseEvent(event)


class PhotoViewer(QDialog):
    """Enlarged view to compare frames and decide; the decision keys stay active."""
    navigate = Signal(int)
    decided = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.source = None
        self.area = QScrollArea()
        self.area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.area.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: #1b201e; border: 0; }")
        self.photo = QLabel()
        self.photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photo.setObjectName("preview")
        self.area.setWidget(self.photo)
        layout = QVBoxLayout(self)
        layout.addWidget(self.area, 1)
        self.reasons = QLabel()
        self.reasons.setObjectName("muted")
        self.reasons.setWordWrap(True)
        layout.addWidget(self.reasons)
        bar = QHBoxLayout()
        self.previous = QPushButton("← Précédente")
        self.next_photo = QPushButton("Suivante →")
        self.previous.clicked.connect(lambda: self.navigate.emit(-1))
        self.next_photo.clicked.connect(lambda: self.navigate.emit(1))
        self.zoom = QCheckBox("Zoom ×2")
        self.zoom.toggled.connect(self.fit)
        self.decisions = []
        for key, (title, status) in enumerate((("Retenir", "keep"), ("À vérifier", "review"), ("Écarter", "reject")), 1):
            choice = QPushButton(f"{title} · {key}")
            choice.setCheckable(True)
            choice.clicked.connect(lambda checked=False, s=status: self.decided.emit(s))
            self.decisions.append(choice)
        done = QPushButton("Fermer")
        done.clicked.connect(self.reject)
        self.counter = QLabel()
        for w in (self.previous, self.counter, self.next_photo):
            bar.addWidget(w)
        bar.addStretch()
        for w in self.decisions:
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.zoom)
        bar.addWidget(done)
        layout.addLayout(bar)
        self.area.viewport().installEventFilter(self)

    def show_decision(self, status, enabled):
        for value, choice in zip(("keep", "review", "reject"), self.decisions, strict=True):
            choice.setChecked(value == status)
            choice.setEnabled(enabled)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.navigate.emit(-1 if event.key() == Qt.Key.Key_Left else 1)
            return
        keys = {Qt.Key.Key_1: "keep", Qt.Key.Key_2: "review", Qt.Key.Key_3: "reject"}
        if event.key() in keys and self.decisions[0].isEnabled():
            self.decided.emit(keys[event.key()])
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if obj == self.area.viewport() and event.type() == QEvent.Type.Resize:
            self.fit()
        return super().eventFilter(obj, event)

    def display(self, pixmap, message=""):
        self.source = pixmap
        if not pixmap:
            self.photo.clear()
            self.photo.setText(message)
        self.fit()

    def fit(self):
        if not self.source:
            self.photo.resize(self.area.viewport().size())
            return
        # The unzoomed viewport excludes the frame but is independent of scrollbar visibility.
        size = self.area.maximumViewportSize().expandedTo(QSize(1, 1))
        target = self.source.size().scaled(size, Qt.AspectRatioMode.KeepAspectRatio)
        if self.zoom.isChecked():
            target *= 2
        self.photo.resize(target)
        self.photo.setPixmap(self.source.scaled(target, Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))
