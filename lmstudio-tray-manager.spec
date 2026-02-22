# -*- mode: python ; coding: utf-8 -*-

import subprocess
import os
import glob
import logging

# Dynamically detect GdkPixbuf loaders paths across different distros
def get_gdk_pixbuf_paths():
    """Detect platform-specific GdkPixbuf loaders using pkg-config.

    Returns:
        tuple[list, list]: (binaries, datas) lists with platform-specific
            paths. Falls back to empty lists if loaders cannot be found.
    """
    binaries = []
    datas = []
    try:
        result = subprocess.run(
            ["pkg-config", "--variable=gdk_pixbuf_moduledir",
             "gdk-pixbuf-2.0"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5
        )
        if result.returncode == 0:
            loaders_dir = result.stdout.strip()
            if os.path.exists(loaders_dir):
                # Add individual .so loader files
                for loader_file in glob.glob(os.path.join(
                    loaders_dir, '*.so*'
                )):
                    binaries.append((loader_file,
                                     'lib/gdk-pixbuf/loaders'))

                # Find loaders.cache
                cache_file = os.path.join(
                    os.path.dirname(loaders_dir),
                    "loaders.cache"
                )
                if os.path.exists(cache_file):
                    datas.append((cache_file, 'lib/gdk-pixbuf'))
    except (OSError, subprocess.SubprocessError) as e:
        logging.warning(
            "Failed to detect GdkPixbuf loaders via pkg-config: %s",
            e, exc_info=True
        )
    return binaries, datas

gdk_binaries, gdk_datas = get_gdk_pixbuf_paths()

project_root = os.path.abspath(os.path.dirname(__file__))

datas_base = [
    (os.path.join(project_root, 'VERSION'), '.'),
    (os.path.join(project_root, 'AUTHORS'), '.'),
]

optional_datas = []
assets_dir = os.path.join(project_root, 'assets')
if os.path.exists(assets_dir):
    optional_datas.append((assets_dir, 'assets'))

datas = datas_base + optional_datas + gdk_datas

a = Analysis(
    [os.path.join(project_root, 'lmstudio_tray.py')],
    pathex=[project_root],
    binaries=gdk_binaries,
    datas=datas,
    hiddenimports=[
        'gi.repository.cairo',
        'gi.repository.AyatanaAppIndicator3',
        'gi.repository.AppIndicator3',
        'cairo',
        'gi.repository.Gtk',
        'gi.repository.GLib',
        'gi.repository.GObject',
        'gi.repository.Gio',
        'gi.repository.Gdk',
        'gi.repository.GdkPixbuf',
        'gi.repository.Pango',
        'gi.repository.PangoCairo',
        'gi.repository.cairo',
        'cairo',
        'pkg_resources.py2_warn',
    ],
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
