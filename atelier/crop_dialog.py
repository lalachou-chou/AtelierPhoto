"""Interactive framing in coordinates relative to the full, oriented photo."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QShortcut,
    QTransform,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

FULL = (0., 0., 1., 1.)
PHI = (1 + math.sqrt(5)) / 2


class CropCanvas(QWidget):
    edited = Signal(tuple)

    def __init__(self, source, crop):
        super().__init__()
        self.source = source
        self.crop = tuple(crop or FULL)
        self.guide = "Règle des tiers"
        self.anchor = None
        self.setMinimumSize(280, 180)
        self.setMouseTracking(True)
        self.setAccessibleName("Cadre de recadrage")

    def image_rect(self):
        area = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        size = QRectF(self.source.rect()).size().scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
        box = QRectF(QPointF(), size)
        box.moveCenter(area.center())
        return box

    def frame(self):
        box = self.image_rect()
        left, top, right, bottom = self.crop
        return QRectF(box.left() + left * box.width(), box.top() + top * box.height(),
                      (right - left) * box.width(), (bottom - top) * box.height())

    def set_guide(self, guide):
        self.guide = guide
        self.update()

    def guide_path(self, frame):
        path = QPainterPath()
        if self.guide == "Spirale d’or":
            # A golden logarithmic spiral grows by phi each quarter turn.
            points = []
            for step in range(321):
                angle = step * math.pi / 80
                radius = PHI ** (2 * angle / math.pi)
                points.append(QPointF(radius * math.cos(angle), radius * math.sin(angle)))
            if frame.height() > frame.width():
                points = [QPointF(-p.y(), p.x()) for p in points]
            for i, point in enumerate(points):
                (path.lineTo if i else path.moveTo)(point)
            bounds = path.boundingRect()
            scale = min(frame.width() / bounds.width(), frame.height() / bounds.height())
            transform = QTransform()
            transform.translate(frame.center().x(), frame.center().y())
            transform.scale(scale, scale)
            transform.translate(-bounds.center().x(), -bounds.center().y())
            return transform.map(path)
        lines = {"Règle des tiers": (1 / 3, 2 / 3), "Grille 4 × 4": (.25, .5, .75),
                 "Nombre d’or": (1 - 1 / PHI, 1 / PHI)}.get(self.guide, ())
        for fraction in lines:
            x = frame.left() + frame.width() * fraction
            y = frame.top() + frame.height() * fraction
            path.moveTo(x, frame.top())
            path.lineTo(x, frame.bottom())
            path.moveTo(frame.left(), y)
            path.lineTo(frame.right(), y)
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1b201e"))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        box, frame = self.image_rect(), self.frame()
        painter.drawPixmap(box, self.source, QRectF(self.source.rect()))
        shade = QPainterPath()
        shade.addRect(box)
        shade.addRect(frame)
        painter.fillPath(shade, QColor(0, 0, 0, 150))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        lines = self.guide_path(frame)
        lines.addRect(frame)
        for color, width in ((QColor(0, 0, 0, 155), 3), (QColor(255, 255, 255, 225), 1)):
            painter.setPen(QPen(color, width))
            painter.drawPath(lines)
        for point in (frame.topLeft(), frame.topRight(), frame.bottomLeft(), frame.bottomRight()):
            painter.fillRect(QRectF(point.x() - 3, point.y() - 3, 6, 6), Qt.GlobalColor.white)
        painter.end()

    def hit(self, point):
        frame = self.frame()
        for name, corner in (("tl", frame.topLeft()), ("tr", frame.topRight()),
                             ("bl", frame.bottomLeft()), ("br", frame.bottomRight())):
            if (corner - point).manhattanLength() <= 14:
                return name
        return "move" if self.crop != FULL and frame.contains(point) else "draw"

    def mousePressEvent(self, event):
        point = event.position()
        if event.button() == Qt.MouseButton.LeftButton and self.image_rect().adjusted(-4, -4, 4, 4).contains(point):
            self.anchor = point
            self.original = self.crop
            self.drag = self.hit(point)

    def mouseMoveEvent(self, event):
        point = event.position()
        if self.anchor is None:
            cursors = {"tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
                       "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
                       "move": Qt.CursorShape.SizeAllCursor}
            self.setCursor(cursors.get(self.hit(point), Qt.CursorShape.CrossCursor))
            return
        if (point - self.anchor).manhattanLength() < 3:
            return
        box = self.image_rect()
        x = max(0., min(1., (point.x() - box.left()) / box.width()))
        y = max(0., min(1., (point.y() - box.top()) / box.height()))
        left, top, right, bottom = self.original
        if self.drag == "move":
            delta = point - self.anchor
            dx = max(-left, min(1 - right, delta.x() / box.width()))
            dy = max(-top, min(1 - bottom, delta.y() / box.height()))
            crop = (left + dx, top + dy, right + dx, bottom + dy)
        else:
            if self.drag == "draw":
                ax = max(0., min(1., (self.anchor.x() - box.left()) / box.width()))
                ay = max(0., min(1., (self.anchor.y() - box.top()) / box.height()))
            else:
                ax = right if "l" in self.drag else left
                ay = bottom if "t" in self.drag else top
            crop = min(x, ax), min(y, ay), max(x, ax), max(y, ay)
        if (crop[2] - crop[0]) * box.width() >= 4 and (crop[3] - crop[1]) * box.height() >= 4:
            self.crop = crop
            self.update()

    def mouseReleaseEvent(self, event):
        if self.anchor is not None and event.button() == Qt.MouseButton.LeftButton:
            self.mouseMoveEvent(event)
            self.anchor = None
            if self.crop != self.original:
                self.edited.emit(self.original)


class CropDialog(QDialog):
    def __init__(self, parent, source, data, name):
        super().__init__(parent)
        self.setWindowTitle(f"Recadrer · {name}")
        self.resize(860, 640)
        self.history = [tuple(c) for c in data.get("crop_history", [])]
        layout = QVBoxLayout(self)
        hint = QLabel("Tracez un cadre sur la photo. Glissez un coin pour l’ajuster ou son centre pour le déplacer.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.canvas = CropCanvas(source, data.get("crop"))
        layout.addWidget(self.canvas, 1)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Repère"))
        guides = QComboBox()
        guides.setAccessibleName("Repère de composition")
        guides.addItems(["Règle des tiers", "Grille 4 × 4", "Nombre d’or", "Spirale d’or", "Aucun"])
        guides.currentTextChanged.connect(self.canvas.set_guide)
        bar.addWidget(guides)
        bar.addStretch()
        self.undo = QPushButton("Annuler le dernier cadrage")
        self.undo.clicked.connect(self.undo_crop)
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self.undo_crop)
        bar.addWidget(self.undo)
        self.reset = QPushButton("Cadre d’origine")
        self.reset.clicked.connect(self.reset_crop)
        bar.addWidget(self.reset)
        layout.addLayout(bar)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Ok).setText("Appliquer")
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)
        self.canvas.edited.connect(self.remember)
        self.update_controls()

    def update_controls(self):
        self.undo.setEnabled(bool(self.history))
        self.reset.setEnabled(self.canvas.crop != FULL)
        self.canvas.update()

    def remember(self, previous):
        self.history.append(previous)
        self.update_controls()

    def undo_crop(self):
        if self.history:
            self.canvas.crop = self.history.pop()
            self.update_controls()

    def reset_crop(self):
        previous = self.canvas.crop
        self.canvas.crop = FULL
        self.remember(previous)
