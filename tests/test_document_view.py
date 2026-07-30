from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWebEngineWidgets")

from PySide6.QtCore import QUrl  # noqa: E402

from app.document_view import (  # noqa: E402
    _DATA_URL_LIMIT,
    _SET_HTML_SAFE_BYTES,
    _cleanup_temp_files,
    _fits_set_html,
    _safe_mtime,
    _with_base_href,
)


def test_safe_mtime_none_and_missing(tmp_path: Path):
    assert _safe_mtime(None) is None
    assert _safe_mtime(tmp_path / "missing.md") is None


def test_safe_mtime_reflects_writes(tmp_path: Path):
    doc = tmp_path / "a.md"
    doc.write_text("one")
    first = _safe_mtime(doc)
    assert first is not None
    import os

    os.utime(doc, (first + 5, first + 5))
    assert _safe_mtime(doc) != first


def test_fits_set_html_small_document():
    assert _fits_set_html("<head></head><body>hello</body>") is True


def test_fits_set_html_rejects_mid_size_document():
    # Above the guaranteed-safe size we always take the temp-file path, because
    # Qt's percent-encoding can push a sub-2 MB page over the data: URL cap
    # (a ~0.9 MB HTML page was observed to blank out). Raw size alone decides.
    html = "<head></head>" + "x" * _SET_HTML_SAFE_BYTES
    assert len(html.encode("utf-8")) < _DATA_URL_LIMIT
    assert _fits_set_html(html) is False


def test_with_base_href_inserts_after_head():
    html = "<!doctype html>\n<html>\n<head>\n<title>x</title></head><body>hi</body></html>"
    out = _with_base_href(html, QUrl.fromLocalFile("/home/user/docs/"))
    assert '<base href="file:///home/user/docs/">' in out
    assert out.index("<base") < out.index("<title>")


def test_with_base_href_without_head_prepends():
    out = _with_base_href("<div>fragment</div>", QUrl.fromLocalFile("/tmp/"))
    assert out.startswith('<base href="file:///tmp/">')


def test_cleanup_temp_files_removes_and_is_idempotent(tmp_path: Path):
    target = tmp_path / "page.html"
    target.write_text("x", encoding="utf-8")
    files = {1: target}
    _cleanup_temp_files(files)
    assert not target.exists()
    _cleanup_temp_files(files)  # missing files must not raise
