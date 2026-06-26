"""Rich Markdown editor backed by @gravity-ui/markdown-editor.

The editor itself is a React app built under ``frontend/`` into a single
self-contained ``app/assets/editor/index.html``. This module embeds that page
in a ``QWebEngineView`` and bridges it to Python over ``QWebChannel`` so the
host window can load a document, receive edits and save — exposing the same
small interface as the plain-text :class:`~app.editor.MarkdownEditor`, so the
window can use either interchangeably.

When the built bundle is absent (e.g. a source checkout without a frontend
build) :func:`web_editor_available` returns ``False`` and the window falls back
to the plain-text editor.
"""

from __future__ import annotations

from PySide6.QtCore import QFile, QIODevice, QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .settings import resource_path


def editor_index_path():
    return resource_path("assets", "editor", "index.html")


def web_editor_available() -> bool:
    return editor_index_path().exists()


def _qwebchannel_js() -> str:
    """The qwebchannel.js client shipped inside Qt, read from its resource."""
    file = QFile(":/qtwebchannel/qwebchannel.js")
    if not file.open(QIODevice.OpenModeFlag.ReadOnly):
        return ""
    try:
        return bytes(file.readAll().data()).decode("utf-8")
    finally:
        file.close()


class EditorBridge(QObject):
    """QWebChannel endpoint. Signals go Python -> JS; slots are called by JS."""

    # Python -> JS
    contentSet = Signal(str, str)  # (markup, theme)  # noqa: N815 - JS-facing name
    themeChanged = Signal(str)  # noqa: N815 - JS-facing name

    # Internal (JS slot -> host widget) signals
    js_ready = Signal()
    js_content_changed = Signal(str)
    js_save = Signal(str)
    js_cancel = Signal()

    @Slot()
    def ready(self) -> None:
        self.js_ready.emit()

    @Slot(str)
    def onContentChanged(self, markup: str) -> None:  # noqa: N802 - JS-facing name
        self.js_content_changed.emit(markup)

    @Slot(str)
    def onSave(self, markup: str) -> None:  # noqa: N802 - JS-facing name
        self.js_save.emit(markup)

    @Slot()
    def onCancel(self) -> None:  # noqa: N802 - JS-facing name
        self.js_cancel.emit()


class WebMarkdownEditor(QWidget):
    """Drop-in replacement for :class:`~app.editor.MarkdownEditor` driving the
    gravity-ui editor through a web view."""

    save_requested = Signal()
    cancel_requested = Signal()
    content_changed = Signal()

    def __init__(self, parent: QWidget | None = None, dark: bool = False) -> None:
        super().__init__(parent)
        self._markup = ""
        self._loaded_markup = ""
        self._dark = dark
        self._ready = False
        self._pending: tuple[str, str] | None = None

        self.view = QWebEngineView(self)
        self.page = QWebEnginePage(self.view)
        self.view.setPage(self.page)

        self.bridge = EditorBridge(self)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject("bridge", self.bridge)
        self.page.setWebChannel(self.channel)
        self._inject_qwebchannel()

        self.bridge.js_ready.connect(self._on_ready)
        self.bridge.js_content_changed.connect(self._on_content_changed)
        self.bridge.js_save.connect(self._on_save)
        self.bridge.js_cancel.connect(self.cancel_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self.view.load(QUrl.fromLocalFile(str(editor_index_path())))

    def _inject_qwebchannel(self) -> None:
        source = _qwebchannel_js()
        if not source:
            return
        script = QWebEngineScript()
        script.setName("qwebchannel")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(source)
        self.page.scripts().insert(script)

    # -------------------------------------------------- bridge -> host widget

    def _on_ready(self) -> None:
        self._ready = True
        if self._pending is not None:
            self.bridge.contentSet.emit(*self._pending)
            self._pending = None

    def _on_content_changed(self, markup: str) -> None:
        self._markup = markup
        self.content_changed.emit()

    def _on_save(self, markup: str) -> None:
        self._markup = markup
        self.save_requested.emit()

    # --------------------------------------------- MarkdownEditor-like surface

    def load(self, text: str, label: str = "") -> None:
        self._loaded_markup = text
        self._markup = text
        payload = (text, "dark" if self._dark else "light")
        if self._ready:
            self.bridge.contentSet.emit(*payload)
        else:
            self._pending = payload

    def text(self) -> str:
        return self._markup

    def is_modified(self) -> bool:
        return self._markup != self._loaded_markup

    def mark_saved(self) -> None:
        self._loaded_markup = self._markup

    def focus_editor(self) -> None:
        self.view.setFocus()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self.bridge.themeChanged.emit("dark" if dark else "light")
