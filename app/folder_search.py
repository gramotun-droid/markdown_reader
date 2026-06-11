from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .renderer import read_text_with_fallback
from .settings import SUPPORTED_EXTENSIONS, TECHNICAL_DIRS

MAX_HITS = 500
SNIPPET_RADIUS = 40


@dataclass(frozen=True)
class SearchHit:
    path: Path
    line_number: int
    snippet: str


def search_markdown_files(folder: Path, query: str, max_hits: int = MAX_HITS) -> list[SearchHit]:
    """Case-insensitive full-text search across Markdown files in a folder tree.

    Pure (no Qt) so it can be unit-tested and run off the UI thread.
    """
    needle = query.strip().lower()
    if not needle:
        return []

    hits: list[SearchHit] = []
    for dirpath, dirnames, filenames in os.walk(folder, onerror=lambda _error: None):
        dirnames[:] = [name for name in dirnames if name not in TECHNICAL_DIRS]
        for filename in sorted(filenames):
            if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            path = Path(dirpath) / filename
            try:
                text = read_text_with_fallback(path)
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                column = line.lower().find(needle)
                if column == -1:
                    continue
                hits.append(SearchHit(path, line_number, _snippet(line, column, len(needle))))
                if len(hits) >= max_hits:
                    return hits
    return hits


def _snippet(line: str, column: int, length: int) -> str:
    start = max(0, column - SNIPPET_RADIUS)
    end = min(len(line), column + length + SNIPPET_RADIUS)
    snippet = line[start:end].strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(line) else ""
    return f"{prefix}{snippet}{suffix}"
