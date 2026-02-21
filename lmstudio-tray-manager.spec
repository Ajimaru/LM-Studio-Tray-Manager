# -*- mode: python ; coding: utf-8 -*-

import os
import subprocess


def _get_gdk_pixbuf_entries():
    """Resolve gdk-pixbuf loaders via pkg-config (matches build_binary.py)."""
    try:
        result = subprocess.run(
            [
                "pkg-config",
                "--variable=gdk_pixbuf_moduledir",
                "gdk-pixbuf-2.0",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return [], []

    if result.returncode != 0:
        return [], []

    loaders_dir = result.stdout.strip()
    if not loaders_dir or not os.path.exists(loaders_dir):
        return [], []

    cache_file = os.path.join(
        os.path.dirname(loaders_dir),
        "loaders.cache",
    )
    if not os.path.exists(cache_file):
        return [], []

    return [
        (loaders_dir, "lib/gdk-pixbuf/loaders"),
    ], [
        (cache_file, "lib/gdk-pixbuf"),
    ]


_gdk_binaries, _gdk_datas = _get_gdk_pixbuf_entries()


a = Analysis(
    ['lmstudio_tray.py'],
    pathex=[],
    binaries=_gdk_binaries,
    datas=[('VERSION', '.'), ('AUTHORS', '.'), ('assets', 'assets')] + _gdk_datas,
    hiddenimports=['gi', 'gi.repository', 'gi.repository.Gtk', 'gi.repository.GLib', 'gi.repository.GObject', 'gi.repository.Gio', 'gi.repository.Gdk', 'gi.repository.GdkPixbuf', 'gi.repository.Pango', 'gi.repository.PangoCairo', 'gi.repository.cairo', 'cairo', 'pkg_resources.py2_warn'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='lmstudio-tray-manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
