from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path

from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

from .settings import resource_path

# Pygments style per UI theme so code blocks match the surrounding page.
PYGMENTS_STYLES = {"light": "default", "dark": "github-dark"}
TOC_MIN_HEADINGS = 2
TOC_MAX_LEVEL = 3


class MarkdownRenderError(RuntimeError):
    pass


class PygmentsRenderer:
    def __init__(self, formatter: HtmlFormatter) -> None:
        self.formatter = formatter

    def __call__(self, code: str, lang: str, attrs: str) -> str:
        language_parts = (lang or "").strip().split(maxsplit=1)
        language = language_parts[0] if language_parts else ""
        try:
            lexer = get_lexer_by_name(language) if language else TextLexer()
        except ClassNotFound:
            lexer = TextLexer()

        return highlight(code, lexer, self.formatter)


@dataclass(frozen=True)
class RenderedDocument:
    html: str
    title: str


class MarkdownRenderer:
    def __init__(self, theme: str = "light") -> None:
        self._template = resource_path("templates", "page.html").read_text(encoding="utf-8")
        self.set_theme(theme)

    def set_theme(self, theme: str) -> None:
        self.theme = theme if theme in PYGMENTS_STYLES else "light"
        style = PYGMENTS_STYLES[self.theme]
        formatter = HtmlFormatter(nowrap=False, style=style)
        self._pygments_css = formatter.get_style_defs(".highlight")
        self._theme_css = self._load_theme_css()
        self.markdown = (
            MarkdownIt(
                "commonmark",
                {
                    "html": False,
                    "linkify": True,
                    "typographer": True,
                    "highlight": PygmentsRenderer(formatter),
                },
            )
            .enable("table")
            .enable("strikethrough")
            .use(tasklists_plugin, enabled=True)
            .use(anchors_plugin, max_level=TOC_MAX_LEVEL, permalink=True, permalinkSymbol="#")
        )

    def render_file(self, path: Path) -> RenderedDocument:
        markdown_text = read_text_with_fallback(path)
        return self.render_text(markdown_text, title=path.name)

    def render_text(self, markdown_text: str, title: str = "Document") -> RenderedDocument:
        try:
            env: dict = {}
            tokens = self.markdown.parse(markdown_text, env)
            body = self.markdown.renderer.render(tokens, self.markdown.options, env)
            toc = self._build_toc(tokens)
            html = self._template.format(
                title=escape(title),
                css=self._theme_css,
                pygments_css=self._pygments_css,
                toc=toc,
                content=body,
            )
            return RenderedDocument(html=html, title=title)
        except Exception as exc:  # noqa: BLE001
            raise MarkdownRenderError(f"Не удалось отрендерить Markdown: {exc}") from exc

    def _build_toc(self, tokens) -> str:
        headings = collect_headings(tokens)
        if len(headings) < TOC_MIN_HEADINGS:
            return ""

        top_level = min(level for level, _, _ in headings)
        items = []
        for level, text, slug in headings:
            indent = level - top_level
            items.append(
                f'<li class="toc-l{indent}"><a href="#{escape(slug, quote=True)}">{escape(text)}</a></li>'
            )
        return (
            '<details class="toc" open>'
            "<summary>Содержание</summary>"
            f'<ul>{"".join(items)}</ul>'
            "</details>"
        )

    def _load_theme_css(self) -> str:
        css_name = "style-dark.css" if self.theme == "dark" else "style-light.css"
        return resource_path("assets", css_name).read_text(encoding="utf-8")


def collect_headings(tokens) -> list[tuple[int, str, str]]:
    """Extract (level, text, slug) for headings carrying an anchor id."""
    headings: list[tuple[int, str, str]] = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        slug = token.attrGet("id")
        if not slug:
            continue
        level = int(token.tag[1])
        inline = tokens[index + 1] if index + 1 < len(tokens) else None
        text = inline.content if inline is not None else ""
        headings.append((level, text, slug))
    return headings


def read_text_with_fallback(path: Path) -> str:
    errors: list[str] = []
    for encoding in ("utf-8", "utf-8-sig", "cp1251"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}: {exc}")
        except OSError:
            raise

    raise UnicodeDecodeError(
        "utf-8",
        b"",
        0,
        1,
        "Не удалось прочитать файл как utf-8, utf-8-sig или cp1251. " + "; ".join(errors),
    )
