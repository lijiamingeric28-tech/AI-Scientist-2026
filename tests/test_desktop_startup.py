import socket

import pytest

from astroquery_ai.api import desktop, launcher
from astroquery_ai.runtime import paths


def test_window_fits_the_usable_desktop():
    geometry = desktop.window_geometry(1366, 728)
    assert geometry["maximized"] and geometry["height"] < 728
    assert geometry["min_size"][1] <= geometry["height"]
    large = desktop.window_geometry(1920, 1040)
    assert not large["maximized"] and (large["width"], large["height"]) == desktop.WINDOW_SIZE


def test_occupied_preferred_port_uses_and_keeps_another_socket(monkeypatch):
    with socket.socket() as other:
        other.bind((desktop.HOST, 0))
        occupied = other.getsockname()[1]
        monkeypatch.setenv("ASTROQUERY_PORT", str(occupied))
        with desktop.desktop_socket(desktop.HOST, None) as reserved:
            actual = reserved.getsockname()[1]
            assert actual != occupied
            with pytest.raises(RuntimeError):
                desktop.desktop_socket(desktop.HOST, actual)
        with desktop.desktop_socket(desktop.HOST, actual) as available:
            assert available.getsockname()[1] == actual


def test_double_click_leaves_port_selection_to_desktop(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(launcher.sys, "argv", ["AstroQueryAI.exe", "--data-root", str(tmp_path)])
    monkeypatch.setenv("ASTROQUERY_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(desktop, "run_embedded", lambda **kwargs: called.append(kwargs))
    launcher.main()
    assert called == [{"port": None}]


def test_flattened_checkout_reads_existing_user_data_and_prefers_new_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "product_root", lambda: tmp_path)
    monkeypatch.delenv("ASTROQUERY_DATA_ROOT", raising=False)
    monkeypatch.delenv("ASTROQUERY_PATHS_FILE", raising=False)
    old = tmp_path / "AstroQuery"
    old_data = old / "runtime-data"
    old_data.mkdir(parents=True)
    (old / ".env").touch()
    old_config = old / "paths.local.json"

    assert paths.data_root() == old_data
    assert paths.dotenv_file() == old / ".env"
    old_config.write_text(
        '{"data_root": "runtime-data", "dotenv_file": ".env", "build_root": "local-build"}',
        encoding="utf-8",
    )
    assert paths.data_root() == old_data
    assert paths.dotenv_file() == old / ".env"
    assert paths.build_root() == old / "local-build"

    new_data = tmp_path / "runtime-data"
    new_data.mkdir()
    (tmp_path / ".env").touch()
    (tmp_path / "paths.local.json").write_text("{}", encoding="utf-8")
    assert paths.data_root() == new_data
    assert paths.dotenv_file() == tmp_path / ".env"
    assert paths.local_paths() == {}
