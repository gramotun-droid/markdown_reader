from app.updater import INSTALLER_ASSET, is_newer, parse_release, parse_version


def test_parse_version_strips_v_and_suffix():
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("1.0") == (1, 0)
    assert parse_version("v2.0.0-rc1") == (2, 0, 0)
    assert parse_version("garbage") == (0,)


def test_is_newer_compares_numerically():
    assert is_newer("1.0.1", "1.0.0")
    assert is_newer("v1.1.0", "1.0.9")
    assert is_newer("2.0.0", "1.9.9")
    assert not is_newer("1.0.0", "1.0.0")
    assert not is_newer("1.0.0", "1.0.1")
    # Pre-release of the same head is not "newer" than the release.
    assert not is_newer("1.0.0-rc1", "1.0.0")


def test_parse_release_picks_installer_asset():
    payload = {
        "tag_name": "v1.0.0",
        "html_url": "https://github.com/gramotun-droid/markdown_reader/releases/tag/v1.0.0",
        "assets": [
            {"name": "MdReader-windows.zip", "browser_download_url": "https://example/zip"},
            {"name": INSTALLER_ASSET, "browser_download_url": "https://example/setup.exe"},
        ],
    }
    info = parse_release(payload)
    assert info.version == "1.0.0"
    assert info.tag == "v1.0.0"
    assert info.asset_name == INSTALLER_ASSET
    assert info.asset_url == "https://example/setup.exe"


def test_parse_release_without_installer_asset():
    payload = {"tag_name": "v0.9.0", "assets": []}
    info = parse_release(payload)
    assert info.version == "0.9.0"
    assert info.asset_url is None
    assert info.html_url.endswith("/releases/latest")
