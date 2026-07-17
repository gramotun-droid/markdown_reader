from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWebEngineWidgets")

from PySide6.QtCore import QUrl  # noqa: E402

from app.document_view import (  # noqa: E402
    _DATA_URL_LIMIT,
    _cleanup_temp_files,
    _fits_set_html,
    _with_base_href,
)


def test_fits_set_html_small_document():
    assert _fits_set_html("<head></head><body>hello</body>") is True


def test_fits_set_html_rejects_when_encoded_url_exceeds_cap():
    # Chars that must be percent-encoded triple in size, so raw bytes well under
    # the cap can still overflow the data: URL that setHtml builds.
    html = "<head></head>" + "<>&" * 400_000
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
