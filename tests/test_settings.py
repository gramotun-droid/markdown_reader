from pathlib import Path

from app.settings import MAX_RECENT_FILES, AppSettings


def test_remember_recent_inserts_at_front(tmp_path) -> None:
    settings = AppSettings()
    first = tmp_path / "a.md"
    second = tmp_path / "b.md"

    settings.remember_recent(first)
    settings.remember_recent(second)

    assert settings.recent_files[0] == second.resolve()
    assert settings.recent_files[1] == first.resolve()


def test_remember_recent_deduplicates(tmp_path) -> None:
    settings = AppSettings()
    path = tmp_path / "a.md"

    settings.remember_recent(path)
    settings.remember_recent(tmp_path / "b.md")
    settings.remember_recent(path)

    assert settings.recent_files.count(path.resolve()) == 1
    assert settings.recent_files[0] == path.resolve()


def test_remember_recent_caps_history() -> None:
    settings = AppSettings()
    for index in range(MAX_RECENT_FILES + 5):
        settings.remember_recent(Path(f"/tmp/file{index}.md"))

    assert len(settings.recent_files) == MAX_RECENT_FILES
