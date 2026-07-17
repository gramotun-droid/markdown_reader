"""Import a Word (.docx) document by converting it to Markdown.

This is the counterpart of :mod:`app.export`: instead of writing a .docx from
Markdown, it reads a .docx with python-docx and emits Markdown text covering the
common constructs (headings, emphasis, bullet/numbered lists with nesting,
block quotes, tables and hyperlinks). The result is meant to be rendered and
edited like any other Markdown document.

Only the modern .docx format is supported — the legacy binary .doc format is a
different file type that python-docx cannot read.
"""

from __future__ import annotations

from pathlib import Path


class DocxImportError(RuntimeError):
    """Raised when a .docx document cannot be converted to Markdown."""


# Characters that carry meaning in Markdown and would otherwise be mangled when
# they appear verbatim in Word text.
_ESCAPE = str.maketrans({c: "\\" + c for c in "\\`*_[]"})


def _escape(text: str) -> str:
    return text.translate(_ESCAPE)


def docx_to_markdown(path: Path) -> str:
    """Convert the .docx at *path* to a Markdown string."""
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:  # pragma: no cover - only when packaging is broken
        raise DocxImportError(
            "Для открытия .docx требуется библиотека python-docx, но она недоступна."
        ) from exc

    try:
        document = Document(str(path))
    except Exception as exc:  # noqa: BLE001 - python-docx raises assorted errors
        raise DocxImportError(f"Не удалось прочитать .docx: {exc}") from exc

    blocks: list[str] = []
    for block in _iter_block_items(document, qn, Paragraph, Table):
        if isinstance(block, Paragraph):
            rendered = _paragraph_md(block, qn)
            if rendered is not None:
                blocks.append(rendered)
        else:  # Table
            blocks.append(_table_md(block, qn))

    return _join_blocks(blocks)


def _iter_block_items(document, qn, Paragraph, Table):
    """Yield paragraphs and tables in document order (python-docx exposes them
    as separate flat lists, losing their interleaving)."""
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _paragraph_md(paragraph, qn) -> str | None:
    """Markdown for a single paragraph, or ``None`` to drop it (blank spacer)."""
    text = _inline_md(paragraph, qn)
    style = (paragraph.style.name or "") if paragraph.style else ""

    heading_level = _heading_level(style)
    if heading_level:
        return f"{'#' * heading_level} {text}".rstrip() if text else None

    if "Quote" in style:
        return f"> {text}" if text else None

    bullet, level = _list_info(paragraph, style, qn)
    if bullet is not None:
        indent = "  " * level
        return f"{indent}{bullet} {text}"

    if not text.strip():
        return None
    return text


def _heading_level(style: str) -> int:
    if style == "Title":
        return 1
    if style.startswith("Heading "):
        try:
            return min(int(style.split()[1]), 6)
        except (IndexError, ValueError):
            return 0
    return 0


def _list_info(paragraph, style: str, qn) -> tuple[str | None, int]:
    """Return (marker, nesting level) for a list paragraph, else (None, 0)."""
    ordered = "Number" in style
    is_list = "List" in style
    level = 0

    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is not None:
        numPr = pPr.find(qn("w:numPr"))
        if numPr is not None:
            is_list = True
            ilvl = numPr.find(qn("w:ilvl"))
            if ilvl is not None:
                try:
                    level = int(ilvl.get(qn("w:val")) or 0)
                except ValueError:
                    level = 0

    if not is_list:
        return None, 0
    return ("1." if ordered else "-"), level


def _inline_md(paragraph, qn) -> str:
    """Render a paragraph's runs and hyperlinks to inline Markdown."""
    from docx.text.run import Run

    parts: list[str] = []
    for child in paragraph._p.iterchildren():
        if child.tag == qn("w:r"):
            parts.append(_run_md(Run(child, paragraph)))
        elif child.tag == qn("w:hyperlink"):
            inner = "".join(_run_md(Run(r, paragraph)) for r in child.findall(qn("w:r")))
            url = _hyperlink_url(child, paragraph, qn)
            parts.append(f"[{inner}]({url})" if url else inner)
    return "".join(parts).strip()


def _hyperlink_url(hyperlink, paragraph, qn) -> str:
    rid = hyperlink.get(qn("r:id"))
    if not rid:
        return ""
    rels = paragraph.part.rels
    if rid in rels:
        return rels[rid].target_ref
    return ""


def _run_md(run) -> str:
    text = run.text or ""
    if not text:
        return ""
    text = _escape(text)
    bold = bool(run.bold)
    italic = bool(run.italic)
    if bold and italic:
        return f"***{text}***"
    if bold:
        return f"**{text}**"
    if italic:
        return f"*{text}*"
    return text


def _table_md(table, qn) -> str:
    rows: list[list[str]] = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            text = " ".join(
                _inline_md(p, qn) for p in cell.paragraphs
            ).replace("|", "\\|").strip()
            cells.append(text or " ")
        rows.append(cells)

    if not rows:
        return ""

    width = max(len(r) for r in rows)
    rows = [r + [" "] * (width - len(r)) for r in rows]
    header = rows[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _join_blocks(blocks: list[str]) -> str:
    """Join block elements, keeping consecutive items of the same list type
    tight and separating everything else with a blank line."""
    out: list[str] = []
    prev_kind: str | None = None
    for block in blocks:
        kind = _list_kind(block)
        if out and not (kind is not None and kind == prev_kind):
            out.append("")
        out.append(block)
        prev_kind = kind
    return "\n".join(out).strip() + "\n"


def _list_kind(block: str) -> str | None:
    """"bullet" / "ordered" for a list item, else ``None`` (indent ignored so
    nested items of the same kind stay in one list)."""
    stripped = block.lstrip()
    if stripped.startswith("- "):
        return "bullet"
    if stripped[:2] == "1." or (stripped[:1].isdigit() and ". " in stripped[:5]):
        return "ordered"
    return None
