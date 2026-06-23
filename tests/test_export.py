from __future__ import annotations

from pathlib import Path

import pytest

from app.export import ExportError, markdown_to_docx

docx = pytest.importorskip("docx")


SAMPLE = """# Заголовок

Обычный абзац с **жирным**, *курсивом* и `кодом`.

## Список

- первый
- второй
  - вложенный

1. раз
2. два

> Цитата текста

```python
def hello():
    return 1
```

| A | B |
|---|---|
| 1 | 2 |

---

[ссылка](https://example.com)
"""


def _texts(document) -> list[str]:
    return [p.text for p in document.paragraphs]


def test_markdown_to_docx_writes_file(tmp_path: Path) -> None:
    dest = tmp_path / "out.docx"
    markdown_to_docx(SAMPLE, dest, title="Sample")
    assert dest.exists() and dest.stat().st_size > 0

    document = docx.Document(str(dest))
    texts = _texts(document)
    assert "Заголовок" in texts
    # Inline emphasis collapses into a single paragraph's text.
    assert any("жирным" in t and "курсивом" in t and "кодом" in t for t in texts)
    assert "первый" in texts and "второй" in texts and "вложенный" in texts
    assert "раз" in texts and "два" in texts
    assert "Цитата текста" in texts
    assert any("def hello():" in t for t in texts)
    assert any("ссылка" in t for t in texts)


def test_markdown_to_docx_heading_levels(tmp_path: Path) -> None:
    dest = tmp_path / "headings.docx"
    markdown_to_docx("# H1\n\n## H2\n\n### H3\n", dest)
    document = docx.Document(str(dest))
    styles = {p.text: p.style.name for p in document.paragraphs if p.text}
    assert styles["H1"] == "Heading 1"
    assert styles["H2"] == "Heading 2"
    assert styles["H3"] == "Heading 3"


def test_markdown_to_docx_builds_table(tmp_path: Path) -> None:
    dest = tmp_path / "table.docx"
    markdown_to_docx("| A | B |\n|---|---|\n| 1 | 2 |\n", dest)
    document = docx.Document(str(dest))
    assert len(document.tables) == 1
    table = document.tables[0]
    assert table.rows[0].cells[0].text == "A"
    assert table.rows[1].cells[1].text == "2"


def test_bold_runs_for_table_header(tmp_path: Path) -> None:
    dest = tmp_path / "table2.docx"
    markdown_to_docx("| H |\n|---|\n| v |\n", dest)
    document = docx.Document(str(dest))
    header_cell = document.tables[0].rows[0].cells[0]
    assert all(run.bold for run in header_cell.paragraphs[0].runs)


def test_export_error_is_raised_on_bad_destination(tmp_path: Path) -> None:
    bad = tmp_path / "missing-dir" / "out.docx"
    with pytest.raises(ExportError):
        markdown_to_docx("# hi\n", bad)
