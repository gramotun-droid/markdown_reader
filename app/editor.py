from __future__ import annotations

import re

from PySide6.QtCore import QRegularExpression, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

# Live-preview debounce so we don't re-render on every keystroke.
PREVIEW_DEBOUNCE_MS = 250


class MarkdownHighlighter(QSyntaxHighlighter):
    """Lightweight Markdown syntax highlighting for the editor pane."""

    def __init__(self, document: QTextDocument, dark: bool = False) -> None:
        super().__init__(document)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self._fence_format = QTextCharFormat()
        self._build_rules(dark)

    def _build_rules(self, dark: bool) -> None:
        palette = {
            "heading": "#7aa2ff" if dark else "#1d4ed8",
            "emphasis": "#e5e7eb" if dark else "#1f2937",
            "code": "#e879f9" if dark else "#9333ea",
            "link": "#34d399" if dark else "#0d9488",
            "quote": "#a6adbb" if dark else "#5d6675",
            "list": "#f59e0b" if dark else "#b45309",
        }

        def fmt(color: str, *, bold: bool = False, italic: bool = False, mono: bool = False) -> QTextCharFormat:
            text_format = QTextCharFormat()
            text_format.setForeground(QColor(color))
            if bold:
                text_format.setFontWeight(QFont.Weight.Bold)
            if italic:
                text_format.setFontItalic(True)
            if mono:
                text_format.setFontFixedPitch(True)
            return text_format

        rules = [
            (r"^#{1,6}\s.*$", fmt(palette["heading"], bold=True)),
            (r"\*\*[^*]+\*\*", fmt(palette["emphasis"], bold=True)),
            (r"__[^_]+__", fmt(palette["emphasis"], bold=True)),
            (r"(?<!\*)\*(?!\*)[^*]+\*(?!\*)", fmt(palette["emphasis"], italic=True)),
            (r"`[^`]+`", fmt(palette["code"], mono=True)),
            (r"\[[^\]]+\]\([^)]+\)", fmt(palette["link"])),
            (r"^\s*>.*$", fmt(palette["quote"], italic=True)),
            (r"^\s*([-*+]|\d+\.)\s", fmt(palette["list"], bold=True)),
        ]
        self._rules = [(QRegularExpression(pattern), text_format) for pattern, text_format in rules]
        self._fence_format = fmt(palette["code"], mono=True)

    def highlightBlock(self, text: str) -> None:
        # Multi-line fenced code blocks via block state.
        fence = re.match(r"^\s*(```|~~~)", text)
        if self.previousBlockState() == 1:
            self.setFormat(0, len(text), self._fence_format)
            self.setCurrentBlockState(0 if fence else 1)
            return
        if fence:
            self.setFormat(0, len(text), self._fence_format)
            self.setCurrentBlockState(1)
            return

        for expression, text_format in self._rules:
            iterator = expression.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), text_format)


class MarkdownEditor(QWidget):
    """Editor pane: a thin header showing the file path plus the text area.

    All editing commands (save, cancel, undo, redo) live in the window's
    "Правка" menu rather than on in-pane buttons, so this widget only exposes
    signals/methods the menu actions drive."""

    save_requested = Signal()
    cancel_requested = Signal()
    content_changed = Signal()
    undo_available = Signal(bool)
    redo_available = Signal(bool)

    def __init__(self, parent: QWidget | None = None, dark: bool = False) -> None:
        super().__init__(parent)
        self.editor = QPlainTextEdit(self)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setTabStopDistance(28)
        font = QFont("Cascadia Code", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(font)
        self.highlighter = MarkdownHighlighter(self.editor.document(), dark=dark)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(PREVIEW_DEBOUNCE_MS)
        self._debounce.timeout.connect(self.content_changed)
        self.editor.textChanged.connect(self._debounce.start)

        self.path_label = QLabel("", self)
        self.path_label.setObjectName("editorPathLabel")
        self.path_label.setContentsMargins(8, 6, 8, 6)

        # Re-emit the editor's availability signals so the menu actions can
        # enable/disable themselves without reaching into the QPlainTextEdit.
        self.editor.undoAvailable.connect(self.undo_available)
        self.editor.redoAvailable.connect(self.redo_available)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.path_label)
        layout.addWidget(self.editor, 1)

    def load(self, text: str, label: str = "") -> None:
        self.editor.setPlainText(text)
        self.editor.document().clearUndoRedoStacks()
        self.editor.document().setModified(False)
        self.path_label.setText(label)
        self.undo_available.emit(False)
        self.redo_available.emit(False)

    def undo(self) -> None:
        self.editor.undo()

    def redo(self) -> None:
        self.editor.redo()

    def text(self) -> str:
        return self.editor.toPlainText()

    def is_modified(self) -> bool:
        return self.editor.document().isModified()

    def mark_saved(self) -> None:
        self.editor.document().setModified(False)

    def focus_editor(self) -> None:
        self.editor.setFocus()

    def set_dark(self, dark: bool) -> None:
        # Rebuild the highlighter so editor colours follow the app theme.
        self.highlighter.setDocument(None)
        self.highlighter.deleteLater()
        self.highlighter = MarkdownHighlighter(self.editor.document(), dark=dark)
