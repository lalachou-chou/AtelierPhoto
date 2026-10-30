"""Render the original SVG into application icons (no extra dependencies)."""
import io
import os
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parents[1] / "atelier" / "assets"


def render_icon(size):
    renderer = QSvgRenderer(str(ASSETS / "app-icon.svg"))
    if not renderer.isValid():
        raise ValueError("Invalid application icon SVG")
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return Image.open(io.BytesIO(bytes(data))).convert("RGBA")


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication.instance() or QGuiApplication([])
    master = render_icon(1024)
    master.save(ASSETS / "app-icon.png")
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    variants = [render_icon(size * 4).resize((size, size), Image.Resampling.LANCZOS) for size in sizes]
    variants[-1].save(ASSETS / "app-icon.ico", sizes=[(s, s) for s in sizes], append_images=variants[:-1])
    master.save(ASSETS / "app-icon.icns")
    # Keep the Qt application alive until all rendering has completed.
    app.quit()
    print("Application icons generated: PNG, ICO, ICNS")


if __name__ == "__main__":
    main()
