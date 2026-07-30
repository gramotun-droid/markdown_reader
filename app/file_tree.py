"""A lazy filesystem tree model that can show arbitrary roots.

Qt's own ``QFileSystemModel`` only lists lettered drives (``C:\\``, ``D:\\`` …) at
its "My Computer" level, so WSL distributions and other UNC network shares
(``\\\\wsl.localhost\\Ubuntu``, ``\\\\server\\share``) never appear in the sidebar
even though the app is perfectly able to open files inside them.

``FileTreeModel`` instead takes an explicit list of ``(label, path)`` roots —
local drives, WSL distros and network shares alike, as produced by
:func:`app.drives.available_roots` — and lazily lists their contents with
``os.scandir``. Directories are always shown; files are filtered to the given
Markdown extensions. Children are only scanned when a node is first expanded (or
revealed), so mounting a large drive stays cheap.

The pure directory-listing and path-matching helpers (:func:`scan_dir`,
:func:`path_prefix_parts`) are unit-tested without a running Qt application; the
model itself is a thin wrapper over them.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QAbstractItemModel, QFileInfo, QModelIndex, Qt

try:  # QFileIconProvider moved between QtGui and QtWidgets across Qt 6 minor releases.
    from PySide6.QtGui import QFileIconProvider
except ImportError:  # pragma: no cover - depends on the installed PySide6 build
    from PySide6.QtWidgets import QFileIconProvider


def scan_dir(path: os.PathLike[str] | str, extensions: set[str]) -> list[tuple[str, Path, bool]]:
    """List *path*'s children as ``(name, full_path, is_dir)`` triples.

    Directories come first, then files, each group sorted case-insensitively.
    Directories are always included; files are kept only when their suffix is in
    *extensions* (lower-case, dot-prefixed, e.g. ``{".md", ".markdown"}``).
    Dot-files and unreadable entries are skipped, and an unreadable directory
    yields an empty list rather than raising.
    """
    dirs: list[str] = []
    files: list[str] = []
    try:
        with os.scandir(path) as iterator:
            for entry in iterator:
                if entry.name.startswith("."):
                    continue
                try:
                    is_dir = entry.is_dir()
                except OSError:
                    continue
                if is_dir:
                    dirs.append(entry.name)
                elif Path(entry.name).suffix.lower() in extensions:
                    files.append(entry.name)
    except OSError:
        return []
    dirs.sort(key=str.lower)
    files.sort(key=str.lower)
    base = Path(path)
    return [(name, base / name, True) for name in dirs] + [(name, base / name, False) for name in files]


def path_prefix_parts(root: Path, target: Path) -> tuple[str, ...] | None:
    """Return *target*'s path parts below *root*, or ``None`` if *target* is not
    inside (or equal to) *root*.

    Comparison is case-insensitive so it survives Windows drive-letter casing
    (``c:\\`` vs ``C:\\``) and UNC hosts. ``root == target`` yields ``()``.
    """
    root_parts = root.parts
    target_parts = target.parts
    if len(target_parts) < len(root_parts):
        return None
    for want, have in zip(root_parts, target_parts, strict=False):
        if want.lower() != have.lower():
            return None
    return target_parts[len(root_parts):]


class _Node:
    """One tree entry. ``children is None`` until the directory is scanned."""

    __slots__ = ("path", "label", "is_dir", "parent", "row", "children")

    def __init__(self, path: Path, label: str, is_dir: bool, parent: _Node | None, row: int) -> None:
        self.path = path
        self.label = label
        self.is_dir = is_dir
        self.parent = parent
        self.row = row
        self.children: list[_Node] | None = None


class FileTreeModel(QAbstractItemModel):
    """Lazy single-column filesystem model over an explicit list of roots."""

    def __init__(self, extensions, parent=None) -> None:
        super().__init__(parent)
        self._extensions = {ext.lower() for ext in extensions}
        self._roots: list[_Node] = []
        self._icons: QFileIconProvider | None = None

    # ---------------------------------------------------------------- roots

    def set_roots(self, roots: list[tuple[str, str]]) -> None:
        """Replace the top-level roots with ``(label, path)`` pairs."""
        self.beginResetModel()
        self._roots = [_Node(Path(path), label, True, None, row) for row, (label, path) in enumerate(roots)]
        self.endResetModel()

    def has_roots(self) -> bool:
        return bool(self._roots)

    # ------------------------------------------------------- internal helpers

    def _node(self, index: QModelIndex) -> _Node | None:
        return index.internalPointer() if index.isValid() else None

    def _children(self, node: _Node | None) -> list[_Node]:
        if node is None:
            return self._roots
        if node.children is None:
            entries = scan_dir(node.path, self._extensions) if node.is_dir else []
            node.children = [_Node(path, name, is_dir, node, row) for row, (name, path, is_dir) in enumerate(entries)]
        return node.children

    # ----------------------------------------------- QAbstractItemModel API

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802, B008 - Qt override signature
        return 1

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802, B008 - Qt override signature
        node = self._node(parent)
        if node is not None and not node.is_dir:
            return 0
        return len(self._children(node))

    def hasChildren(self, parent=QModelIndex()) -> bool:  # noqa: N802, B008 - Qt override signature
        node = self._node(parent)
        if node is None:
            return bool(self._roots)
        if not node.is_dir:
            return False
        # Avoid scanning collapsed directories: assume they may hold children
        # until they are actually expanded.
        return True if node.children is None else bool(node.children)

    def index(self, row, column, parent=QModelIndex()) -> QModelIndex:  # noqa: N802, B008 - Qt override signature
        if column != 0 or row < 0:
            return QModelIndex()
        children = self._children(self._node(parent))
        if row >= len(children):
            return QModelIndex()
        return self.createIndex(row, 0, children[row])

    def parent(self, index) -> QModelIndex:  # noqa: N802 - Qt override
        node = self._node(index)
        if node is None or node.parent is None:
            return QModelIndex()
        parent = node.parent
        return self.createIndex(parent.row, 0, parent)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802 - Qt override
        node = self._node(index)
        if node is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return node.label
        if role == Qt.ItemDataRole.ToolTipRole:
            return str(node.path)
        if role == Qt.ItemDataRole.DecorationRole:
            if self._icons is None:
                self._icons = QFileIconProvider()
            return self._icons.icon(QFileInfo(str(node.path)))
        return None

    def flags(self, index):  # noqa: N802 - Qt override
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    # --------------------------------------------------- path <-> index API

    def path_for_index(self, index: QModelIndex) -> Path | None:
        node = self._node(index)
        return node.path if node is not None else None

    def index_for_path(self, target) -> QModelIndex:
        """Index of *target* if it lives under one of the roots, else invalid.

        The chain of directories down to *target* is scanned on the way (so a
        freshly opened file can be revealed even before its folders are
        expanded). The deepest root that contains *target* wins, so a WSL/UNC
        root is preferred over a coincidental drive-letter match.
        """
        target = Path(target)
        best: tuple[_Node, tuple[str, ...]] | None = None
        for root in self._roots:
            rel = path_prefix_parts(root.path, target)
            if rel is None:
                continue
            if best is None or len(root.path.parts) > len(best[0].path.parts):
                best = (root, rel)
        if best is None:
            return QModelIndex()
        node, rel = best
        index = self.createIndex(node.row, 0, node)
        for part in rel:
            match = next((child for child in self._children(node) if child.path.name.lower() == part.lower()), None)
            if match is None:
                return QModelIndex()
            node = match
            index = self.createIndex(node.row, 0, node)
        return index
