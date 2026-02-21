#!/usr/bin/env python3
"""
PyInstaller build script for LM Studio Tray Manager.

This script creates a standalone binary using PyInstaller with all necessary
GTK3/GObject dependencies bundled.
"""

import glob
import importlib.util
import os
import shlex
import sys
import subprocess
from pathlib import Path


def get_gdk_pixbuf_loaders():
    """Find and return GdkPixbuf loaders directory and files.

    Args:
        None

    Returns:
        tuple[str | None, str | None]: A tuple of (loaders_dir,
            cache_file) where loaders_dir is the path to the GdkPixbuf
            loaders directory and cache_file is the path to loaders.cache.
            Both elements are None if the loaders cannot be found or an
            error occurs.

    Raises:
        OSError: If subprocess execution fails.
        subprocess.SubprocessError: If pkg-config command fails.
    """
    try:
        # Get loaders directory from pkg-config
        result = subprocess.run(
            ["pkg-config", "--variable=gdk_pixbuf_moduledir",
             "gdk-pixbuf-2.0"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            loaders_dir = result.stdout.strip()
            if os.path.exists(loaders_dir):
                print(f"✓ Found GdkPixbuf loaders: {loaders_dir}")

                # Find loaders.cache
                cache_file = os.path.join(
                    os.path.dirname(loaders_dir),
                    "loaders.cache"
                )
                if os.path.exists(cache_file):
                    print(f"✓ Found loaders.cache: {cache_file}")
                    return loaders_dir, cache_file

        print("⚠ GdkPixbuf loaders not found via pkg-config")
        return None, None
    except (OSError, subprocess.SubprocessError) as e:
        print(f"⚠ Error finding GdkPixbuf loaders: {e}")
        return None, None


def check_dependencies():
    """Check and install required build dependencies.

    Args:
        None

    Returns:
        None

    Raises:
        SystemExit: If PyInstaller installation fails.
    """
    if importlib.util.find_spec("PyInstaller") is not None:
        print("✓ PyInstaller is installed")
        return

    req_file = Path(__file__).parent / "requirements-build.txt"
    print("Installing PyInstaller...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Failed to install PyInstaller: {e}")
        sys.exit(1)
    except OSError as e:
        print(f"\n❌ Error running pip: {e}")
        sys.exit(1)


def get_hidden_imports():
    """Return list of hidden imports needed for GTK3/GObject.

    Args:
        None

    Returns:
        list[str]: Hidden import module names required for GTK3/GObject
            functionality in the standalone binary.

    Raises:
        None
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
        "gi.repository.cairo",
        "cairo",
        "pkg_resources.py2_warn",
    ]


def get_data_files():
    """Return list of data files to bundle.

    Args:
        None

    Returns:
        list[tuple[str, str]]: List of (source, destination) tuples
            representing files and directories to bundle with the binary.
            source is the file/directory path, destination is the target
            path relative to the binary root.

    Raises:
        OSError: If filesystem operations fail when checking paths.
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


def build_binary():
    """Build the standalone binary using PyInstaller.

    Args:
        None

    Returns:
        int: Exit code (0 on successful build, 1 if binary creation
            fails or binary is missing after build completion).

    Raises:
        subprocess.TimeoutExpired: If PyInstaller takes longer than
            3600 seconds.
    """
    print("\n" + "="*60)
    print("Building LM Studio Tray Manager Binary")
    print("="*60 + "\n")

    # Check dependencies
    check_dependencies()

    # Get GdkPixbuf loaders
    loaders_dir, cache_file = get_gdk_pixbuf_loaders()

    # Build PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name=lmstudio-tray-manager",
        "--windowed",  # No console window
        "--clean",
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
        result = subprocess.run(cmd, check=False, timeout=3600)
    except subprocess.TimeoutExpired:
        print("\n❌ Build failed: PyInstaller timed out after 3600 seconds")
        return 1

    if result.returncode == 0:
        binary_path = Path("dist/lmstudio-tray-manager")
        if binary_path.exists():
            size_mb = binary_path.stat().st_size / (1024 * 1024)
            print("\n✅ Build successful!")
            print(f"Binary location: {binary_path}")
            print(f"Binary size: {size_mb:.2f} MB")
            print("\nNext steps:")
            print("1. Test: ./dist/lmstudio-tray-manager --version")
            print("2. Optimize: strip dist/lmstudio-tray-manager")
            print("3. Compress: upx --best dist/lmstudio-tray-manager")
        else:
            print("\n❌ Build completed but binary not found!")
            return 1
    else:
        print("\n❌ Build failed!")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(build_binary())
