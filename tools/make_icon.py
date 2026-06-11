"""Regenerate app/assets/app.ico from the SVG logo.

Renders app/assets/logo.svg into raster sizes via Qt and writes a multi-size
Windows .ico used as the PyInstaller exe / taskbar icon.

Usage:
    python tools/make_icon.py
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parent.parent / "app" / "assets"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def render_png(renderer: QSvgRenderer, size: int) -> Image.Image:
    image = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    buffer_data = QByteArray()
    buffer = QBuffer(buffer_data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(buffer_data.data()))).convert("RGBA")


def main() -> None:
    QGuiApplication([])
    svg = ASSETS / "logo.svg"
    renderer = QSvgRenderer(svg.read_bytes())
    if not renderer.isValid():
        raise SystemExit(f"Invalid SVG: {svg}")

    frames = [render_png(renderer, size) for size in SIZES]
    out = ASSETS / "app.ico"
    frames[-1].save(out, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"Wrote {out} with sizes {SIZES}")


if __name__ == "__main__":
    main()
