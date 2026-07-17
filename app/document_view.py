"""A single open document: its rendered viewer plus an optional editor.

Each browser-style tab in the main window is a :class:`DocumentView`. It owns
everything that used to be per-document state on the window — the web view, the
in-page find bar, navigation history, scroll restoration and the edit/preview
machinery — and talks back to the window through signals (open a linked file,
refresh the tab label, surface status, etc.). The shared pieces (tree, menus,
file watcher, updates, theme/zoom coordination) stay on the window.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .editor import MarkdownEditor
from .import_docx import DocxImportError, docx_to_markdown
from .renderer import MarkdownRenderer, MarkdownRenderError, read_text_with_fallback
from .web_editor import WebMarkdownEditor
from .web_page import MarkdownWebPage

# QWebEngineView.setHtml() serializes the page into a `data:` URL and silently
# discards it once that URL exceeds 2 MB, leaving a blank page. The cap applies
# to the *percent-encoded* HTML, not the raw bytes, so a document well under
# 2 MB of HTML (~800 KB of Markdown and up) can still blow past it once markup
# is encoded. Anything that would exceed the cap is loaded from a temporary file
# instead (see DocumentView._display), which has no such limit.
_DATA_URL_LIMIT = 2 * 1024 * 1024
# Below this raw size the HTML fits even if every byte percent-encodes to 3
# bytes, so we can skip the exact (costlier) measurement.
_SET_HTML_SAFE_BYTES = _DATA_URL_LIMIT // 3

# Hard upper bound on the source file we will render. Bigger files parse and
# render slowly enough to freeze the UI (and produce HTML the web view struggles
# with), so we refuse them outright instead.
_MAX_FILE_BYTES = 10 * 1024 * 1024


def _fits_set_html(html: str) -> bool:
    """Whether *html* will survive QWebEngineView.setHtml(), i.e. its
    percent-encoded data URL stays under Qt's 2 MB cap."""
    raw = len(html.encode("utf-8"))
    if raw < _SET_HTML_SAFE_BYTES:
        return True
    from urllib.parse import quote

    return len(quote(html).encode("utf-8")) < _DATA_URL_LIMIT


def _cleanup_temp_files(paths: dict[int, Path]) -> None:
    for path in paths.values():
        try:
            path.unlink()
        except OSError:
            pass


def _cleanup_converted_dir(holder: dict[str, Path]) -> None:
    directory = holder.get("dir")
    if directory is not None:
        shutil.rmtree(directory, ignore_errors=True)


def _with_base_href(html: str, base_url: QUrl) -> str:
    """Inject a <base> tag so relative resources resolve against the document
    folder even when the HTML is loaded from a temp file elsewhere."""
    base_tag = f'<base href="{base_url.toString()}">'
    marker = "<head>"
    index = html.lower().find(marker)
    if index == -1:
        return base_tag + html
    cut = index + len(marker)
    return html[:cut] + base_tag + html[cut:]


class DocumentView(QWidget):
    title_changed = Signal()  # tab label/tooltip should refresh
    state_changed = Signal()  # window should re-evaluate action enabled states
    open_request = Signal(object)  # Path — a link wants another document opened
    missing_link = Signal(object)  # Path
    status_message = Signal(str, int)  # text, timeout ms
    save_as_requested = Signal()  # converted doc wants a real save location

    def __init__(
        self,
        renderer: MarkdownRenderer,
        *,
        use_web_editor: bool,
        zoom_factor: float = 1.0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.renderer = renderer
        self._use_web_editor = use_web_editor
        self._zoom_factor = zoom_factor

        self.current_file: Path | None = None
        self._history: list[Path] = []
        self._history_index = -1
        self._pending_scroll: dict[int, int] = {}
        self._temp_html: dict[int, Path] = {}
        self._suppress_watch = False
        self._editing = False
        # Set when this tab holds a .docx converted to Markdown: current_file
        # then points at a throwaway working copy under a temp dir, and
        # _converted_from keeps the original .docx path for the close prompt.
        # The temp dir lives in a mutable holder so it can be cleaned up from
        # the destroyed signal without touching the (dying) widget.
        self._converted_from: Path | None = None
        self._converted_holder: dict[str, Path] = {}
        self.destroyed.connect(partial(_cleanup_temp_files, self._temp_html))
        self.destroyed.connect(partial(_cleanup_converted_dir, self._converted_holder))

        # editor/preview are created lazily on first edit to avoid spinning up a
        # heavy web view per tab.
        self.editor: WebMarkdownEditor | MarkdownEditor | None = None
        self.preview: QWebEngineView | None = None
        self._edit_index = -1

        self.web_page = MarkdownWebPage(self)
        self.web_page.open_markdown_callback = self.open_request.emit
        self.web_page.missing_file_callback = self.missing_link.emit
        self.web_page.pdfPrintingFinished.connect(self._on_pdf_finished)

        self.viewer = QWebEngineView(self)
        self.viewer.setPage(self.web_page)
        self.viewer.setZoomFactor(zoom_factor)
        self.viewer.loadFinished.connect(partial(self._restore_scroll, self.viewer))

        self.search_panel = self._create_search_panel()
        self.search_panel.hide()

        view_page = QWidget(self)
        view_layout = QVBoxLayout(view_page)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(0)
        view_layout.addWidget(self.search_panel)
        view_layout.addWidget(self.viewer)

        self.stack = QStackedWidget(self)
        self.stack.addWidget(view_page)  # index 0 = reading view

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.stack)

    # ------------------------------------------------------------- open/show

    def open(self, path: Path, record_history: bool = True) -> bool:
        path = path.resolve()
        try:
            size = path.stat().st_size
        except OSError as exc:
            QMessageBox.warning(self, "Не удалось открыть файл", f"{path}\n\n{exc}")
            return False
        if size > _MAX_FILE_BYTES:
            QMessageBox.warning(
                self,
                "Файл слишком большой",
                f"{path}\n\nРазмер {size / 1024 / 1024:.1f} МБ превышает лимит "
                f"{_MAX_FILE_BYTES // 1024 // 1024} МБ, файл не открыт.",
            )
            return False
        try:
            rendered = self.renderer.render_file(path)
        except OSError as exc:
            QMessageBox.warning(self, "Не удалось открыть файл", f"{path}\n\n{exc}")
            return False
        except MarkdownRenderError as exc:
            QMessageBox.warning(self, "Ошибка Markdown", str(exc))
            return False

        self.current_file = path
        self.web_page.current_markdown_path = path
        self._display(self.viewer, rendered.html, path.parent)
        if record_history:
            self._record_history(path)
        self.title_changed.emit()
        self.state_changed.emit()
        return True

    def open_docx(self, source: Path) -> bool:
        """Convert a Word .docx to Markdown and open it as an editable, throwaway
        working copy. The original .docx is never written to."""
        source = source.resolve()
        try:
            size = source.stat().st_size
        except OSError as exc:
            QMessageBox.warning(self, "Не удалось открыть файл", f"{source}\n\n{exc}")
            return False
        if size > _MAX_FILE_BYTES:
            QMessageBox.warning(
                self,
                "Файл слишком большой",
                f"{source}\n\nРазмер {size / 1024 / 1024:.1f} МБ превышает лимит "
                f"{_MAX_FILE_BYTES // 1024 // 1024} МБ, файл не открыт.",
            )
            return False
        try:
            markdown_text = docx_to_markdown(source)
        except DocxImportError as exc:
            QMessageBox.warning(self, "Не удалось открыть Word-документ", str(exc))
            return False

        directory = Path(tempfile.mkdtemp(prefix="mdreader-docx-"))
        working = directory / f"{source.stem}.md"
        try:
            working.write_text(markdown_text, encoding="utf-8")
        except OSError as exc:
            shutil.rmtree(directory, ignore_errors=True)
            QMessageBox.warning(self, "Не удалось открыть Word-документ", f"{source}\n\n{exc}")
            return False

        self._converted_from = source
        self._converted_holder["dir"] = directory
        return self.open(working, record_history=False)

    def is_converted(self) -> bool:
        return self._converted_from is not None

    def converted_source(self) -> Path | None:
        return self._converted_from

    def current_markdown_text(self) -> str:
        """The document's current Markdown: the live editor buffer while editing,
        otherwise the working file on disk."""
        if self._editing and self.editor is not None:
            return self.editor.text()
        if self.current_file is not None:
            try:
                return read_text_with_fallback(self.current_file)
            except (OSError, UnicodeDecodeError):
                return ""
        return ""

    def mark_persisted(self, path: Path) -> None:
        """Adopt *path* as the document's real file: it is no longer a converted
        throwaway copy, so normal save/close semantics apply from now on."""
        self._converted_from = None
        self.current_file = path.resolve()
        self.web_page.current_markdown_path = self.current_file
        if self.editor is not None:
            self.editor.mark_saved()
        self.title_changed.emit()
        self.state_changed.emit()

    def title(self) -> str:
        if self.current_file is None:
            return "Документ"
        name = self.current_file.name
        if self._editing and self.has_unsaved():
            return f"● {name}"
        return name

    def tooltip(self) -> str:
        return str(self.current_file) if self.current_file else ""

    # -------------------------------------------------------------- refresh

    def refresh(self) -> None:
        if not self.current_file:
            return
        self.viewer.page().runJavaScript("window.scrollY", 0, self._refresh_at)

    def _refresh_at(self, scroll_y) -> None:
        if not self.current_file:
            return
        try:
            rendered = self.renderer.render_file(self.current_file)
        except (OSError, MarkdownRenderError) as exc:
            QMessageBox.warning(self, "Не удалось обновить", str(exc))
            return
        self._display(self.viewer, rendered.html, self.current_file.parent, scroll_to=int(scroll_y or 0))
        self.status_message.emit(f"Обновлено: {self.current_file.name}", 2000)

    def wants_external_reload(self) -> bool:
        return not self._editing and not self._suppress_watch

    # ----------------------------------------------------------- navigation

    def _record_history(self, path: Path) -> None:
        if self._history and self._history[self._history_index] == path:
            return
        del self._history[self._history_index + 1:]
        self._history.append(path)
        self._history_index = len(self._history) - 1
        self.state_changed.emit()

    def can_go_back(self) -> bool:
        return self._history_index > 0

    def can_go_forward(self) -> bool:
        return self._history_index < len(self._history) - 1

    def navigate_back(self) -> None:
        if not self.can_go_back():
            return
        self._history_index -= 1
        self.open(self._history[self._history_index], record_history=False)
        self.state_changed.emit()

    def navigate_forward(self) -> None:
        if not self.can_go_forward():
            return
        self._history_index += 1
        self.open(self._history[self._history_index], record_history=False)
        self.state_changed.emit()

    # ----------------------------------------------------------- edit mode

    def can_edit(self) -> bool:
        return self.current_file is not None

    def is_editing(self) -> bool:
        return self._editing

    def _ensure_editor(self) -> None:
        if self.editor is not None:
            return
        dark = self.renderer.theme == "dark"
        if self._use_web_editor:
            self.editor = WebMarkdownEditor(self, dark=dark)
            edit_page = self.editor
        else:
            self.editor = MarkdownEditor(self, dark=dark)
            self.editor.content_changed.connect(self._update_preview)
            self.preview = QWebEngineView(self)
            self.preview.setPage(MarkdownWebPage(self))
            self.preview.setZoomFactor(self._zoom_factor)
            self.preview.loadFinished.connect(partial(self._restore_scroll, self.preview))
            edit_page = QWidget(self)
            edit_layout = QVBoxLayout(edit_page)
            edit_layout.setContentsMargins(0, 0, 0, 0)
            edit_layout.setSpacing(0)
            split = QSplitter(Qt.Orientation.Horizontal, edit_page)
            split.addWidget(self.editor)
            split.addWidget(self.preview)
            split.setSizes([600, 600])
            edit_layout.addWidget(split)
        self.editor.save_requested.connect(self.save)
        self.editor.cancel_requested.connect(self.cancel_edit)
        self._edit_index = self.stack.addWidget(edit_page)

    def enter_edit_mode(self) -> bool:
        if not self.current_file:
            return False
        try:
            text = read_text_with_fallback(self.current_file)
        except (OSError, UnicodeDecodeError) as exc:
            QMessageBox.warning(self, "Не удалось открыть файл для правки", str(exc))
            return False
        self._ensure_editor()
        self.editor.set_dark(self.renderer.theme == "dark")
        self.editor.load(text, label=str(self.current_file))
        if not self._use_web_editor:
            self._render_preview(text)
        self._editing = True
        self.stack.setCurrentIndex(self._edit_index)
        self.editor.focus_editor()
        self.title_changed.emit()
        self.state_changed.emit()
        return True

    def save(self) -> None:
        if self.editor is None:
            return
        if self._converted_from is not None:
            # A converted .docx has no real file yet — route Ctrl+S to "save as".
            self.save_as_requested.emit()
            return
        if not self.current_file:
            return
        text = self.editor.text()
        try:
            self._suppress_watch = True
            self.current_file.write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Не удалось сохранить файл", f"{self.current_file}\n\n{exc}")
            self._suppress_watch = False
            return
        self.editor.mark_saved()
        QTimer.singleShot(300, self._release_watch)
        self._exit_edit_mode()
        self.open(self.current_file, record_history=False)

    def cancel_edit(self) -> None:
        if self.editor is not None and self.editor.is_modified():
            answer = QMessageBox.question(
                self,
                "Отменить правки",
                "Несохранённые изменения будут потеряны. Закрыть редактор?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._exit_edit_mode()

    def _exit_edit_mode(self) -> None:
        self._editing = False
        self.stack.setCurrentIndex(0)
        self.viewer.setFocus()
        self.title_changed.emit()
        self.state_changed.emit()

    def has_unsaved(self) -> bool:
        return self._editing and self.editor is not None and self.editor.is_modified()

    def has_edits(self) -> bool:
        """Whether the editor holds unsaved changes, even outside edit mode."""
        return self.editor is not None and self.editor.is_modified()

    def _release_watch(self) -> None:
        self._suppress_watch = False

    # ------------------------------------------------------------- preview

    def _update_preview(self) -> None:
        if self.preview is None:
            return
        self.preview.page().runJavaScript("window.scrollY", 0, self._render_preview_at)

    def _render_preview_at(self, scroll_y) -> None:
        if self.editor is not None:
            self._render_preview(self.editor.text(), scroll_to=int(scroll_y or 0))

    def _render_preview(self, text: str, scroll_to: int = 0) -> None:
        if self.preview is None:
            return
        try:
            html = self.renderer.render_text(text, title="preview").html
        except MarkdownRenderError:
            return
        base = self.current_file.parent if self.current_file else Path.cwd()
        self._display(self.preview, html, base, scroll_to=scroll_to)

    # ---------------------------------------------------------- zoom/theme

    def set_zoom(self, factor: float) -> None:
        self._zoom_factor = factor
        self.viewer.setZoomFactor(factor)
        if self.preview is not None:
            self.preview.setZoomFactor(factor)

    def apply_theme(self) -> None:
        dark = self.renderer.theme == "dark"
        if self.editor is not None:
            self.editor.set_dark(dark)
        if self._editing and not self._use_web_editor and self.editor is not None:
            self._render_preview(self.editor.text())
        if self.current_file:
            self.open(self.current_file, record_history=False)

    # -------------------------------------------------------------- export

    def export_pdf(self, dest: str) -> None:
        self.viewer.page().printToPdf(dest)

    def export_pdf_current(self, dest: str, on_done) -> None:
        """Render the current Markdown (including unsaved edits) into the reading
        view and print it to *dest*, calling ``on_done(ok, path)`` when finished."""
        text = self.current_markdown_text()
        try:
            html = self.renderer.render_text(text, title=self.title()).html
        except MarkdownRenderError as exc:
            on_done(False, str(exc))
            return
        base = self.current_file.parent if self.current_file else Path.cwd()
        self._pdf_export_done = on_done
        self._pdf_export_dest = dest
        self.viewer.loadFinished.connect(self._print_current_pdf)
        if self._editing:
            self._editing = False
            self.stack.setCurrentIndex(0)
        self._display(self.viewer, html, base)

    def _print_current_pdf(self, ok: bool) -> None:
        try:
            self.viewer.loadFinished.disconnect(self._print_current_pdf)
        except (RuntimeError, TypeError):
            pass
        self.viewer.page().printToPdf(self._pdf_export_dest)

    def _on_pdf_finished(self, path: str, ok: bool) -> None:
        done = self.__dict__.pop("_pdf_export_done", None)
        if done is not None:
            done(ok, path)
            return
        if ok:
            self.status_message.emit(f"Сохранено в PDF: {path}", 6000)
        else:
            QMessageBox.warning(self, "Не удалось экспортировать PDF", path)

    # --------------------------------------------------------------- search

    def _create_search_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(8, 6, 8, 6)

        label = QLabel("Поиск:", panel)
        self.search_input = QLineEdit(panel)
        self.search_input.setPlaceholderText("Введите текст")
        self.search_input.textChanged.connect(self._find_text)
        self.search_input.returnPressed.connect(self._find_next)

        previous_button = QPushButton("Назад", panel)
        previous_button.clicked.connect(self._find_previous)
        next_button = QPushButton("Далее", panel)
        next_button.clicked.connect(self._find_next)
        close_button = QPushButton("Закрыть", panel)
        close_button.clicked.connect(self.hide_search)

        layout.addWidget(label)
        layout.addWidget(self.search_input, 1)
        layout.addWidget(previous_button)
        layout.addWidget(next_button)
        layout.addWidget(close_button)
        return panel

    def show_search(self) -> None:
        self.search_panel.show()
        self.search_input.setFocus()
        self.search_input.selectAll()

    def hide_search(self) -> None:
        self.viewer.findText("")
        self.search_panel.hide()
        self.viewer.setFocus()

    def search_visible(self) -> bool:
        return self.search_panel.isVisible()

    def _find_text(self, text: str) -> None:
        self.viewer.findText(text)

    def _find_next(self) -> None:
        self.viewer.findText(self.search_input.text())

    def _find_previous(self) -> None:
        self.viewer.findText(self.search_input.text(), QWebEnginePage.FindFlag.FindBackward)

    # ----------------------------------------------------------- rendering

    def _display(self, view: QWebEngineView, html: str, base_dir: Path, scroll_to: int = 0) -> None:
        self._pending_scroll[id(view)] = scroll_to
        base_url = QUrl.fromLocalFile(str(base_dir) + "/")
        if _fits_set_html(html):
            view.setHtml(html, base_url)
            return
        # Too big for setHtml — load from a temp file. A <base> tag keeps
        # relative links/images resolving against the document folder, just as
        # setHtml's base URL did.
        html = _with_base_href(html, base_url)
        view.load(QUrl.fromLocalFile(str(self._write_temp_html(view, html))))

    def _write_temp_html(self, view: QWebEngineView, html: str) -> Path:
        path = self._temp_html.get(id(view))
        if path is None:
            fd, name = tempfile.mkstemp(prefix="mdreader-", suffix=".html")
            os.close(fd)
            path = Path(name)
            self._temp_html[id(view)] = path
        path.write_text(html, encoding="utf-8")
        return path

    def _restore_scroll(self, view: QWebEngineView, ok: bool) -> None:
        scroll_to = self._pending_scroll.pop(id(view), 0)
        if ok and scroll_to:
            view.page().runJavaScript(f"window.scrollTo(0, {scroll_to});")
