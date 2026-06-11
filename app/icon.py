from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap

from .settings import resource_path

_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def app_icon() -> QIcon:
    """Build the application icon from the SVG logo.

    Renders the vector logo into several raster sizes so it stays crisp in the
    window corner, the taskbar and the system tray. Falls back to the bundled
    .ico and finally to an empty icon if anything is unavailable.
    """
    svg_path = resource_path("assets", "logo.svg")
    if svg_path.exists():
        icon = _icon_from_svg(svg_path.read_bytes())
        if not icon.isNull():
            return icon

    ico_path = resource_path("assets", "app.ico")
    if ico_path.exists():
        return QIcon(str(ico_path))

    return QIcon()


def _icon_from_svg(svg_bytes: bytes) -> QIcon:
    try:
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        # No SVG module: let QIcon try to load the file format directly.
        return QIcon()

    renderer = QSvgRenderer(svg_bytes)
    if not renderer.isValid():
        return QIcon()

    icon = QIcon()
    for size in _ICON_SIZES:
        image = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(QPixmap.fromImage(image))
    return icon
