"""Tests for build_binary.py helpers and build flow."""

from types import SimpleNamespace
import importlib.util
import sys
from pathlib import Path
import pytest


def _load_build_binary_module():
    """Load and return the build_binary module from the repository root.

    Attempts to import the file build_binary.py located one directory
    above this test package and returns the loaded module object.

    Returns:
        module: The imported `build_binary` module object.

    Raises:
        RuntimeError: If the module spec or loader cannot be obtained
            and the module cannot be loaded.
    """
    module_name = "build_binary"
    module_path = Path(__file__).resolve().parents[1] / "build_binary.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(
            "Failed to load build_binary module"
        )  # noqa: TRY003
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module", name="build_binary_module")
def fixture_build_binary_module():
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


def test_get_data_files(build_binary_module):
    """Include VERSION, AUTHORS, and assets when present."""
    # get_data_files returns absolute paths from the project dir
    # Just verify the function returns tuples with correct destinations
    data_files = build_binary_module.get_data_files()

    # VERSION file should map to "."
    assert any(
        dest == "." and Path(src).name == "VERSION"
        for src, dest in data_files
    )
    # AUTHORS file should map to "."
    assert any(
        dest == "." and Path(src).name == "AUTHORS"
        for src, dest in data_files
    )
    # assets directory should map to "assets"
    assert any(
        dest == "assets" and Path(src).name == "assets"
        for src, dest in data_files
    )


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


def test_build_binary_loaders_without_cache(
    build_binary_module, monkeypatch, tmp_path
):
    """Loader .so binaries are bundled even when loaders.cache is absent."""
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
    (loaders_dir / "libpixbufloader-png.so").write_bytes(b"")
    monkeypatch.setattr(
        build_binary_module,
        "get_gdk_pixbuf_loaders",
        lambda: (str(loaders_dir), None),
    )
    monkeypatch.setattr(
        build_binary_module, "get_hidden_imports", lambda: []
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
    pyinstaller_cmd = commands[0]
    assert any("--add-binary" in arg for arg in pyinstaller_cmd)
    has_cache_data = any(
        "--add-data" in arg and "loaders.cache" in str(arg)
        for arg in pyinstaller_cmd
    )
    assert not has_cache_data


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


def test_get_gdk_pixbuf_loaders_no_pkg_config(
    build_binary_module, monkeypatch
):
    """Return None when pkg-config is not found and fallback fails."""
    # Mock both shutil.which and subprocess.run to ensure failure
    monkeypatch.setattr(
        build_binary_module.shutil, "which", lambda _n: None
    )
    
    def fake_run_fail(*_args, **_kwargs):
        # pkg-config fallback attempt fails
        return _RunResult(returncode=1, stdout="")
    
    monkeypatch.setattr(
        build_binary_module.subprocess, "run", fake_run_fail
    )
    
    found_dir, found_cache = (
        build_binary_module.get_gdk_pixbuf_loaders()
    )
    assert found_dir is None
    assert found_cache is None


def test_get_gdk_pixbuf_loaders_subprocess_error(
    build_binary_module, monkeypatch
):
    """Return None when subprocess raises an error."""
    monkeypatch.setattr(
        build_binary_module.shutil,
        "which",
        lambda _n: "/usr/bin/pkg-config",
    )

    def fake_run_error(*_a, **_k):
        raise build_binary_module.subprocess.SubprocessError("test error")

    monkeypatch.setattr(
        build_binary_module.subprocess, "run", fake_run_error
    )
    found_dir, found_cache = (
        build_binary_module.get_gdk_pixbuf_loaders()
    )
    assert found_dir is None
    assert found_cache is None


def test_get_gdk_pixbuf_loaders_cache_missing(
    build_binary_module, monkeypatch, tmp_path
):
    """Return loaders dir when found but cache is missing."""
    loaders_dir = str(tmp_path / "gdk-pixbuf" / "loaders")

    def fake_run(*_args, **_kwargs):
        return _RunResult(returncode=0, stdout=loaders_dir + "\n")

    def fake_isdir(path):
        return path == loaders_dir

    def fake_isfile(path):
        return False  # cache_file does not exist

    orig_isabs = build_binary_module.os.path.isabs

    def fake_isabs(path):
        if path == loaders_dir:
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
    assert found_cache is None


def test_validate_pyinstaller_cmd_invalid_type(build_binary_module):
    """Validate raises ValueError for non-list command."""
    with pytest.raises(ValueError, match="must be a non-empty list"):
        build_binary_module.validate_pyinstaller_cmd("not a list")


def test_validate_pyinstaller_cmd_empty_list(build_binary_module):
    """Validate raises ValueError for empty list."""
    with pytest.raises(ValueError, match="must be a non-empty list"):
        build_binary_module.validate_pyinstaller_cmd([])


def test_validate_pyinstaller_cmd_wrong_prefix(build_binary_module):
    """Validate raises ValueError when command prefix is wrong."""
    cmd = ["false", "-m", "PyInstaller"]
    with pytest.raises(ValueError, match="not trusted"):
        build_binary_module.validate_pyinstaller_cmd(cmd)


def test_validate_pyinstaller_cmd_non_string_arg(build_binary_module):
    """Validate raises ValueError for non-string arguments."""
    cmd = [
        build_binary_module.sys.executable,
        "-m",
        "PyInstaller",
        123,  # non-string arg
    ]
    with pytest.raises(ValueError, match="must be strings"):
        build_binary_module.validate_pyinstaller_cmd(cmd)


def test_validate_pyinstaller_cmd_null_byte(build_binary_module):
    """Validate raises ValueError for null bytes in arguments."""
    cmd = [
        build_binary_module.sys.executable,
        "-m",
        "PyInstaller",
        "arg\x00with\x00nulls",
    ]
    with pytest.raises(ValueError, match="null bytes"):
        build_binary_module.validate_pyinstaller_cmd(cmd)


def test_validate_pyinstaller_cmd_missing_data_value(build_binary_module):
    """Validate raises ValueError when --add-data has no value."""
    cmd = [
        build_binary_module.sys.executable,
        "-m",
        "PyInstaller",
        "--add-data",
        # missing value (end of list)
    ]
    with pytest.raises(ValueError, match="Missing value"):
        build_binary_module.validate_pyinstaller_cmd(cmd)


def test_validate_pyinstaller_cmd_invalid_data_value(build_binary_module):
    """Validate raises ValueError when --add-data value lacks pathsep."""
    cmd = [
        build_binary_module.sys.executable,
        "-m",
        "PyInstaller",
        "--add-data",
        "invalid_format",  # missing os.pathsep separator
    ]
    with pytest.raises(ValueError, match="Invalid PyInstaller data"):
        build_binary_module.validate_pyinstaller_cmd(cmd)


def test_validate_pyinstaller_cmd_valid(build_binary_module):
    """Validate accepts valid PyInstaller command."""
    import os
    cmd = [
        build_binary_module.sys.executable,
        "-m",
        "PyInstaller",
        "--add-data",
        f"/src{os.pathsep}/dest",
    ]
    # Should not raise
    build_binary_module.validate_pyinstaller_cmd(cmd)


def test_build_binary_with_loaders_deduplication(
    build_binary_module, monkeypatch, tmp_path
):
    """Build deduplicates .so files by real path."""
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
    # Create real file and symlink to it
    real_file = loaders_dir / "libpixbufloader-png.so.1.0"
    real_file.write_bytes(b"")
    symlink = loaders_dir / "libpixbufloader-png.so"
    symlink.symlink_to(real_file)
    
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
    
    # Verify only one --add-binary for the real file
    cmd = commands[0]
    binary_indices = [i for i, x in enumerate(cmd) if x == "--add-binary"]
    # Should be 1 (symlink and target deduplicated)
    assert len(binary_indices) == 1


def test_check_dependencies_not_found(
    build_binary_module, monkeypatch
):
    """Exit when requirements-build.txt is not found."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda _n: None)
    monkeypatch.setattr(
        build_binary_module.Path,
        "is_file",
        lambda self: False,
    )
    with pytest.raises(SystemExit) as exc_info:
        build_binary_module.check_dependencies()
    assert exc_info.value.code == 1


def test_check_dependencies_path_escape(
    build_binary_module, monkeypatch, tmp_path
):
    """Exit when requirements-build.txt path escapes project directory."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda _n: None)
    
    # Create a requirements file outside project root
    outside_file = tmp_path / "requirements-build.txt"
    outside_file.write_text("dummy")
    
    # Mock Path to simulate a path escape
    original_path = build_binary_module.Path
    
    class MockPath:
        def __init__(self, *args, **kwargs):
            self._path = original_path(*args, **kwargs)
        
        def is_file(self):
            return self._path.is_file() if hasattr(self._path, 'is_file') else True
        
        def resolve(self):
            mock = MockPath()
            mock._path = self._path.resolve() if hasattr(self._path, 'resolve') else self._path
            return mock
        
        def is_relative_to(self, other):
            # Always return False to simulate path escape
            return False
        
        def __truediv__(self, other):
            mock = MockPath()
            result = self._path / other if hasattr(self._path, '__truediv__') else self._path
            mock._path = result
            return mock
        
        @property
        def parent(self):
            mock = MockPath()
            mock._path = self._path.parent if hasattr(self._path, 'parent') else self._path
            return mock
    
    monkeypatch.setattr(
        build_binary_module, "Path", MockPath
    )
    
    with pytest.raises(SystemExit) as exc_info:
        build_binary_module.check_dependencies()
    assert exc_info.value.code == 1


def test_check_dependencies_pip_install_fails(
    build_binary_module, monkeypatch
):
    """Exit when pip install fails."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda _n: None)
    
    def fake_run_error(*args, **_kwargs):
        raise build_binary_module.subprocess.CalledProcessError(
            1, args[0]
        )
    
    monkeypatch.setattr(
        build_binary_module.subprocess, "run", fake_run_error
    )
    
    with pytest.raises(SystemExit) as exc_info:
        build_binary_module.check_dependencies()
    assert exc_info.value.code == 1


def test_check_dependencies_pip_oserror(
    build_binary_module, monkeypatch
):
    """Exit when pip command raises OSError."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda _n: None)
    
    def fake_run_error(*_args, **_kwargs):
        raise OSError("Command not found")
    
    monkeypatch.setattr(
        build_binary_module.subprocess, "run", fake_run_error
    )
    
    with pytest.raises(SystemExit) as exc_info:
        build_binary_module.check_dependencies()
    assert exc_info.value.code == 1


def test_build_binary_symlink_chain_deduplication(
    build_binary_module, monkeypatch, tmp_path
):
    """
    Verify deduplication works with symlink chains.
    
    Tests a realistic scenario where GdkPixbuf loaders have symlink chains
    like: lib.so -> lib.so.1 -> lib.so.1.0. The deduplication logic should
    resolve all symlinks to the same real file and include it only once.
    
    This prevents runtime loading errors where GdkPixbuf might expect certain
    filenames while the binary package contains only the canonical version.
    """
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
    
    # Create realistic symlink chain: lib.so -> lib.so.1 -> lib.so.1.0
    # All should resolve to the same real file
    real_png = loaders_dir / "libpixbufloader-png.so.1.0"
    real_png.write_bytes(b"fake_png_loader")
    
    # Create symlink chain
    sym_png_1 = loaders_dir / "libpixbufloader-png.so.1"
    sym_png_1.symlink_to(real_png)
    
    sym_png = loaders_dir / "libpixbufloader-png.so"
    sym_png.symlink_to(sym_png_1)
    
    # Add another unrelated loader without symlinks
    real_jpeg = loaders_dir / "libpixbufloader-jpeg.so"
    real_jpeg.write_bytes(b"fake_jpeg_loader")
    
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
    
    # Verify command structure
    cmd = commands[0]
    binary_indices = [i for i, x in enumerate(cmd) if x == "--add-binary"]
    
    # Should have 2 entries (png loaders deduplicated to 1, jpeg to 1)
    # NOT 4 entries (if symlinks were not deduplicated)
    assert len(binary_indices) == 2, (
        f"Expected 2 --add-binary entries for deduplicated loaders, "
        f"got {len(binary_indices)}"
    )
    
    # Collect the binary values (command[i+1])
    binary_values = [cmd[i+1] for i in binary_indices]
    
    # Both should reference the loaders destination
    assert all("lib/gdk-pixbuf/loaders" in val for val in binary_values), (
        f"Unexpected binary values: {binary_values}"
    )
    
    # Verify the real paths are included, not symlinks
    real_paths = [val.split(build_binary_module.os.pathsep)[0] 
                  for val in binary_values]
    for real_path in real_paths:
        # All paths should be real files, not symlinks
        assert build_binary_module.os.path.isfile(real_path), (
            f"{real_path} should be a file"
        )
