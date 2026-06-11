"""Enumerate filesystem roots the user can open: local and network drives plus
mounted WSL distributions.

`parse_wsl_distros` is pure and unit-tested; `available_roots` pulls live drive
info from Qt and (on Windows) shells out to ``wsl.exe`` to list distributions.
"""

from __future__ import annotations

import subprocess
import sys

# WSL distros that are implementation details, not user filesystems.
_HIDDEN_WSL = ("docker-desktop",)


def parse_wsl_distros(raw: str) -> list[str]:
    """Parse the (already decoded) output of ``wsl.exe --list --quiet``."""
    distros: list[str] = []
    for line in raw.replace("\r", "\n").split("\n"):
        name = line.replace("\x00", "").strip()
        if not name:
            continue
        if name.lower().startswith(_HIDDEN_WSL):
            continue
        distros.append(name)
    return distros


def wsl_distros() -> list[str]:
    """Names of installed WSL distributions (empty off Windows or on failure)."""
    if not sys.platform.startswith("win"):
        return []
    try:
        result = subprocess.run(
            ["wsl.exe", "--list", "--quiet"],
            capture_output=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    # wsl.exe emits UTF-16-LE.
    text = result.stdout.decode("utf-16-le", errors="ignore")
    return parse_wsl_distros(text)


def available_roots() -> list[tuple[str, str]]:
    """Return ``(label, path)`` pairs for every openable root.

    Local and mapped network drives come from Qt's drive list; WSL
    distributions are exposed via their ``\\\\wsl.localhost`` UNC paths.
    """
    from PySide6.QtCore import QDir

    roots: list[tuple[str, str]] = []
    for drive in QDir.drives():
        path = drive.absoluteFilePath()
        roots.append((_drive_label(path), path))

    for distro in wsl_distros():
        roots.append((f"WSL · {distro}", rf"\\wsl.localhost\{distro}"))

    return roots


def _drive_label(path: str) -> str:
    """Human label for a drive root, e.g. ``C:\\ (Windows)`` or ``Z:\\ (share)``."""
    from PySide6.QtCore import QDir, QStorageInfo

    native = QDir.toNativeSeparators(path)
    info = QStorageInfo(path)
    name = (info.displayName() or "").strip()
    suffix = ""
    if name and name not in {native, native.rstrip("\\/")}:
        suffix = f" ({name})"
    return f"{native}{suffix}"
