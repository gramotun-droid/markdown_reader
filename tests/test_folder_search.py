from app.folder_search import search_markdown_files


def _make_wiki(root):
    (root / "a.md").write_text("# Alpha\n\nthe quick brown fox\n", encoding="utf-8")
    (root / "b.markdown").write_text("nothing matching here\n", encoding="utf-8")
    sub = root / "sub"
    sub.mkdir()
    (sub / "c.md").write_text("another quick line\n", encoding="utf-8")
    (root / "notes.txt").write_text("quick but not markdown\n", encoding="utf-8")
    skip = root / "node_modules"
    skip.mkdir()
    (skip / "d.md").write_text("quick inside ignored dir\n", encoding="utf-8")


def test_search_finds_matches_across_tree(tmp_path) -> None:
    _make_wiki(tmp_path)

    hits = search_markdown_files(tmp_path, "quick")

    found = {hit.path.name for hit in hits}
    assert found == {"a.md", "c.md"}


def test_search_is_case_insensitive(tmp_path) -> None:
    _make_wiki(tmp_path)

    assert search_markdown_files(tmp_path, "QUICK")


def test_search_skips_non_markdown_and_technical_dirs(tmp_path) -> None:
    _make_wiki(tmp_path)

    names = {hit.path.name for hit in search_markdown_files(tmp_path, "quick")}
    assert "notes.txt" not in names
    assert "d.md" not in names


def test_blank_query_returns_nothing(tmp_path) -> None:
    _make_wiki(tmp_path)

    assert search_markdown_files(tmp_path, "   ") == []


def test_max_hits_is_respected(tmp_path) -> None:
    (tmp_path / "many.md").write_text("hit\n" * 50, encoding="utf-8")

    assert len(search_markdown_files(tmp_path, "hit", max_hits=10)) == 10
