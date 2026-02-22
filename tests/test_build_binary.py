"""Tests for build_binary.py helpers and build flow."""

from types import SimpleNamespace
import importlib.util
import sys
from pathlib import Path
import pytest


def _load_build_binary_module():
    """Load build_binary.py directly from the repo root."""
    module_name = "build_binary"
    module_path = Path(__file__).resolve().parents[1] / "build_binary.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load build_binary module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build_binary_module():
    """Load build_binary module for testing.

    Returns:
        The build_binary module.

    Raises:
        RuntimeError: If module cannot be loaded.
    """
    return _load_build_binary_module()


class _RunResult(SimpleNamespace):
    """Simple subprocess result stub."""


def test_get_gdk_pixbuf_loaders_found(
    build_binary_module, monkeypatch, tmp_path
):
    """Return loaders dir and cache when found."""
    loaders_dir = str(tmp_path / "gdk-pixbuf" / "loaders")
    cache_file = str(tmp_path / "gdk-pixbuf" / "loaders.cache")

    def fake_run(*_args, **_kwargs):
        return _RunResult(returncode=0, stdout=loaders_dir + "\n")

    orig_isabs = build_binary_module.os.path.isabs

    def fake_isdir(path):
        return path == loaders_dir

    def fake_isfile(path):
        return path == cache_file

    def fake_isabs(path):
        if path in {loaders_dir, cache_file}:
            return True
        return orig_isabs(path)

    monkeypatch.setattr(
        build_binary_module.subprocess, "run", fake_run
    )
    monkeypatch.setattr(
        build_binary_module.os.path, "isdir", fake_isdir
    )
    monkeypatch.setattr(
        build_binary_module.os.path, "isfile", fake_isfile
    )
    monkeypatch.setattr(
        build_binary_module.os.path, "isabs", fake_isabs
    )

    found_dir, found_cache = (
        build_binary_module.get_gdk_pixbuf_loaders()
    )
    assert found_dir == loaders_dir
    assert found_cache == cache_file


def test_get_gdk_pixbuf_loaders_missing(
    build_binary_module, monkeypatch
):
    """Return None when loaders cannot be located."""
    monkeypatch.setattr(
        build_binary_module.shutil,
        "which",
        lambda _name: "/usr/bin/pkg-config",
    )
    monkeypatch.setattr(
        build_binary_module.subprocess,
        "run",
        lambda *_a, **_k: _RunResult(returncode=1, stdout=""),
    )
    found_dir, found_cache = (
        build_binary_module.get_gdk_pixbuf_loaders()
    )
    assert found_dir is None
    assert found_cache is None


def test_check_dependencies_installed(
    build_binary_module, monkeypatch
):
    """Skip pip install when PyInstaller is available."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda _n: object())
    calls = []

    def fake_run(*args, **_kwargs):
        calls.append(args)
        return _RunResult(returncode=0)

    monkeypatch.setattr(build_binary_module.subprocess, "run", fake_run)
    build_binary_module.check_dependencies()
    assert not calls


def test_check_dependencies_installs(
    build_binary_module, monkeypatch
):
    """Invoke pip install when PyInstaller is missing."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda _n: None)
    calls = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        return _RunResult(returncode=0)

    monkeypatch.setattr(build_binary_module.subprocess, "run", fake_run)
    build_binary_module.check_dependencies()
    assert calls
    assert calls[0][:3] == [sys.executable, "-m", "pip"]


def test_get_data_files(build_binary_module, monkeypatch, tmp_path):
    """Include VERSION, AUTHORS, and assets when present."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "VERSION").write_text("v1.2.3", encoding="utf-8")
    (tmp_path / "AUTHORS").write_text("- Test", encoding="utf-8")
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    (assets_dir / "icon.png").write_text("x", encoding="utf-8")

    data_files = build_binary_module.get_data_files()
    assert ("VERSION", ".") in data_files
    assert ("AUTHORS", ".") in data_files
    assert ("assets", "assets") in data_files


def test_build_binary_success_with_loaders(
    build_binary_module, monkeypatch, tmp_path
):
    """Build succeeds and reports when binary exists."""
    monkeypatch.chdir(tmp_path)
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    binary_path = dist_dir / "lmstudio-tray-manager"
    binary_path.write_text("bin", encoding="utf-8")

    monkeypatch.setattr(
        build_binary_module, "check_dependencies", lambda: None
    )
    loaders_dir = tmp_path / "loaders"
    loaders_dir.mkdir()
    # Dummy .so files - content is not inspected; only the glob match matters.
    (loaders_dir / "libpixbufloader-png.so").write_bytes(b"")
    (loaders_dir / "libpixbufloader-jpeg.so").write_bytes(b"")
    monkeypatch.setattr(
        build_binary_module,
        "get_gdk_pixbuf_loaders",
        lambda: (str(loaders_dir),
                 str(tmp_path / "loaders.cache")),
    )
    monkeypatch.setattr(
        build_binary_module,
        "get_hidden_imports",
        lambda: ["gi"],
    )
    monkeypatch.setattr(
        build_binary_module, "get_data_files", lambda: []
    )

    commands = []

    def fake_run(args, **_kwargs):
        commands.append(args)
        return _RunResult(returncode=0)

    monkeypatch.setattr(build_binary_module.subprocess, "run", fake_run)
    result = build_binary_module.build_binary()
    assert result == 0
    assert any("--add-binary" in cmd for cmd in commands[0])


def test_build_binary_missing_output(
    build_binary_module, monkeypatch, tmp_path
):
    """Return failure when binary is missing after build."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        build_binary_module, "check_dependencies", lambda: None
    )
    monkeypatch.setattr(
        build_binary_module,
        "get_gdk_pixbuf_loaders",
        lambda: (None, None),
    )
    monkeypatch.setattr(build_binary_module, "get_hidden_imports", lambda: [])
    monkeypatch.setattr(build_binary_module, "get_data_files", lambda: [])
    monkeypatch.setattr(
        build_binary_module.subprocess,
        "run",
        lambda *_a, **_k: _RunResult(returncode=0),
    )

    result = build_binary_module.build_binary()
    assert result == 1


def test_build_binary_failure(monkeypatch, tmp_path, build_binary_module):
    """Return failure when PyInstaller run fails."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        build_binary_module, "check_dependencies", lambda: None
    )
    monkeypatch.setattr(
        build_binary_module,
        "get_gdk_pixbuf_loaders",
        lambda: (None, None),
    )
    monkeypatch.setattr(
        build_binary_module, "get_hidden_imports", lambda: []
    )
    monkeypatch.setattr(
        build_binary_module, "get_data_files", lambda: []
    )
    monkeypatch.setattr(
        build_binary_module.subprocess,
        "run",
        lambda *_a, **_k: _RunResult(returncode=1),
    )

    result = build_binary_module.build_binary()
    assert result == 1


def test_build_binary_timeout(build_binary_module, monkeypatch):
    """Build returns 1 when subprocess times out."""
    monkeypatch.setattr(
        build_binary_module, "check_dependencies", lambda: None
    )
    monkeypatch.setattr(
        build_binary_module,
        "get_gdk_pixbuf_loaders",
        lambda: (None, None),
    )
    monkeypatch.setattr(
        build_binary_module, "get_hidden_imports", lambda: []
    )
    monkeypatch.setattr(
        build_binary_module, "get_data_files", lambda: []
    )

    def fake_run_timeout(*_a, **_k):
        raise build_binary_module.subprocess.TimeoutExpired("cmd", 3600)

    monkeypatch.setattr(
        build_binary_module.subprocess, "run", fake_run_timeout
    )

    result = build_binary_module.build_binary()
    assert result == 1
