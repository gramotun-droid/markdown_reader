from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import __version__  # noqa: E402
from app.icon import app_icon  # noqa: E402
from app.settings import APP_NAME, ORG_NAME  # noqa: E402
from app.single_instance import SingleInstance  # noqa: E402
from app.window import MainWindow  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mdreader",
        description="MD Reader — просмотрщик и редактор Markdown-файлов и локальных wiki.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="Файл .md/.markdown или папка wiki для открытия в окне.",
    )
    parser.add_argument(
        "--theme",
        choices=["light", "dark"],
        help="Тема оформления при запуске.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} {__version__}",
    )
    return parser


def _resolve_path(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return str(Path(raw).expanduser().resolve())
    except OSError:
        return raw


def _handle_incoming(window: MainWindow, payload: str) -> None:
    # A second instance forwarded a request: open the file (if any) and bring
    # the existing window to the front instead of starting a new copy.
    if payload:
        window.open_start_path(payload)
    window._restore_window()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)

    QApplication.setOrganizationName(ORG_NAME)
    QApplication.setApplicationName(APP_NAME)

    app = QApplication(sys.argv[:1])
    app.setWindowIcon(app_icon())

    # If another instance is already running, hand off the file and exit so the
    # document opens as a new tab there rather than in a second window.
    instance = SingleInstance()
    if not instance.try_become_primary():
        instance.send_to_primary(_resolve_path(args.path))
        return 0

    window = MainWindow()
    instance.message_received.connect(lambda payload: _handle_incoming(window, payload))
    if args.theme and args.theme != window.renderer.theme:
        window.toggle_theme()
    window.show()

    if args.path:
        window.open_start_path(args.path)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
