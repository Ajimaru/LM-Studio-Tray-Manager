# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['lmstudio_tray.py'],
    pathex=[],
    binaries=[('/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders', 'lib/gdk-pixbuf/loaders')],
    datas=[('VERSION', '.'), ('AUTHORS', '.'), ('assets', 'assets'), ('/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders.cache', 'lib/gdk-pixbuf')],
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
