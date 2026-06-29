from __future__ import annotations

import os
import tempfile
import threading
from functools import partial
from pathlib import Path

from PySide6.QtCore import QDir, QFileSystemWatcher, QModelIndex, QObject, QProcess, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFileSystemModel,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QSplitterHandle,
    QStackedWidget,
    QSystemTrayIcon,
    QTabWidget,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .document_view import DocumentView
from .drives import available_roots
from .export import ExportError, markdown_to_docx
from .folder_search import search_markdown_files
from .icon import app_icon
from .renderer import MarkdownRenderer, read_text_with_fallback
from .settings import APP_NAME, SUPPORTED_EXTENSIONS, TECHNICAL_DIRS, AppSettings
from .updater import INSTALLER_ASSET, UpdateInfo, can_self_install, check_for_update, download_asset
from .web_editor import web_editor_available


class _UpdateSignals(QObject):
    """Bridges background update threads back to the GUI thread via queued signals."""

    check_done = Signal(object)  # UpdateInfo | None
    check_failed = Signal(str)
    progress = Signal(int)
    download_done = Signal(str)  # path to downloaded installer
    download_failed = Signal(str)


class _SidebarSplitterHandle(QSplitterHandle):
    """Splitter divider that carries a small button to collapse/expand the
    sidebar, the way IDEs and other "grown-up" apps do it."""

    def __init__(self, orientation: Qt.Orientation, splitter: SidebarSplitter) -> None:
        super().__init__(orientation, splitter)
        self.button = QToolButton(self)
        self.button.setObjectName("sidebarToggle")
        self.button.setAutoRaise(True)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setFixedSize(splitter.handleWidth(), 48)
        self.button.clicked.connect(splitter.toggle_sidebar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addSpacing(10)
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)


class SidebarSplitter(QSplitter):
    """Horizontal splitter whose first pane (the tree) can be toggled via a
    button living on the divider handle."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setHandleWidth(12)
        self._restore_width = 300
        self._toggle_button: QToolButton | None = None

    def createHandle(self) -> QSplitterHandle:  # noqa: N802 - Qt override
        # Qt calls this while the splitter is still being built, so avoid
        # querying sizes() here (it re-enters C++ and can crash); the sidebar
        # starts expanded, so seed the glyph directly.
        handle = _SidebarSplitterHandle(self.orientation(), self)
        self._toggle_button = handle.button
        self._toggle_button.setText("‹")
        self._toggle_button.setToolTip("Скрыть дерево")
        return handle

    def sidebar_collapsed(self) -> bool:
        return self.sizes()[0] == 0

    def toggle_sidebar(self) -> None:
        sizes = self.sizes()
        total = sum(sizes)
        if sizes[0] > 0:
            self._restore_width = sizes[0]
            self.setSizes([0, total])
        else:
            width = self._restore_width or 300
            width = min(width, max(160, total - 160))
            self.setSizes([width, total - width])
        self._sync_button()

    def _sync_button(self) -> None:
        if self._toggle_button is None:
            return
        collapsed = self.sidebar_collapsed()
        # ‹ points "into" the sidebar to hide it, › points out to reveal it.
        self._toggle_button.setText("›" if collapsed else "‹")
        self._toggle_button.setToolTip("Показать дерево" if collapsed else "Скрыть дерево")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = AppSettings.load()
        self.renderer = MarkdownRenderer(theme=self.settings.theme)
        self.current_folder: Path | None = None
        self._use_web_editor = web_editor_available()

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1220, 820)

        self.file_model = QFileSystemModel(self)
        self.file_model.setNameFilters(["*.md", "*.markdown"])
        self.file_model.setNameFilterDisables(False)
        self.file_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        # The model loads directories lazily, so revealing a deeply nested file
        # has to wait for each level to populate; _reveal_target drives that.
        self._reveal_target: Path | None = None
        self.file_model.directoryLoaded.connect(self._on_directory_loaded)

        self.tree = QTreeView(self)
        self.tree.setModel(self.file_model)
        self.tree.setHeaderHidden(True)
        self.tree.clicked.connect(self._on_tree_clicked)
        for column in range(1, self.file_model.columnCount()):
            self.tree.hideColumn(column)

        # Tabs (one open document each), with a welcome screen shown when empty.
        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.tabCloseRequested.connect(self._close_tab)

        self.welcome = QWebEngineView(self)

        self.right_stack = QStackedWidget(self)
        self.right_stack.addWidget(self.welcome)  # index 0
        self.right_stack.addWidget(self.tabs)  # index 1

        self.splitter = SidebarSplitter(self)
        self.splitter.addWidget(self.tree)
        self.splitter.addWidget(self.right_stack)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([300, 900])
        self.setCentralWidget(self.splitter)

        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._on_file_changed)
        self._watch_timer = QTimer(self)
        self._watch_timer.setSingleShot(True)
        self._watch_timer.setInterval(150)
        self._watch_timer.timeout.connect(self._do_watch_reload)
        self._changed_paths: set[str] = set()

        self._create_actions()
        self._create_menus()
        self._create_tray()
        self._apply_app_style()
        self._rebuild_recent_menu()
        self._show_welcome()
        self._update_actions()

        self._init_updates()

    # --------------------------------------------------------------- tabs

    def _active(self) -> DocumentView | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, DocumentView) else None

    def _tab_for(self, path: Path) -> DocumentView | None:
        for index in range(self.tabs.count()):
            doc = self.tabs.widget(index)
            if isinstance(doc, DocumentView) and doc.current_file == path:
                return doc
        return None

    def _new_document(self) -> DocumentView:
        doc = DocumentView(self.renderer, use_web_editor=self._use_web_editor, zoom_factor=self.settings.zoom_factor)
        doc.open_request.connect(self.open_file)
        doc.missing_link.connect(self._show_missing_link)
        doc.status_message.connect(self.statusBar().showMessage)
        doc.title_changed.connect(partial(self._update_tab_title, doc))
        doc.state_changed.connect(partial(self._on_doc_state_changed, doc))
        return doc

    def _update_tab_title(self, doc: DocumentView) -> None:
        index = self.tabs.indexOf(doc)
        if index >= 0:
            self.tabs.setTabText(index, doc.title())
            self.tabs.setTabToolTip(index, doc.tooltip())
        if doc is self._active():
            self._update_window_title()

    def _on_doc_state_changed(self, doc: DocumentView) -> None:
        if doc is self._active():
            self._update_actions()

    def _on_tab_changed(self, _index: int) -> None:
        doc = self._active()
        self._update_actions()
        self._update_window_title()
        if doc and doc.current_file:
            self._ensure_tree_for_file(doc.current_file)

    def _close_tab(self, index: int) -> None:
        doc = self.tabs.widget(index)
        if isinstance(doc, DocumentView) and doc.has_unsaved():
            answer = QMessageBox.question(
                self,
                "Закрыть вкладку",
                "В этом документе есть несохранённые изменения. Закрыть?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.tabs.removeTab(index)
        if isinstance(doc, DocumentView):
            doc.deleteLater()
        self._resync_watch()
        if self.tabs.count() == 0:
            self._show_welcome()
        self._update_actions()

    def close_current_tab(self) -> None:
        if self.tabs.count():
            self._close_tab(self.tabs.currentIndex())

    # ------------------------------------------------------------------ open

    def open_start_path(self, raw_path: str) -> None:
        path = Path(raw_path).expanduser().resolve()
        if path.is_file():
            self.open_file(path)
        elif path.is_dir():
            self.open_folder(path)
        else:
            self._error("Путь не найден", f"Не удалось найти: {path}")

    def open_file(self, path: Path) -> None:
        path = path.resolve()
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            self._error("Неподдерживаемый файл", "Можно открывать только .md и .markdown файлы.")
            return

        existing = self._tab_for(path)
        if existing is not None:
            self.right_stack.setCurrentWidget(self.tabs)
            self.tabs.setCurrentWidget(existing)
            self._post_open(path)
            return

        doc = self._new_document()
        index = self.tabs.addTab(doc, "…")
        self.tabs.setCurrentIndex(index)
        self.right_stack.setCurrentWidget(self.tabs)
        if not doc.open(path):
            self.tabs.removeTab(index)
            doc.deleteLater()
            if self.tabs.count() == 0:
                self._show_welcome()
            return
        self._post_open(path)

    def _post_open(self, path: Path) -> None:
        self.settings.last_path = path
        self.settings.remember_recent(path)
        self._ensure_tree_for_file(path)
        self._resync_watch()
        self._rebuild_recent_menu()
        self._update_actions()
        self._update_window_title()
        self.settings.save()

    def open_folder(self, path: Path) -> None:
        path = path.resolve()
        if not path.exists() or not path.is_dir():
            self._error("Папка не найдена", f"Не удалось открыть папку: {path}")
            return

        self.current_folder = path
        self.settings.last_path = path
        root_index = self.file_model.setRootPath(str(path))
        self.tree.setRootIndex(root_index)
        self.tree.expand(root_index)
        self.folder_search_action.setEnabled(True)
        self.settings.save()

        start_file = self._find_start_file(path)
        if start_file:
            self.open_file(start_file)
        else:
            self._show_folder_empty(path)

    # --------------------------------------------------------------- actions

    def _create_actions(self) -> None:
        self.open_file_action = QAction("Открыть файл", self)
        self.open_file_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_file_action.triggered.connect(self._choose_file)

        self.open_folder_action = QAction("Открыть папку", self)
        self.open_folder_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.open_folder_action.triggered.connect(self._choose_folder)

        self.close_tab_action = QAction("Закрыть вкладку", self)
        self.close_tab_action.setShortcut(QKeySequence.StandardKey.Close)  # Ctrl+W
        self.close_tab_action.triggered.connect(self.close_current_tab)

        self.edit_action = QAction("Редактировать", self)
        self.edit_action.setShortcut(QKeySequence("Ctrl+E"))
        self.edit_action.setEnabled(False)
        self.edit_action.triggered.connect(self._edit_active)

        self.export_pdf_action = QAction("В PDF…", self)
        self.export_pdf_action.setEnabled(False)
        self.export_pdf_action.triggered.connect(self.export_pdf)

        self.export_docx_action = QAction("В Word (DOCX)…", self)
        self.export_docx_action.setEnabled(False)
        self.export_docx_action.triggered.connect(self.export_docx)

        self.save_action = QAction("Сохранить", self)
        self.save_action.setEnabled(False)
        self.save_action.triggered.connect(self._save_active)
        if not self._use_web_editor:
            # The web editor handles Ctrl+S itself; the plain editor needs the
            # window-level shortcut to drive saving.
            self.save_action.setShortcut(QKeySequence.StandardKey.Save)

        self.cancel_edit_action = QAction("Отменить правки", self)
        self.cancel_edit_action.setEnabled(False)
        self.cancel_edit_action.triggered.connect(self._cancel_active)

        self.toggle_sidebar_action = QAction("Боковая панель", self)
        self.toggle_sidebar_action.setShortcut(QKeySequence("Ctrl+B"))
        self.toggle_sidebar_action.triggered.connect(self.splitter.toggle_sidebar)

        self.exit_action = QAction("Выход", self)
        self.exit_action.triggered.connect(self.close)

        self.find_action = QAction("Поиск на странице", self)
        self.find_action.setShortcut(QKeySequence.StandardKey.Find)
        self.find_action.triggered.connect(self._find_in_active)

        self.folder_search_action = QAction("Поиск по папке", self)
        self.folder_search_action.setShortcut(QKeySequence("Ctrl+Shift+F"))
        self.folder_search_action.setEnabled(False)
        self.folder_search_action.triggered.connect(self._show_folder_search)

        self.refresh_action = QAction("Обновить", self)
        self.refresh_action.setShortcut(QKeySequence("Ctrl+R"))
        self.refresh_action.triggered.connect(self._refresh_active)

        self.back_action = QAction("Назад", self)
        self.back_action.setShortcut(QKeySequence("Alt+Left"))
        self.back_action.triggered.connect(self._back_active)

        self.forward_action = QAction("Вперёд", self)
        self.forward_action.setShortcut(QKeySequence("Alt+Right"))
        self.forward_action.triggered.connect(self._forward_active)

        self.theme_action = QAction("Тёмная тема", self)
        self.theme_action.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self.theme_action.triggered.connect(self.toggle_theme)
        self._sync_theme_action()

        self.zoom_in_action = QAction("Увеличить масштаб", self)
        self.zoom_in_action.setShortcut(QKeySequence.StandardKey.ZoomIn)
        self.zoom_in_action.triggered.connect(self.zoom_in)

        self.zoom_out_action = QAction("Уменьшить масштаб", self)
        self.zoom_out_action.setShortcut(QKeySequence.StandardKey.ZoomOut)
        self.zoom_out_action.triggered.connect(self.zoom_out)

        self.zoom_reset_action = QAction("Сбросить масштаб", self)
        self.zoom_reset_action.setShortcut(QKeySequence("Ctrl+0"))
        self.zoom_reset_action.triggered.connect(self.zoom_reset)

        self.update_action = QAction("Проверить обновления", self)
        self.update_action.triggered.connect(lambda: self.check_for_updates(silent=False))

        self.about_action = QAction("О программе", self)
        self.about_action.triggered.connect(self._show_about)

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("Файл")
        file_menu.addAction(self.open_file_action)
        file_menu.addAction(self.open_folder_action)
        self.drives_menu = file_menu.addMenu("Диски")
        self.drives_menu.aboutToShow.connect(lambda: self._populate_drives_menu(self.drives_menu))
        self.recent_menu = file_menu.addMenu("Недавние файлы")
        file_menu.addSeparator()
        export_menu = file_menu.addMenu("Экспорт")
        export_menu.addAction(self.export_pdf_action)
        export_menu.addAction(self.export_docx_action)
        file_menu.addSeparator()
        file_menu.addAction(self.close_tab_action)
        file_menu.addAction(self.exit_action)

        edit_menu = self.menuBar().addMenu("Правка")
        edit_menu.addAction(self.edit_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.save_action)
        edit_menu.addAction(self.cancel_edit_action)

        view_menu = self.menuBar().addMenu("Вид")
        view_menu.addAction(self.toggle_sidebar_action)
        view_menu.addSeparator()
        view_menu.addAction(self.back_action)
        view_menu.addAction(self.forward_action)
        view_menu.addSeparator()
        view_menu.addAction(self.theme_action)
        view_menu.addSeparator()
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)
        view_menu.addAction(self.zoom_reset_action)
        view_menu.addSeparator()
        view_menu.addAction(self.refresh_action)

        search_menu = self.menuBar().addMenu("Поиск")
        search_menu.addAction(self.find_action)
        search_menu.addAction(self.folder_search_action)

        help_menu = self.menuBar().addMenu("Справка")
        help_menu.addAction(self.update_action)
        help_menu.addSeparator()
        help_menu.addAction(self.about_action)

    def _populate_drives_menu(self, menu: QMenu) -> None:
        # Rebuilt on every open so mounting a drive/WSL distro shows up live.
        menu.clear()
        try:
            roots = available_roots()
        except Exception:  # noqa: BLE001 - drive enumeration must never crash the UI
            roots = []
        if not roots:
            empty = menu.addAction("Диски не найдены")
            empty.setEnabled(False)
            return
        for label, path in roots:
            action = menu.addAction(label)
            action.triggered.connect(partial(self.open_folder, Path(path)))

    def _create_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(APP_NAME)

        show_action = QAction("Показать окно", self)
        show_action.triggered.connect(self._restore_window)
        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self.close)

        # The tray menu mirrors the main actions so there is no separate toolbar.
        menu = QMenu(self)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(self.open_file_action)
        menu.addAction(self.open_folder_action)
        tray_drives = menu.addMenu("Диски")
        tray_drives.aboutToShow.connect(lambda: self._populate_drives_menu(tray_drives))
        menu.addSeparator()
        menu.addAction(self.theme_action)
        menu.addAction(self.update_action)
        menu.addSeparator()
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._restore_window()

    def _restore_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # --------------------------------------------- active-tab action routing

    def _edit_active(self) -> None:
        doc = self._active()
        if doc:
            doc.enter_edit_mode()

    def _save_active(self) -> None:
        doc = self._active()
        if doc:
            doc.save()

    def _cancel_active(self) -> None:
        doc = self._active()
        if doc:
            doc.cancel_edit()

    def _refresh_active(self) -> None:
        doc = self._active()
        if doc:
            doc.refresh()
        else:
            self.statusBar().showMessage("Нет открытого документа", 3000)

    def _back_active(self) -> None:
        doc = self._active()
        if doc:
            doc.navigate_back()

    def _forward_active(self) -> None:
        doc = self._active()
        if doc:
            doc.navigate_forward()

    def _find_in_active(self) -> None:
        doc = self._active()
        if doc:
            doc.show_search()

    def _update_actions(self) -> None:
        doc = self._active()
        has_doc = doc is not None and doc.current_file is not None
        editing = bool(doc and doc.is_editing())
        self.edit_action.setEnabled(bool(doc and doc.can_edit()) and not editing)
        self.save_action.setEnabled(editing)
        self.cancel_edit_action.setEnabled(editing)
        self.export_pdf_action.setEnabled(has_doc)
        self.export_docx_action.setEnabled(has_doc)
        self.refresh_action.setEnabled(has_doc)
        self.find_action.setEnabled(has_doc)
        self.back_action.setEnabled(bool(doc and doc.can_go_back()))
        self.forward_action.setEnabled(bool(doc and doc.can_go_forward()))

    def _update_window_title(self) -> None:
        doc = self._active()
        if doc and doc.current_file:
            self.setWindowTitle(f"{APP_NAME} - {doc.current_file.name}")
        else:
            self.setWindowTitle(APP_NAME)

    # ------------------------------------------------------------- watcher

    def _resync_watch(self) -> None:
        existing = self.watcher.files()
        if existing:
            self.watcher.removePaths(existing)
        paths = {
            str(self.tabs.widget(i).current_file)
            for i in range(self.tabs.count())
            if isinstance(self.tabs.widget(i), DocumentView) and self.tabs.widget(i).current_file
        }
        if paths:
            self.watcher.addPaths(list(paths))

    def _on_file_changed(self, path: str) -> None:
        self._changed_paths.add(path)
        self._watch_timer.start()

    def _do_watch_reload(self) -> None:
        changed = self._changed_paths
        self._changed_paths = set()
        for index in range(self.tabs.count()):
            doc = self.tabs.widget(index)
            if not isinstance(doc, DocumentView) or not doc.current_file:
                continue
            if str(doc.current_file) in changed and doc.current_file.exists() and doc.wants_external_reload():
                doc.refresh()
        # Some editors replace files, dropping the watch; re-arm it.
        self._resync_watch()

    # ------------------------------------------------------------- recent

    def _rebuild_recent_menu(self) -> None:
        self.recent_menu.clear()
        if not self.settings.recent_files:
            empty = self.recent_menu.addAction("Пусто")
            empty.setEnabled(False)
            return
        for path in self.settings.recent_files:
            action = self.recent_menu.addAction(path.name)
            action.setToolTip(str(path))
            action.triggered.connect(partial(self._open_recent, path))
        self.recent_menu.addSeparator()
        clear_action = self.recent_menu.addAction("Очистить список")
        clear_action.triggered.connect(self._clear_recent)

    def _open_recent(self, path: Path) -> None:
        if path.exists():
            self.open_file(path)
        else:
            self._error("Файл не найден", f"Файл больше не существует:\n{path}")
            self.settings.recent_files = [item for item in self.settings.recent_files if item != path]
            self.settings.save()
            self._rebuild_recent_menu()

    def _clear_recent(self) -> None:
        self.settings.recent_files = []
        self.settings.save()
        self._rebuild_recent_menu()

    # --------------------------------------------------------- folder search

    def _show_folder_search(self) -> None:
        if not self.current_folder:
            return
        dialog = FolderSearchDialog(self.current_folder, self)
        dialog.file_chosen.connect(self.open_file)
        dialog.exec()

    # --------------------------------------------------------------- export

    def export_pdf(self) -> None:
        doc = self._active()
        if not doc or not doc.current_file:
            return
        default = str(doc.current_file.with_suffix(".pdf"))
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт в PDF", default, "PDF (*.pdf)")
        if not path:
            return
        self.statusBar().showMessage("Экспорт в PDF…")
        doc.export_pdf(path)

    def export_docx(self) -> None:
        doc = self._active()
        if not doc or not doc.current_file:
            return
        default = str(doc.current_file.with_suffix(".docx"))
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт в Word", default, "Word (*.docx)")
        if not path:
            return
        try:
            text = read_text_with_fallback(doc.current_file)
            markdown_to_docx(text, Path(path), title=doc.current_file.stem)
        except (OSError, UnicodeDecodeError) as exc:
            self._error("Не удалось экспортировать DOCX", f"{path}\n\n{exc}")
            return
        except ExportError as exc:
            self._error("Не удалось экспортировать DOCX", str(exc))
            return
        self.statusBar().showMessage(f"Сохранено в DOCX: {path}", 6000)

    # ----------------------------------------------------------- file/folder

    def _choose_file(self) -> None:
        last = self.settings.last_path
        if last and last.is_file():
            start_dir = str(last.parent)
        else:
            start_dir = str(last or Path.home())
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть Markdown файл",
            start_dir,
            "Markdown files (*.md *.markdown)",
        )
        if file_name:
            self.open_file(Path(file_name))

    def _choose_folder(self) -> None:
        start_dir = str(self.settings.last_path if self.settings.last_path and self.settings.last_path.is_dir() else Path.home())
        folder_name = QFileDialog.getExistingDirectory(self, "Открыть папку wiki", start_dir)
        if folder_name:
            self.open_folder(Path(folder_name))

    def _on_tree_clicked(self, index: QModelIndex) -> None:
        path = Path(self.file_model.filePath(index))
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            self.open_file(path)

    def _ensure_tree_for_file(self, path: Path) -> None:
        """Show the directory tree containing the open file and highlight it.
        For files outside a wiki folder the tree is rooted at the filesystem /
        drive top so the whole chain of parent folders stays visible."""
        self._reveal_target = path
        if not (self.current_folder and _is_within(path, self.current_folder)):
            self.current_folder = path.parent
            self.file_model.setRootPath(str(path.parent))
            self.tree.setRootIndex(QModelIndex())
            self.folder_search_action.setEnabled(True)
        self._try_reveal()

    def _on_directory_loaded(self, _loaded_path: str) -> None:
        self._try_reveal()

    def _try_reveal(self) -> None:
        target = self._reveal_target
        if target is not None and self._select_file_in_tree(target):
            self._reveal_target = None

    def _select_file_in_tree(self, path: Path) -> bool:
        index = self.file_model.index(str(path))
        if not index.isValid():
            return False
        parent = index.parent()
        while parent.isValid():
            self.tree.expand(parent)
            parent = parent.parent()
        self.tree.setCurrentIndex(index)
        self.tree.scrollTo(index, QTreeView.ScrollHint.PositionAtCenter)
        return True

    def _find_start_file(self, folder: Path) -> Path | None:
        for name in ("index.md", "README.md", "readme.md", "Index.md"):
            candidate = folder / name
            if candidate.exists():
                return candidate

        root_markdown_files = sorted(
            candidate for candidate in folder.iterdir() if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        if root_markdown_files:
            return root_markdown_files[0]

        for dirpath, dirnames, filenames in os.walk(folder, onerror=lambda _error: None):
            dirnames[:] = [name for name in dirnames if name not in TECHNICAL_DIRS]
            for filename in sorted(filenames):
                candidate = Path(dirpath) / filename
                if candidate.suffix.lower() in SUPPORTED_EXTENSIONS:
                    return candidate
        return None

    # ----------------------------------------------------------- view/zoom

    def zoom_in(self) -> None:
        self._set_zoom(min(self.settings.zoom_factor + 0.1, 3.0))

    def zoom_out(self) -> None:
        self._set_zoom(max(self.settings.zoom_factor - 0.1, 0.25))

    def zoom_reset(self) -> None:
        self._set_zoom(1.0)

    def _set_zoom(self, factor: float) -> None:
        self.settings.zoom_factor = factor
        for index in range(self.tabs.count()):
            doc = self.tabs.widget(index)
            if isinstance(doc, DocumentView):
                doc.set_zoom(factor)
        self.settings.save()

    # -------------------------------------------------------------- theme

    def toggle_theme(self) -> None:
        new_theme = "dark" if self.renderer.theme == "light" else "light"
        self.renderer.set_theme(new_theme)
        self.settings.theme = new_theme
        self.settings.save()
        self._sync_theme_action()
        self._apply_app_style()
        for index in range(self.tabs.count()):
            doc = self.tabs.widget(index)
            if isinstance(doc, DocumentView):
                doc.apply_theme()
        if self.tabs.count() == 0:
            self._show_welcome()

    def _sync_theme_action(self) -> None:
        self.theme_action.setText("Светлая тема" if self.renderer.theme == "dark" else "Тёмная тема")

    def _apply_app_style(self) -> None:
        """A light, theme-aware Qt stylesheet for the window chrome (sidebar,
        tabs, splitter, status bar, scrollbars). The rendered Markdown keeps its
        own CSS; this only dresses up the surrounding native widgets."""
        if self.renderer.theme == "dark":
            c = {
                "bg": "#171a21", "panel": "#1b1f27", "text": "#e5e7eb",
                "muted": "#a6adbb", "border": "#2a3039", "accent": "#3b6fe0",
                "sel": "#24406e", "hover": "#222732",
            }
        else:
            c = {
                "bg": "#ffffff", "panel": "#f7f9fc", "text": "#1f2937",
                "muted": "#5d6675", "border": "#e1e6ee", "accent": "#2563eb",
                "sel": "#dbe6ff", "hover": "#eef2f8",
            }
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{ background: {c['bg']}; color: {c['text']}; }}
            QTreeView {{
                background: {c['panel']}; border: none; padding: 6px 4px;
                outline: 0; font-size: 13px;
            }}
            QTreeView::item {{ padding: 4px 6px; border-radius: 6px; }}
            QTreeView::item:hover {{ background: {c['hover']}; }}
            QTreeView::item:selected {{ background: {c['sel']}; color: {c['text']}; }}
            QTabWidget::pane {{ border: none; }}
            QTabBar {{ qproperty-drawBase: 0; }}
            QTabBar::tab {{
                background: {c['panel']}; color: {c['muted']};
                border: 1px solid {c['border']}; border-bottom: none;
                border-top-left-radius: 6px; border-top-right-radius: 6px;
                padding: 6px 12px; margin-right: 2px; max-width: 240px;
            }}
            QTabBar::tab:selected {{ background: {c['bg']}; color: {c['text']}; }}
            QTabBar::tab:hover {{ background: {c['hover']}; }}
            QTabBar::close-button {{ subcontrol-position: right; }}
            QSplitter::handle {{ background: {c['panel']}; }}
            QSplitter::handle:horizontal {{ width: 12px; border-left: 1px solid {c['border']}; }}
            QToolButton#sidebarToggle {{
                border: none; background: transparent; color: {c['muted']};
                font-size: 15px; font-weight: bold; border-radius: 4px;
            }}
            QToolButton#sidebarToggle:hover {{ background: {c['hover']}; color: {c['text']}; }}
            QStatusBar {{ background: {c['panel']}; color: {c['muted']}; border-top: 1px solid {c['border']}; }}
            QStatusBar::item {{ border: none; }}
            QProgressBar {{
                border: 1px solid {c['border']}; border-radius: 6px;
                background: {c['bg']}; text-align: center; height: 16px;
            }}
            QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}
            QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 28px; }}
            QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
            """
        )

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            doc = self._active()
            if doc and doc.search_visible():
                doc.hide_search()
                return
        super().keyPressEvent(event)

    # ------------------------------------------------------------- screens

    def _render_into_welcome(self, markdown: str, title: str) -> None:
        html = self.renderer.render_text(markdown, title=title).html
        self.welcome.setHtml(html, QUrl.fromLocalFile(str(Path.cwd()) + "/"))

    def _show_missing_link(self, path: Path) -> None:
        self._error("Файл не найден", f"Ссылка ведёт на несуществующий файл:\n{path}")

    def _show_welcome(self) -> None:
        self._render_into_welcome(
            "# MD Reader\n\nОткройте Markdown-файл или папку wiki через меню **Файл**. "
            "Документы открываются во вкладках вверху.",
            "MD Reader",
        )
        self.right_stack.setCurrentWidget(self.welcome)
        self._update_window_title()

    def _show_folder_empty(self, path: Path) -> None:
        self._render_into_welcome(
            f"# Папка открыта\n\nВ папке не найдено Markdown-файлов:\n\n`{path}`",
            "Папка открыта",
        )
        self.right_stack.setCurrentWidget(self.welcome)
        self.setWindowTitle(f"{APP_NAME} - {path.name}")

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "О программе",
            f"<h3>MD Reader</h3>"
            f"<p>Версия {__version__}</p>"
            "<p>Просмотрщик и редактор Markdown-файлов и локальных wiki.</p>"
            "<p><b>Разработчик:</b> Pavel Maksimov</p>",
        )

    def _error(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    # ----------------------------------------------------------------- updates

    def _init_updates(self) -> None:
        self._update_in_progress = False
        self._update_silent = True
        self._latest_update: UpdateInfo | None = None
        self._progress_dialog: QProgressDialog | None = None

        self._update_signals = _UpdateSignals()
        self._update_signals.check_done.connect(self._on_update_checked)
        self._update_signals.check_failed.connect(self._on_update_check_failed)
        self._update_signals.progress.connect(self._set_progress_value)
        self._update_signals.download_done.connect(self._on_update_downloaded)
        self._update_signals.download_failed.connect(self._on_update_download_failed)

        if self.settings.check_updates_on_start:
            # Defer so the window paints first; the check runs off the GUI thread.
            QTimer.singleShot(1500, lambda: self.check_for_updates(silent=True))

    def _show_progress_dialog(self, label: str, *, busy: bool) -> None:
        """A clearly visible modeless dialog with a label and progress bar, so
        the user can always see that a check/download is happening."""
        if self._progress_dialog is None:
            dialog = QProgressDialog(label, "", 0, 0, self)
            dialog.setCancelButton(None)  # no cancel — updates run to completion
            dialog.setWindowTitle("Обновление MD Reader")
            dialog.setWindowModality(Qt.WindowModality.NonModal)
            dialog.setMinimumDuration(0)
            dialog.setAutoClose(False)
            dialog.setAutoReset(False)
            dialog.setMinimumWidth(380)
            self._progress_dialog = dialog
        dialog = self._progress_dialog
        dialog.setLabelText(label)
        if busy:
            dialog.setRange(0, 0)  # marquee / indeterminate
        else:
            dialog.setRange(0, 100)
            dialog.setValue(0)
        dialog.show()
        dialog.raise_()

    def _set_progress_value(self, value: int) -> None:
        if self._progress_dialog is not None and self._progress_dialog.maximum() != 0:
            self._progress_dialog.setValue(value)

    def _finish_update_activity(self) -> None:
        self.statusBar().clearMessage()
        if self._progress_dialog is not None:
            self._progress_dialog.reset()
            self._progress_dialog.hide()

    def check_for_updates(self, silent: bool = False) -> None:
        if self._update_in_progress:
            return
        self._update_in_progress = True
        self._update_silent = silent
        if not silent:
            self._show_progress_dialog("Проверка обновлений…", busy=True)
        threading.Thread(target=self._run_update_check, daemon=True).start()

    def _run_update_check(self) -> None:
        try:
            info = check_for_update(__version__)
        except Exception as exc:  # noqa: BLE001 - any failure is reported to the UI
            self._update_signals.check_failed.emit(str(exc))
        else:
            self._update_signals.check_done.emit(info)

    def _on_update_checked(self, info: object) -> None:
        if info is None:
            self._update_in_progress = False
            self._finish_update_activity()
            if not self._update_silent:
                QMessageBox.information(
                    self,
                    "Обновления",
                    f"У вас последняя версия MD Reader ({__version__}).",
                )
            return

        self._latest_update = info  # type: ignore[assignment]
        if can_self_install() and info.asset_url:  # type: ignore[attr-defined]
            self._start_update_download(info)  # type: ignore[arg-type]
        else:
            self._update_in_progress = False
            self._finish_update_activity()
            self.statusBar().showMessage(f"Доступна версия {info.tag}", 8000)  # type: ignore[attr-defined]
            if not self._update_silent:
                QDesktopServices.openUrl(QUrl(info.html_url))  # type: ignore[attr-defined]

    def _on_update_check_failed(self, message: str) -> None:
        self._update_in_progress = False
        self._finish_update_activity()
        if not self._update_silent:
            self._error("Не удалось проверить обновления", message)

    def _start_update_download(self, info: UpdateInfo) -> None:
        dest = str(Path(tempfile.gettempdir()) / (info.asset_name or INSTALLER_ASSET))
        self._show_progress_dialog(f"Загрузка обновления MD Reader {info.tag}…", busy=False)
        self.statusBar().showMessage(f"Загрузка обновления MD Reader {info.tag}…")
        threading.Thread(
            target=self._run_update_download,
            args=(info.asset_url, dest),
            daemon=True,
        ).start()

    def _run_update_download(self, url: str, dest: str) -> None:
        try:
            download_asset(url, Path(dest), progress=self._update_signals.progress.emit)
        except Exception as exc:  # noqa: BLE001
            self._update_signals.download_failed.emit(str(exc))
        else:
            self._update_signals.download_done.emit(dest)

    def _on_update_downloaded(self, path: str) -> None:
        self._finish_update_activity()
        self._update_in_progress = False
        tag = self._latest_update.tag if self._latest_update else ""
        answer = QMessageBox.question(
            self,
            "Обновление готово",
            f"Загружено обновление MD Reader {tag}.\n\n"
            "Установить сейчас? Приложение будет закрыто на время установки.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.statusBar().showMessage("Обновление будет установлено позже", 6000)
            return
        self.statusBar().showMessage("Установка обновления…")
        started = QProcess.startDetached(path, ["/VERYSILENT", "/NORESTART"])
        if started:
            QTimer.singleShot(200, QApplication.quit)
        else:
            self._error("Не удалось запустить установщик обновления", path)

    def _on_update_download_failed(self, message: str) -> None:
        self._finish_update_activity()
        self._update_in_progress = False
        if not self._update_silent:
            self._error("Не удалось загрузить обновление", message)
        else:
            self.statusBar().showMessage("Не удалось загрузить обновление", 6000)


class FolderSearchDialog(QDialog):
    """Full-text search across the open wiki folder."""

    file_chosen = Signal(object)

    def __init__(self, folder: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.folder = folder
        self.setWindowTitle("Поиск по папке")
        self.resize(720, 480)

        self.input = QLineEdit(self)
        self.input.setPlaceholderText("Введите текст и нажмите Enter")
        self.input.returnPressed.connect(self._run_search)

        search_button = QPushButton("Найти", self)
        search_button.clicked.connect(self._run_search)

        self.status = QLabel("", self)
        self.results = QListWidget(self)
        self.results.itemActivated.connect(self._on_activated)
        self.results.itemDoubleClicked.connect(self._on_activated)

        top = QHBoxLayout()
        top.addWidget(self.input, 1)
        top.addWidget(search_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.status)
        layout.addWidget(self.results, 1)

    def _run_search(self) -> None:
        query = self.input.text().strip()
        self.results.clear()
        if not query:
            self.status.setText("")
            return
        hits = search_markdown_files(self.folder, query)
        self.status.setText(f"Найдено совпадений: {len(hits)}")
        for hit in hits:
            rel = _safe_relative(hit.path, self.folder)
            item = QListWidgetItem(f"{rel}:{hit.line_number}  —  {hit.snippet}")
            item.setData(Qt.ItemDataRole.UserRole, str(hit.path))
            self.results.addItem(item)

    def _on_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.file_chosen.emit(Path(path))
            self.accept()


def _is_within(path: Path, base: Path) -> bool:
    """True when ``path`` is ``base`` itself or lives somewhere under it."""
    if path == base:
        return True
    try:
        return path.is_relative_to(base)
    except AttributeError:  # Python < 3.9 fallback
        return base in path.parents


def _safe_relative(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)
