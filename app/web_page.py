from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage

from .settings import SUPPORTED_EXTENSIONS


class MarkdownWebPage(QWebEnginePage):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.current_markdown_path: Path | None = None
        self.open_markdown_callback = None
        self.missing_file_callback = None

    def acceptNavigationRequest(self, url: QUrl, navigation_type: QWebEnginePage.NavigationType, is_main_frame: bool) -> bool:
        if navigation_type != QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            return True

        if url.hasFragment() and not url.path():
            return True

        if url.scheme() in {"http", "https"}:
            QDesktopServices.openUrl(url)
            return False

        if url.scheme() == "file":
            target = Path(unquote(url.toLocalFile())).resolve()
            if target.suffix.lower() in SUPPORTED_EXTENSIONS:
                if target.exists():
                    if self.open_markdown_callback:
                        self.open_markdown_callback(target)
                    return False

                if self.missing_file_callback:
                    self.missing_file_callback(target)
                return False

            QDesktopServices.openUrl(url)
            return False

        if self.current_markdown_path and url.isRelative():
            target = (self.current_markdown_path.parent / unquote(url.toString())).resolve()
            if target.suffix.lower() in SUPPORTED_EXTENSIONS:
                if target.exists():
                    if self.open_markdown_callback:
                        self.open_markdown_callback(target)
                    return False
                if self.missing_file_callback:
                    self.missing_file_callback(target)
                return False

        QDesktopServices.openUrl(url)
        return False
