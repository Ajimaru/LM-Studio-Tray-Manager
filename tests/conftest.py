"""This module provides compatibility fixtures for pytest tests.

It includes an alias fixture `_monkeypatch` that returns the standard
pytest `monkeypatch` fixture, allowing legacy tests to use the expected
fixture name without modification.

It also provides `windows_module`, which imports a second copy of
`lmstudio_tray` with the platform pinned to Windows. That fixture is
opt-in by name, so the Linux and macOS tests are unaffected by it."""

import importlib.util
import os
import subprocess  # nosec B404
import sys
from pathlib import Path
from types import ModuleType

import pytest

from windows_stubs import (
    DummyPilImage,
    DummyPystrayModule,
    completed,
    install_sync_threads,
)


@pytest.fixture(autouse=True)
def _block_real_process_signals(monkeypatch):
    """Stop tests from signalling processes outside the test session.

    ``kill_existing_instances()`` resolves targets with
    ``pgrep -f lmstudio_tray.py``. During a test run that pattern also
    matches pytest's own command line (``pytest tests/test_lmstudio_tray.py``)
    as well as any tray app the developer happens to be running, so a test
    reaching the real ``os.kill`` terminates the test session itself - the
    run dies with exit code 144 partway through, and a locally running app
    disappears with it.

    Tests that care about signalling still override ``os.kill`` themselves;
    this fixture only guarantees that an unmocked path cannot escape.
    """
    def blocked_kill(pid, sig):
        """Swallow the signal instead of delivering it to a real process."""
        _ = (pid, sig)
        return None

    monkeypatch.setattr(os, "kill", blocked_kill)
    yield


@pytest.fixture
def _monkeypatch(monkeypatch):
    """Compatibility alias for tests expecting `_monkeypatch`.

    Many legacy tests refer to `_monkeypatch`.  Provide a simple alias that
    returns the real ``monkeypatch`` fixture so both names work.
    """
    return monkeypatch


@pytest.fixture
def _tmp_path(tmp_path):
    """Alias for pytest's ``tmp_path``.

    A handful of legacy tests expect a fixture called ``_tmp_path``; this
    alias keeps them happy without forcing every test to be rewritten.

    Returns:
        pathlib.Path: the temporary directory provided by pytest.
    """
    return tmp_path


@pytest.fixture(name="windows_sync_threads")
def windows_sync_threads_fixture(monkeypatch):
    """Run worker threads inline and record timers instead of firing them.

    Opt-in rather than autouse: the Linux and macOS suites bring their
    own thread handling, and replacing it globally would change what they
    exercise.
    """
    install_sync_threads(monkeypatch)


@pytest.fixture(name="windows_module")
def windows_module_fixture(monkeypatch, tmp_path):
    """Load lmstudio_tray as if running on Windows, with GUI stubs.

    Mirrors the Linux and macOS module fixtures in
    ``test_lmstudio_tray.py``: pin ``sys.platform`` *before* the import so
    the module-level platform flags derive correctly, hide the other
    platforms' GUI libraries, and keep subprocess calls inert.

    Yields:
        The imported module, flavoured for Windows.
    """
    pystray_stub = DummyPystrayModule()
    pil_image_stub = DummyPilImage()
    pil_pkg = ModuleType("PIL")
    setattr(pil_pkg, "Image", pil_image_stub)

    monkeypatch.setitem(sys.modules, "pystray", pystray_stub)
    monkeypatch.setitem(sys.modules, "PIL", pil_pkg)
    monkeypatch.setitem(sys.modules, "PIL.Image", pil_image_stub)
    monkeypatch.setitem(sys.modules, "gi", None)
    monkeypatch.setitem(sys.modules, "rumps", None)

    def safe_run(*_args, **_kwargs):
        """Return a safe default subprocess result during import."""
        return completed(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", safe_run)
    monkeypatch.setattr(os, "getpid", lambda: 99999)

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))

    module_name = "lmstudio_tray_windows"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name,
        str(Path(__file__).resolve().parents[1] / "lmstudio_tray.py"),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to create module spec or loader")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    # sys.platform is pinned only across the import, which is where the
    # module derives IS_WINDOWS and its path constants. Leaving it pinned
    # for the whole test breaks the stdlib on a POSIX host: shutil.which()
    # re-reads sys.platform on every call and would take its Windows
    # branch, reaching into _winapi, which is None off Windows.
    original_platform = sys.platform
    sys.platform = "win32"
    try:
        spec.loader.exec_module(module)
    finally:
        sys.platform = original_platform

    monkeypatch.setattr(module, "_pystray_lib", pystray_stub)
    monkeypatch.setattr(module, "_pil_image", pil_image_stub)

    yield module

    sys.modules.pop(module_name, None)
