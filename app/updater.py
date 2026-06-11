"""Self-update support: check the GitHub Releases API and download the
Windows installer.

The pure helpers (`parse_version`, `is_newer`, `parse_release`) are unit-tested
without network access; the network functions are thin urllib wrappers used by
the background workers in :mod:`app.window`.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app import __version__

REPO = "gramotun-droid/markdown_reader"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
INSTALLER_ASSET = "MdReader-Setup.exe"
_USER_AGENT = f"MdReader/{__version__}"


@dataclass(frozen=True)
class UpdateInfo:
    """A release newer than the running build (or just the latest release)."""

    version: str  # normalized numeric form, e.g. "1.0.0"
    tag: str  # raw tag, e.g. "v1.0.0"
    html_url: str  # release page (browser fallback)
    asset_url: str | None  # direct download URL of the installer, if attached
    asset_name: str | None


def parse_version(text: str) -> tuple[int, ...]:
    """Turn ``v1.2.3`` / ``1.2`` / ``1.2.3-rc1`` into a comparable tuple.

    Leading ``v`` is dropped and any non-numeric suffix (pre-release/build
    metadata) is ignored, so ``1.0.0`` and ``1.0.0-rc1`` compare as equal heads.
    """
    head = re.split(r"[-+ ]", text.strip().lstrip("vV"), maxsplit=1)[0]
    parts: list[int] = []
    for chunk in head.split("."):
        if chunk.isdigit():
            parts.append(int(chunk))
        else:
            break
    return tuple(parts) or (0,)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def parse_release(payload: dict) -> UpdateInfo:
    """Build an :class:`UpdateInfo` from a GitHub ``releases/latest`` payload."""
    tag = payload.get("tag_name") or payload.get("name") or ""
    asset_url: str | None = None
    asset_name: str | None = None
    for asset in payload.get("assets") or []:
        if asset.get("name") == INSTALLER_ASSET:
            asset_url = asset.get("browser_download_url")
            asset_name = asset.get("name")
            break
    return UpdateInfo(
        version=".".join(str(p) for p in parse_version(tag)),
        tag=tag,
        html_url=payload.get("html_url") or RELEASES_PAGE,
        asset_url=asset_url,
        asset_name=asset_name,
    )


def fetch_latest_release(timeout: float = 10.0) -> UpdateInfo:
    request = urllib.request.Request(
        RELEASES_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (https only)
        payload = json.load(response)
    return parse_release(payload)


def check_for_update(current: str = __version__, timeout: float = 10.0) -> UpdateInfo | None:
    """Return release info if a newer version is published, else ``None``.

    Raises on network/parse errors so the caller can decide whether to surface
    the failure (manual check) or stay silent (startup check).
    """
    info = fetch_latest_release(timeout=timeout)
    if info.tag and is_newer(info.version, current):
        return info
    return None


def download_asset(
    url: str,
    dest: Path,
    *,
    progress: Callable[[int], None] | None = None,
    timeout: float = 60.0,
) -> Path:
    """Stream ``url`` into ``dest``, reporting 0-100% via ``progress``."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        total = int(response.getheader("Content-Length") or 0)
        read = 0
        with open(dest, "wb") as handle:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                read += len(chunk)
                if progress and total:
                    progress(min(100, int(read * 100 / total)))
    if progress:
        progress(100)
    return dest


def can_self_install() -> bool:
    """True only for a frozen Windows build, where running the installer makes
    sense. From source or on other platforms we fall back to the release page.
    """
    return sys.platform.startswith("win") and bool(getattr(sys, "frozen", False))
