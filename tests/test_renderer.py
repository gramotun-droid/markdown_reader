from app.renderer import MarkdownRenderer, collect_headings, read_text_with_fallback


def test_renderer_outputs_common_markdown_features() -> None:
    renderer = MarkdownRenderer()

    rendered = renderer.render_text(
        """# Title

**Bold** and *italic*.

| Name | Value |
| --- | --- |
| A | 1 |

```python
print("hello")
```

[Next](next.md)
""",
        title="sample.md",
    )

    assert '<h1 id="title">Title' in rendered.html
    assert "<strong>Bold</strong>" in rendered.html
    assert "<table>" in rendered.html
    assert "highlight" in rendered.html
    assert 'href="next.md"' in rendered.html


def test_renderer_escapes_raw_html() -> None:
    rendered = MarkdownRenderer().render_text("<script>alert(1)</script>", title="x.md")

    assert "<script>alert(1)</script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html


def test_renderer_handles_fence_without_language() -> None:
    rendered = MarkdownRenderer().render_text(
        """# Diagram

```
plain text block
```
""",
        title="plain.md",
    )

    assert "plain text block" in rendered.html
    assert "highlight" in rendered.html


def test_read_text_with_cp1251_fallback(tmp_path) -> None:
    path = tmp_path / "ru.md"
    path.write_bytes("Привет".encode("cp1251"))

    assert read_text_with_fallback(path) == "Привет"


def test_headings_get_anchor_ids() -> None:
    rendered = MarkdownRenderer().render_text("# Hello World\n\ntext", title="x.md")

    assert 'id="hello-world"' in rendered.html
    assert 'class="header-anchor"' in rendered.html


def test_toc_built_for_multiple_headings() -> None:
    rendered = MarkdownRenderer().render_text("# A\n\n## B\n\n## C\n", title="x.md")

    assert '<details class="toc"' in rendered.html
    assert 'href="#b"' in rendered.html


def test_no_toc_for_single_heading() -> None:
    rendered = MarkdownRenderer().render_text("# Only\n\ntext", title="x.md")

    assert '<details class="toc"' not in rendered.html


def test_collect_headings_returns_levels_and_slugs() -> None:
    renderer = MarkdownRenderer()
    tokens = renderer.markdown.parse("# Title\n\n## Sub", {})
    headings = collect_headings(tokens)

    assert headings == [(1, "Title", "title"), (2, "Sub", "sub")]


def test_dark_theme_uses_dark_pygments_style() -> None:
    light = MarkdownRenderer(theme="light").render_text("```python\nx=1\n```", title="x")
    dark = MarkdownRenderer(theme="dark").render_text("```python\nx=1\n```", title="x")

    assert light.html != dark.html


def test_set_theme_switches_css() -> None:
    renderer = MarkdownRenderer(theme="light")
    assert renderer.theme == "light"
    renderer.set_theme("dark")
    assert renderer.theme == "dark"
    assert "color-scheme: dark" in renderer.render_text("# x", title="x").html
