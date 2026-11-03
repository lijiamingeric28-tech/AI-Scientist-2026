import socket

import pytest

from astroquery_ai.api import desktop, launcher


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
