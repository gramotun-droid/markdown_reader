from app.drives import parse_wsl_distros


def test_parse_wsl_distros_basic():
    assert parse_wsl_distros("Ubuntu\nDebian\n") == ["Ubuntu", "Debian"]


def test_parse_wsl_distros_strips_blank_and_crlf():
    assert parse_wsl_distros("Ubuntu\r\n\r\nDebian\r\n") == ["Ubuntu", "Debian"]


def test_parse_wsl_distros_drops_stray_nulls():
    # wsl.exe output decoded loosely can carry stray NUL bytes.
    assert parse_wsl_distros("U\x00buntu\x00\n") == ["Ubuntu"]


def test_parse_wsl_distros_hides_docker_internal():
    raw = "Ubuntu\ndocker-desktop\ndocker-desktop-data\n"
    assert parse_wsl_distros(raw) == ["Ubuntu"]


def test_parse_wsl_distros_empty():
    assert parse_wsl_distros("") == []
