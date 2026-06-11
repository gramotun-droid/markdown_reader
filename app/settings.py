from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "MD Reader"
ORG_NAME = "MdReader"
SUPPORTED_EXTENSIONS = {".md", ".markdown"}
MAX_RECENT_FILES = 12
TECHNICAL_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv", "build", "dist"}


@dataclass
class AppSettings:
    last_path: Path | None = None
    zoom_factor: float = 1.0
    theme: str = "light"
    recent_files: list[Path] = field(default_factory=list)
    check_updates_on_start: bool = True

    @classmethod
    def load(cls) -> AppSettings:
        from PySide6.QtCore import QSettings

        settings = QSettings(ORG_NAME, APP_NAME)
        raw_last_path = settings.value("last_path", "", str)
        raw_zoom = settings.value("zoom_factor", 1.0, float)
        theme = settings.value("theme", "light", str)
        raw_recent = settings.value("recent_files", [], list) or []
        check_updates = settings.value("check_updates_on_start", True, bool)

        last_path = Path(raw_last_path) if raw_last_path else None
        zoom_factor = float(raw_zoom or 1.0)
        if zoom_factor < 0.25 or zoom_factor > 3.0:
            zoom_factor = 1.0

        if theme not in {"light", "dark"}:
            theme = "light"

        recent_files = [Path(item) for item in raw_recent if item]

        return cls(
            last_path=last_path,
            zoom_factor=zoom_factor,
            theme=theme,
            recent_files=recent_files,
            check_updates_on_start=bool(check_updates),
        )

    def save(self) -> None:
        from PySide6.QtCore import QSettings

        settings = QSettings(ORG_NAME, APP_NAME)
        settings.setValue("last_path", str(self.last_path) if self.last_path else "")
        settings.setValue("zoom_factor", self.zoom_factor)
        settings.setValue("theme", self.theme)
        settings.setValue("recent_files", [str(path) for path in self.recent_files])
        settings.setValue("check_updates_on_start", self.check_updates_on_start)

    def remember_recent(self, path: Path) -> None:
        resolved = path.resolve()
        self.recent_files = [item for item in self.recent_files if item != resolved]
        self.recent_files.insert(0, resolved)
        del self.recent_files[MAX_RECENT_FILES:]


def resource_path(*parts: str) -> Path:
    return Path(__file__).resolve().parent.joinpath(*parts)
