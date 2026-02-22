#!/usr/bin/env python3
"""
PyInstaller build script for LM Studio Tray Manager.

This script creates a standalone binary using PyInstaller that bundles the
LM Studio Tray Manager Python code, resources, and GTK3/GObject-related
Python modules (via hidden imports), as well as optional GdkPixbuf loader
.so files when available. System GTK3/GObject/gi shared libraries must be
provided by the target environment at runtime; this script does not build
a fully self-contained GTK runtime.
"""

import glob
import importlib.util
import os
import shlex
import shutil
import sys
import subprocess  # nosec B404 - required for build tooling
from pathlib import Path


def get_gdk_pixbuf_loaders():
    """Find and return GdkPixbuf loaders directory and files.

    Returns:
        tuple[str | None, str | None]: A tuple of (loaders_dir,
            cache_file) where loaders_dir is the path to the GdkPixbuf
            loaders directory and cache_file is the path to loaders.cache.
            Both elements are None if the loaders cannot be found or an
            error occurs.
    """
    # Validate pkg-config exists
    pkg_config = shutil.which("pkg-config")
    if not pkg_config:
        print("⚠ pkg-config not found")
        return None, None

    try:
        # Get loaders directory from pkg-config
        # nosec B603 - pkg-config path validated via shutil.which
        result = subprocess.run(  # nosec B603
            [pkg_config, "--variable=gdk_pixbuf_moduledir",
             "gdk-pixbuf-2.0"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            shell=False,
        )
        if result.returncode == 0:
            loaders_dir = result.stdout.strip()
            # Validate path is absolute and exists
            if loaders_dir and os.path.isabs(loaders_dir) and \
                    os.path.isdir(loaders_dir):
                print(f"✓ Found GdkPixbuf loaders: {loaders_dir}")

                # Find loaders.cache
                cache_file = os.path.join(
                    os.path.dirname(loaders_dir),
                    "loaders.cache"
                )
                if os.path.isfile(cache_file):
                    print(f"✓ Found loaders.cache: {cache_file}")
                    return loaders_dir, cache_file

                return loaders_dir, None

        print("⚠ GdkPixbuf loaders not found via pkg-config")
        return None, None
    except (OSError, subprocess.SubprocessError) as e:
        print(f"⚠ Error finding GdkPixbuf loaders: {e}")
        return None, None


def check_dependencies():
    """Check and install required build dependencies.

    Returns:
        None

    Raises:
        SystemExit: If requirements-build.txt is not found or if PyInstaller
            installation fails.
    """
    if importlib.util.find_spec("PyInstaller") is not None:
        print("✓ PyInstaller is installed")
        return

    base_dir = Path(__file__).parent.resolve()
    req_file = base_dir / "requirements-build.txt"
    req_file_resolved = req_file.resolve()
    if not req_file.is_file():
        print(f"\n❌ requirements-build.txt not found at {req_file}")
        sys.exit(1)
    if not req_file_resolved.is_relative_to(base_dir):
        print("\n❌ requirements-build.txt path escapes project directory")
        sys.exit(1)

    print("Installing PyInstaller...")
    try:
        # nosec B603 - req_file is validated as a local file
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r",
             str(req_file_resolved)],
            check=True,
            shell=False,
        )
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Failed to install PyInstaller: {e}")
        sys.exit(1)
    except OSError as e:
        print(f"\n❌ Error running pip: {e}")
        sys.exit(1)


def get_hidden_imports():
    """Return list of hidden imports needed for GTK3/GObject.

    Returns:
        list[str]: Hidden import module names required for GTK3/GObject
            functionality in the standalone binary.
    """
    return [
        "gi",
        "gi.repository",
        "gi.repository.Gtk",
        "gi.repository.GLib",
        "gi.repository.GObject",
        "gi.repository.Gio",
        "gi.repository.Gdk",
        "gi.repository.GdkPixbuf",
        "gi.repository.Pango",
        "gi.repository.PangoCairo",
        "gi.repository.AyatanaAppIndicator3",
        "gi.repository.cairo",
        "cairo",
    ]


def get_data_files():
    """Return list of data files to bundle.

    Returns:
        list[tuple[str, str]]: List of (source, destination) tuples
            representing files and directories to bundle with the binary.
            source is the file/directory path, destination is the target
            path relative to the binary root.
    """
    data_files = []

    # Include VERSION file
    if Path("VERSION").exists():
        data_files.append(("VERSION", "."))

    # Include AUTHORS file
    if Path("AUTHORS").exists():
        data_files.append(("AUTHORS", "."))

    # Include assets directory if it exists
    if Path("assets").exists():
        data_files.append(("assets", "assets"))

    return data_files


def validate_pyinstaller_cmd(cmd):
    """Validate the PyInstaller command list before execution.

    Args:
        cmd: List of command arguments to validate.

    Raises:
        ValueError: When the command list is malformed or unsafe.
    """
    if not isinstance(cmd, list) or not cmd:
        raise ValueError("PyInstaller command must be a non-empty list")
    if cmd[:3] != [sys.executable, "-m", "PyInstaller"]:
        raise ValueError("PyInstaller command is not trusted")
    for arg in cmd:
        if not isinstance(arg, str) or not arg:
            raise ValueError("PyInstaller command args must be strings")
        if "\x00" in arg:
            raise ValueError("PyInstaller command contains null bytes")

    for idx, arg in enumerate(cmd):
        if arg in {"--add-data", "--add-binary"}:
            if idx + 1 >= len(cmd):
                raise ValueError("Missing value for PyInstaller data flag")
            value = cmd[idx + 1]
            if os.pathsep not in value:
                raise ValueError("Invalid PyInstaller data flag value")


def build_binary():
    """Build the standalone binary using PyInstaller.

    Returns:
        int: Exit code (0 on successful build, 1 if binary creation
            fails or binary is missing after build completion).
    """
    print("\n" + "="*60)
    print("Building LM Studio Tray Manager Binary")
    print("="*60 + "\n")

    # Check dependencies
    check_dependencies()

    # Get GdkPixbuf loaders
    loaders_dir, cache_file = get_gdk_pixbuf_loaders()

    # Build PyInstaller command
    spec_dir = Path(".build-cache/spec")
    spec_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name=lmstudio-tray-manager",
        "--windowed",  # No console window
        "--clean",
        "--specpath", str(spec_dir),
    ]

    # Add hidden imports
    for imp in get_hidden_imports():
        cmd.extend(["--hidden-import", imp])

    # Add data files
    for src, dest in get_data_files():
        cmd.extend(["--add-data", f"{src}{os.pathsep}{dest}"])

    # Add GdkPixbuf loaders and cache
    if loaders_dir and cache_file:
        for so_file in glob.glob(os.path.join(loaders_dir, "*.so*")):
            cmd.extend([
                "--add-binary",
                f"{so_file}{os.pathsep}lib/gdk-pixbuf/loaders"
            ])
        cmd.extend([
            "--add-data",
            f"{cache_file}{os.pathsep}lib/gdk-pixbuf"
        ])
        print("✓ Added GdkPixbuf loaders to binary\n")
    else:
        print("⚠ Building without GdkPixbuf loaders - icons may not work!\n")

    # Add main script
    cmd.append("lmstudio_tray.py")

    print("Running PyInstaller with options:")
    print(shlex.join(cmd))
    print()

    # Run PyInstaller with timeout
    try:
        validate_pyinstaller_cmd(cmd)
        result = subprocess.run(  # nosec B603
            cmd,
            check=False,
            timeout=3600,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        print("\n❌ Build failed: PyInstaller timed out after 3600 seconds")
        return 1

    if result.returncode != 0:
        print("\n❌ Build failed!")
        return 1

    binary_path = Path("dist/lmstudio-tray-manager")
    if not binary_path.exists():
        print("\n❌ Build completed but binary not found!")
        return 1

    try:
        size_mb = binary_path.stat().st_size / (1024 * 1024)
    except OSError:
        size_mb = 0.0

    print("\n✅ Build successful!")
    print(f"Binary location: {binary_path}")
    print(f"Binary size: {size_mb:.2f} MB")
    print("\nNext steps:")
    print("1. Test: ./dist/lmstudio-tray-manager --version")
    print("2. Optimize: strip dist/lmstudio-tray-manager")
    print("3. Compress: upx --best dist/lmstudio-tray-manager")
    return 0


if __name__ == "__main__":
    sys.exit(build_binary())
