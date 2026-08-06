#!/usr/bin/env python3
"""PyInstaller build script for LM Studio Tray Manager.

Creates standalone binary with Python code, resources,
GTK3/GObject modules, and optional GdkPixbuf loaders.
System GTK3/GObject/gi libraries must be provided by the
target environment at runtime.
"""

import glob
import importlib.util
import os
import shlex
import shutil
import sys
import subprocess  # nosec B404
from pathlib import Path


def get_project_root() -> Path:
    """Return the repository root for this script."""
    return Path(__file__).resolve().parent.parent


def validate_pkg_config_path(path):
    """Validate pkg-config path is absolute, safe, and free of injections.

    Args:
        path: pkg-config executable path.

    Returns:
        str: Validated absolute path.

    Raises:
        ValueError: If path unsafe.
    """
    if not path:
        raise ValueError("pkg-config path is empty")
    if not isinstance(path, str):
        raise ValueError("pkg-config path must be a string")
    if not os.path.isabs(path):
        raise ValueError("pkg-config path must be absolute")
    if "\x00" in path:
        raise ValueError("pkg-config path contains null bytes")
    if ".." in path or path.startswith("-"):
        raise ValueError("Suspicious path pattern in pkg-config path")

    return path


def get_gdk_pixbuf_loaders():
    """Find and return GdkPixbuf loaders dir and cache file.

    Returns:
        tuple[str | None, str | None]:
            (loaders_dir, cache_file) or (None, None) on error.
    """
    pkg_config_path = shutil.which("pkg-config")
    if not pkg_config_path:
        print("⚠ pkg-config not found")
        return None, None

    try:
        pkg_config_path = validate_pkg_config_path(pkg_config_path)
        result = subprocess.run(  # nosec B603
            [pkg_config_path, "--variable=gdk_pixbuf_moduledir",
             "gdk-pixbuf-2.0"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            shell=False,
        )
        if result.returncode == 0:
            loaders_dir = result.stdout.strip()
            if loaders_dir and os.path.isabs(loaders_dir) and \
                    os.path.isdir(loaders_dir):
                print(f"✓ Found GdkPixbuf loaders: {loaders_dir}")
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
    except ValueError as e:
        print(f"⚠ Invalid pkg-config path: {e}")
        return None, None
    except (OSError, subprocess.SubprocessError) as e:
        print(f"⚠ Error finding GdkPixbuf loaders: {e}")
        return None, None


def check_dependencies():
    """Check and install PyInstaller from requirements-build.txt if needed.

    Raises:
        SystemExit: If requirements-build.txt missing or install fails.
    """
    if importlib.util.find_spec("PyInstaller") is not None:
        print("✓ PyInstaller is installed")
        return

    base_dir = get_project_root()
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
        subprocess.run(  # nosec B603
            [sys.executable, "-m", "pip", "install", "-r",
             str(req_file_resolved)],
            check=True,
            shell=False,  # nosec B603
        )
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Failed to install PyInstaller: {e}")
        sys.exit(1)
    except OSError as e:
        print(f"\n❌ Error running pip: {e}")
        sys.exit(1)


def get_hidden_imports():
    """Return hidden imports for PyInstaller for the current platform.

    On macOS the tray needs rumps plus PyObjC's Foundation bindings, which
    it uses to marshal AppKit calls onto the main thread. On Windows it
    needs pystray's Win32 backend and Pillow, plus tkinter for the dialogs.

    Note:
        The macOS branch is currently unreachable in practice. Release builds
        for macOS go through ``tools/build_macos.sh``, which invokes
        PyInstaller directly, and this module only ever runs on Linux (via
        ``tools/Dockerfile.release`` and ``tools/build.sh``) or Windows (via
        ``tools/build_windows.ps1``). PyInstaller's static analysis already
        picks up Foundation and objc from the source imports, so the branch
        is a safety net for a future switch to this module rather than
        something the shipped bundle depends on.

    Returns:
        list[str]: Hidden import module names.
    """
    # certifi is imported inside _build_ssl_context() rather than at module
    # level, so PyInstaller's static analysis does not see it. Declaring it
    # here also pulls in its cacert.pem via the bundled certifi hook; without
    # the CA store every HTTPS request fails on machines that lack the build
    # host's certificate path.
    common = ["certifi"]

    if sys.platform == "darwin":
        return common + [
            "rumps",
            "objc",
            "Foundation",
            "AppKit",
        ]

    if sys.platform == "win32":
        # pystray picks its backend at import time via a dotted module name
        # that static analysis cannot follow, so the Win32 one is named
        # explicitly. PIL._tkinter_finder is what lets Pillow and tkinter
        # share a Tcl interpreter in a frozen build.
        return common + [
            "pystray",
            "pystray._win32",
            "PIL",
            "PIL.Image",
            "PIL._tkinter_finder",
            "tkinter",
            "tkinter.scrolledtext",
        ]

    return common + [
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
        "gi.repository.AppIndicator3",
        "gi.repository.cairo",
        "cairo",
    ]


def get_windows_icon():
    """Return the .ico to embed in the Windows executable, if one exists.

    The icon is generated from the PNG asset by ``tools/build_windows.ps1``
    rather than committed, so a source checkout carries no binary blob.
    Building without it is allowed; the executable then shows the default
    PyInstaller icon in Explorer, which is cosmetic only.

    Returns:
        pathlib.Path | None: Path to the icon, or None when absent or not
        building for Windows.
    """
    if sys.platform != "win32":
        return None

    icon_path = get_project_root() / "build" / "windows" / "app.ico"
    if icon_path.is_file():
        return icon_path

    print("⚠ No app.ico found - the executable will use the default icon\n")
    return None


def get_data_files():
    """Collect VERSION, AUTHORS, and assets directory for inclusion in binary.

    Returns:
        list[tuple[str, str]]: (source, destination) tuples for PyInstaller.
    """
    data_files = []
    seen = set()
    base_dir = get_project_root()

    def add_data_file(source, destination):
        """Add a data file entry if not already present."""
        entry = (str(source), destination)
        if entry in seen:
            return
        data_files.append(entry)
        seen.add(entry)

    version_path = base_dir / "VERSION"
    if version_path.exists():
        add_data_file(version_path, ".")

    authors_path = base_dir / "AUTHORS"
    if authors_path.exists():
        add_data_file(authors_path, ".")

    assets_path = base_dir / "assets"
    if assets_path.exists():
        add_data_file(assets_path, "assets")

    return data_files


def validate_pyinstaller_cmd(cmd):
    """Validate PyInstaller command list for safety before execution.

    Ensures trusted prefix, string args, no null bytes,
    valid data flags, and no path traversal.

    Args:
        cmd: Command list to validate.

    Raises:
        ValueError: If command malformed or unsafe.
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

            source, destination = value.split(os.pathsep, 1)
            if not source or not destination:
                raise ValueError(f"Empty path in data flag value: {value}")

            if ".." in source or source.startswith("-"):
                raise ValueError(
                    f"Suspicious path pattern in source: {source}"
                )
            if ".." in destination or destination.startswith("-"):
                raise ValueError(
                    f"Suspicious path pattern in destination: {destination}"
                )


def build_binary():
    """Build standalone binary using PyInstaller.

    Returns:
        int: 0 on success, 1 on failure.
    """
    print("\n" + "="*60)
    print("Building LM Studio Tray Manager Binary")
    print("="*60 + "\n")

    check_dependencies()

    # GdkPixbuf is a GTK concern, and the lookup shells out to pkg-config,
    # which does not exist on Windows.
    if sys.platform == "linux":
        loaders_dir, cache_file = get_gdk_pixbuf_loaders()
    else:
        loaders_dir, cache_file = None, None

    spec_dir = Path(".build-cache/spec")
    spec_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name=lmstudio-tray-manager",
        "--windowed",
        "--clean",
        "--specpath", str(spec_dir),
        "--exclude-module=pkg_resources",
        "--exclude-module=setuptools",
        "--exclude-module=distutils",
    ]

    for imp in get_hidden_imports():
        cmd.extend(["--hidden-import", imp])

    for src, dest in get_data_files():
        cmd.extend(["--add-data", f"{src}{os.pathsep}{dest}"])

    if loaders_dir:
        seen_loaders = set()
        for so_file in glob.glob(os.path.join(loaders_dir, "*.so*")):
            real_so = os.path.realpath(so_file)
            if not os.path.exists(real_so) or real_so in seen_loaders:
                continue
            seen_loaders.add(real_so)
            binary_value = (
                f"{real_so}{os.pathsep}" +
                "lib/gdk-pixbuf/loaders"
            )
            cmd.extend([
                "--add-binary",
                binary_value
            ])
        if cache_file:
            cmd.extend([
                "--add-data",
                f"{os.path.realpath(cache_file)}{os.pathsep}lib/gdk-pixbuf"
            ])
            print("✓ Added GdkPixbuf loaders and cache to binary\n")
        else:
            print(
                "✓ Added GdkPixbuf loaders to binary\n"
                "⚠ loaders.cache not found - icons may not render"
                " correctly!\n"
            )
    elif sys.platform == "linux":
        print("⚠ Building without GdkPixbuf loaders - icons may not work!\n")

    icon_path = get_windows_icon()
    if icon_path:
        cmd.extend(["--icon", str(icon_path)])
        print(f"✓ Using application icon: {icon_path}\n")

    cmd.append(str(get_project_root() / "lmstudio_tray.py"))

    print("Running PyInstaller with options:")
    print(shlex.join(cmd))
    print()

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

    suffix = ".exe" if sys.platform == "win32" else ""
    binary_path = Path(f"dist/lmstudio-tray-manager{suffix}")
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
    if sys.platform == "win32":
        print(f"1. Test: .\\{binary_path} --version")
        print("2. Package: .\\tools\\build_windows.ps1")
    else:
        print("1. Test: ./dist/lmstudio-tray-manager --version")
        print("2. Optimize: strip dist/lmstudio-tray-manager")
    print(
    )
    return 0


if __name__ == "__main__":
    sys.exit(build_binary())
