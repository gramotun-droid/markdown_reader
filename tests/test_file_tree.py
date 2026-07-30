from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtCore")

# Render Qt off-screen so the model/view tests never need a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex  # noqa: E402
from PySide6.QtWidgets import QApplication, QTreeView  # noqa: E402

from app.file_tree import FileTreeModel, path_prefix_parts, scan_dir  # noqa: E402

EXTS = {".md", ".markdown"}


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# --------------------------------------------------------------- scan_dir


def test_scan_dir_orders_dirs_then_files_and_filters(tmp_path: Path):
    (tmp_path / "zeta").mkdir()
    (tmp_path / "Alpha").mkdir()
    (tmp_path / "b.md").write_text("x")
    (tmp_path / "A.markdown").write_text("x")
    (tmp_path / "notes.txt").write_text("skip")
    names = [name for name, _path, _is_dir in scan_dir(tmp_path, EXTS)]
    # Directories first (case-insensitive), then files (case-insensitive).
    assert names == ["Alpha", "zeta", "A.markdown", "b.md"]


def test_scan_dir_skips_dotfiles(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".secret.md").write_text("x")
    (tmp_path / "visible.md").write_text("x")
    names = [name for name, _p, _d in scan_dir(tmp_path, EXTS)]
    assert names == ["visible.md"]


def test_scan_dir_unreadable_returns_empty(tmp_path: Path):
    assert scan_dir(tmp_path / "does-not-exist", EXTS) == []


# --------------------------------------------------------- path_prefix_parts


def test_path_prefix_parts_nested():
    root = Path("/srv/wiki")
    assert path_prefix_parts(root, root / "docs" / "a.md") == ("docs", "a.md")


def test_path_prefix_parts_equal_is_empty():
    root = Path("/srv/wiki")
    assert path_prefix_parts(root, root) == ()


def test_path_prefix_parts_outside_is_none():
    assert path_prefix_parts(Path("/srv/wiki"), Path("/etc/passwd")) is None


def test_path_prefix_parts_case_insensitive():
    # Mimics Windows drive-letter casing differences.
    assert path_prefix_parts(Path("/Data"), Path("/data/x.md")) == ("x.md",)


# ------------------------------------------------------------- FileTreeModel


def _build_tree(tmp_path: Path) -> tuple[Path, Path]:
    root_a = tmp_path / "DriveA"
    root_b = tmp_path / "WslUbuntu"
    (root_a / "docs").mkdir(parents=True)
    (root_a / "docs" / "guide.md").write_text("# g")
    (root_a / "index.md").write_text("# i")
    (root_a / "notes.txt").write_text("skip")
    (root_b / "home" / "user").mkdir(parents=True)
    (root_b / "home" / "user" / "readme.markdown").write_text("# r")
    return root_a, root_b


def test_model_lists_roots_and_children(qapp, tmp_path: Path):
    root_a, root_b = _build_tree(tmp_path)
    model = FileTreeModel(EXTS)
    model.set_roots([("Drive A", str(root_a)), ("WSL · Ubuntu", str(root_b))])

    assert model.rowCount(QModelIndex()) == 2
    root_index = model.index(0, 0, QModelIndex())
    assert model.data(root_index) == "Drive A"

    child_names = [model.data(model.index(r, 0, root_index)) for r in range(model.rowCount(root_index))]
    assert child_names == ["docs", "index.md"]  # dir first, .txt filtered out


def test_model_reveal_prefers_deepest_root(qapp, tmp_path: Path):
    root_a, root_b = _build_tree(tmp_path)
    model = FileTreeModel(EXTS)
    # root_a is an ancestor of neither, but ensure the deeper/correct root wins.
    model.set_roots([("Drive A", str(root_a)), ("WSL · Ubuntu", str(root_b))])

    target = root_b / "home" / "user" / "readme.markdown"
    index = model.index_for_path(target)
    assert index.isValid()
    assert model.path_for_index(index) == target
    assert model.data(index) == "readme.markdown"
    assert model.data(model.parent(index)) == "user"


def test_model_reveal_missing_path_is_invalid(qapp, tmp_path: Path):
    root_a, _ = _build_tree(tmp_path)
    model = FileTreeModel(EXTS)
    model.set_roots([("Drive A", str(root_a))])
    assert not model.index_for_path(root_a / "nope" / "x.md").isValid()


def test_model_haschildren_is_lazy(qapp, tmp_path: Path):
    root_a, _ = _build_tree(tmp_path)
    model = FileTreeModel(EXTS)
    model.set_roots([("Drive A", str(root_a))])
    root_index = model.index(0, 0, QModelIndex())
    assert model.hasChildren(root_index) is True
    leaf = model.index_for_path(root_a / "index.md")
    assert model.hasChildren(leaf) is False


def test_model_drives_a_real_treeview(qapp, tmp_path: Path):
    root_a, root_b = _build_tree(tmp_path)
    model = FileTreeModel(EXTS)
    model.set_roots([("Drive A", str(root_a)), ("WSL · Ubuntu", str(root_b))])
    view = QTreeView()
    view.setModel(model)
    view.expandAll()  # exercises rowCount/index/parent/hasChildren together
    assert view.model().rowCount(QModelIndex()) == 2
