#!/usr/bin/env python3
"""
LM Studio Tray Icon Monitor.

System tray app for monitoring LM Studio daemon and desktop app.
Linux: GTK3 + AppIndicator3. macOS: rumps (PyObjC).
Windows: pystray + Pillow, with tkinter for dialogs.
Usage:
    ```text
    lmstudio_tray.py [model] [script_dir] [--debug]
    [--auto-start-daemon] [--gui] [--version]
    ```
"""

import argparse
import csv
import subprocess  # nosec B404
import sys
import os
import time
import signal
import logging
import shutil
import threading
import importlib
import io
import json
import re
import socket
import ssl
import webbrowser
from typing import Callable, Optional
from types import ModuleType
from urllib import request as urllib_request
from urllib import error as urllib_error
from urllib import parse as urllib_parse

try:
    import gi
except ImportError:
    gi = None

try:
    import rumps as _rumps_lib
except ImportError:
    _rumps_lib = None

try:
    from Foundation import NSObject, NSThread
except ImportError:
    NSObject = None
    NSThread = None

try:
    import pystray as _pystray_lib
except ImportError:
    _pystray_lib = None

try:
    from PIL import Image as _pil_image
except ImportError:
    _pil_image = None

try:
    import tkinter as _tk_lib
    from tkinter import scrolledtext as _tk_scrolledtext
except ImportError:
    _tk_lib = None
    _tk_scrolledtext = None

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = not IS_MACOS and not IS_WINDOWS
_RumpsBase = _rumps_lib.App if _rumps_lib is not None else object

DEFAULT_APP_VERSION = "dev"


def _make_main_thread_dispatcher():
    """Build the Objective-C shim used to hop work onto the main thread.

    An Objective-C class name may only be registered once per process, so a
    re-import of this module reuses the existing registration instead of
    defining a second class (which the runtime rejects outright).

    Returns:
        The dispatcher instance, or ``None`` when PyObjC is unavailable.
    """
    if NSObject is None:
        return None

    import objc  # pylint: disable=import-outside-toplevel

    class_name = "LMSTrayMainThreadDispatcher"
    try:
        dispatcher_cls = objc.lookUpClass(class_name)
    except objc.nosuchclass_error:
        class LMSTrayMainThreadDispatcher(NSObject):
            """Invokes a Python callable on the AppKit main thread.

            AppKit is main-thread-only. Mutating menus or windows from a
            worker thread trips an AppKit assertion (SIGTRAP) and can leave
            shared WindowServer state wedged, which takes Finder and Dock
            down with it.
            """

            def runCallable_(self, callable_obj) -> None:
                """Run the wrapped callable, logging any error it raises.

                Args:
                    callable_obj: Zero-argument callable to invoke.
                """
                try:
                    callable_obj()
                except Exception:  # pylint: disable=broad-except
                    logging.exception("Main-thread callable raised")

        dispatcher_cls = LMSTrayMainThreadDispatcher

    return dispatcher_cls.alloc().init()


_main_thread_dispatcher = _make_main_thread_dispatcher()


def is_main_thread() -> bool:
    """Return True when running on the AppKit main thread.

    Returns:
        bool: ``True`` on the main thread, or when PyObjC is unavailable
        (non-macOS platforms have no AppKit constraint to satisfy).
    """
    if NSThread is None:
        return True
    return bool(NSThread.isMainThread())


def run_on_main_thread(func: Callable[[], None], wait: bool = False) -> bool:
    """Marshal ``func`` onto the AppKit main thread.

    Args:
        func: Zero-argument callable performing the AppKit work.
        wait: Block until the callable has run.

    Returns:
        bool: ``True`` when the call was dispatched to the main thread,
        ``False`` when no dispatcher is available and the caller must run
        ``func`` itself.
    """
    if _main_thread_dispatcher is None:
        return False
    dispatcher = _main_thread_dispatcher
    dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_(
        "runCallable:", func, wait
    )
    return True


def load_version_from_dir(base_dir: str) -> str:
    """
    Load version from VERSION file in base_dir, or default if missing.

    Args:
        base_dir (str): Directory containing VERSION file.

    Returns:
        str: Version string or DEFAULT_APP_VERSION.
    """
    version_path = os.path.join(base_dir, "VERSION")
    try:
        with open(version_path, "r", encoding="utf-8") as version_file:
            version = version_file.read().strip()
            if version:
                return version
    except OSError:
        pass
    return DEFAULT_APP_VERSION


def _get_default_script_dir() -> str:
    """
    Get script directory or current directory if unavailable.

    Returns:
        str: Absolute path to script directory.
    """
    if sys.argv and sys.argv[0]:
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    else:
        return os.getcwd()


def _get_user_data_dir() -> str:
    """
    Return the per-user directory for application data.

    Windows keeps machine-local application state under ``%LOCALAPPDATA%``;
    an installed build lives under ``Program Files`` where a normal user
    cannot write, so the fallback location matters more there than on the
    other platforms.

    Returns:
        str: Absolute path to the per-user data directory.
    """
    if IS_WINDOWS:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return os.path.join(local_app_data, "lmstudio-tray-manager")
        return os.path.expanduser(
            "~/AppData/Local/lmstudio-tray-manager"
        )

    return os.path.expanduser("~/.local/share/lmstudio-tray-manager")


def _get_writable_logs_dir(base_script_dir: str) -> str:
    """
    Get writable logs directory, fallback to the user data dir if needed.

    Args:
        base_script_dir (str): Script directory to check.

    Returns:
        str: Absolute path to writable logs directory.
    """
    logs_dir = os.path.join(base_script_dir, ".logs")

    try:
        os.makedirs(logs_dir, exist_ok=True)
        test_file = os.path.join(logs_dir, '.write_test_tmp')
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write('test')
        os.remove(test_file)
        return logs_dir
    except (OSError, IOError, PermissionError):
        writable_logs = os.path.join(_get_user_data_dir(), "logs")
        os.makedirs(writable_logs, exist_ok=True)
        return writable_logs


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments and return namespace.

    Returns:
        argparse.Namespace: Parsed arguments.

    Raises:
        SystemExit: On --help, --version, or invalid arguments.
    """
    parser = argparse.ArgumentParser(
        description="LM Studio Tray Monitor",
        add_help=True
    )
    parser.add_argument(
        "model",
        nargs="?",
        default="no-model-passed",
        help="Model name to monitor"
    )
    parser.add_argument(
        "script_dir",
        nargs="?",
        default=_get_default_script_dir(),
        help=(
            "Script directory for logs and VERSION file. If a relative path "
            "is provided it will be resolved to an absolute path when "
            "arguments are applied to the application state."
        ),
    )
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        help="Enable debug logging"
    )
    parser.add_argument(
        "--auto-start-daemon",
        "-a",
        action="store_true",
        help="Start llmster daemon on launch"
    )
    parser.add_argument(
        "--gui",
        "-g",
        action="store_true",
        help="Start LM Studio GUI on launch (stops daemon first)"
    )
    parser.add_argument(
        "--version",
        "-v",
        action="store_true",
        help="Print version and exit"
    )
    return parser.parse_args()


class _AppState:
    """
    Mutable application state shared across the module."""

    MODEL: str = "no-model-passed"
    script_dir: str = _get_default_script_dir()
    DEBUG_MODE: bool = False
    GUI_MODE: bool = False
    AUTO_START_DAEMON: bool = False
    APP_VERSION: str = DEFAULT_APP_VERSION
    API_HOST: str = "localhost"
    API_PORT: int = 1234
    Gtk: Optional[ModuleType] = None
    GLib: Optional[ModuleType] = None
    AppIndicator3: Optional[ModuleType] = None
    GdkPixbuf: Optional[ModuleType] = None

    @classmethod
    def apply_cli_args(cls, args: argparse.Namespace) -> None:
        """
        Apply parsed CLI args to app state.

        Converts script_dir to absolute path.

        Args:
            args (argparse.Namespace): Parsed CLI arguments.
        """
        cls.MODEL = args.model
        cls.script_dir = os.path.abspath(args.script_dir)
        cls.DEBUG_MODE = args.debug
        cls.GUI_MODE = args.gui
        cls.AUTO_START_DAEMON = args.auto_start_daemon and not cls.GUI_MODE

    @classmethod
    def set_gtk_modules(
        cls,
        gtk_module: ModuleType,
        glib_module: ModuleType,
        app_indicator_module: ModuleType,
        gdk_pixbuf_module: ModuleType,
    ) -> None:
        """Store GTK-related module references in class attributes."""
        cls.Gtk = gtk_module
        cls.GLib = glib_module
        cls.AppIndicator3 = app_indicator_module
        cls.GdkPixbuf = gdk_pixbuf_module


def sync_app_state_for_tests(
    gtk_mod: Optional[ModuleType] = None,
    glib_mod: Optional[ModuleType] = None,
    app_mod: Optional[ModuleType] = None,
    gdk_pixbuf_mod: Optional[ModuleType] = None,
    script_dir_val: Optional[str] = None,
    app_version_val: Optional[str] = None,
    auto_start_val: Optional[bool] = None,
    gui_mode_val: Optional[bool] = None,
    api_host_val: Optional[str] = None,
    api_port_val: Optional[int] = None,
) -> None:
    """
    Sync test mocks with _AppState and module-level variables."""

    if gtk_mod is not None:
        _AppState.Gtk = gtk_mod
    if glib_mod is not None:
        _AppState.GLib = glib_mod
    if app_mod is not None:
        _AppState.AppIndicator3 = app_mod
    if gdk_pixbuf_mod is not None:
        _AppState.GdkPixbuf = gdk_pixbuf_mod
    module_globals = globals()
    if script_dir_val is not None:
        module_globals["script_dir"] = script_dir_val
        _AppState.script_dir = script_dir_val
    if app_version_val is not None:
        module_globals["APP_VERSION"] = app_version_val
        _AppState.APP_VERSION = app_version_val
    if auto_start_val is not None:
        module_globals["AUTO_START_DAEMON"] = auto_start_val
        _AppState.AUTO_START_DAEMON = auto_start_val
    if gui_mode_val is not None:
        module_globals["GUI_MODE"] = gui_mode_val
        _AppState.GUI_MODE = gui_mode_val
    if api_host_val is not None:
        _AppState.API_HOST = api_host_val
    if api_port_val is not None:
        _AppState.API_PORT = api_port_val


script_dir = os.getcwd()
APP_VERSION = DEFAULT_APP_VERSION
AUTO_START_DAEMON = False
GUI_MODE = False


INTERVAL = 10
UPDATE_CHECK_INTERVAL = 60 * 60 * 24

# --------------------------------------------
# === GTK icon names from the icon browser ===
# --------------------------------------------

ICON_OK = "emblem-default"         # ✅ Model loaded
ICON_FAIL = "emblem-unreadable"    # ❌ Daemon and app not installed
ICON_WARN = "dialog-warning"       # ⚠️ Daemon and app stopped
ICON_INFO = "dialog-information"   # ℹ️ Runtime active, no model
APP_NAME = "LM Studio Tray Monitor"
APP_MAINTAINER = "Ajimaru"
APP_REPOSITORY = "https://github.com/Ajimaru/LM-Studio-Tray-Manager"
APP_DOCUMENTATION = "https://ajimaru.github.io/LM-Studio-Tray-Manager/"
LATEST_RELEASE_API_URL = (
    "https://api.github.com/repos/Ajimaru/LM-Studio-Tray-Manager"
    "/releases/latest"
)

# ---------------------------------------------------
# === Windows process image names (tasklist etc.) ===
# ---------------------------------------------------

LLMSTER_IMAGE_NAME = "llmster.exe"
LM_STUDIO_IMAGE_NAME = "LM Studio.exe"
TRAY_IMAGE_NAME = "lmstudio-tray-manager.exe"

# subprocess.CREATE_NO_WINDOW, spelled out rather than read off the module:
# the attribute exists only on Windows, so on the Linux CI runner - where
# the Windows code paths are unit-tested - it would silently read as 0 and
# the tests would pass while asserting nothing.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

# The Startup-folder shortcut is written by three separate things: this
# module, lmstudio_autostart.ps1, and the Inno Setup installer's optional
# autostart task. They deliberately share one file name so that whichever
# enabled it, the others see it and can turn it off again.
AUTOSTART_SHORTCUT_NAME = "LM Studio Tray Manager.lnk"


def _ensure_gsettings_schema():
    """
    Set GSETTINGS_SCHEMA_DIR if not set and schemas exist.

    Prevents PyInstaller crashes.
    """
    if "GSETTINGS_SCHEMA_DIR" in os.environ:
        return

    schema_dir = "/usr/share/glib-2.0/schemas"
    if os.path.isdir(schema_dir):
        os.environ["GSETTINGS_SCHEMA_DIR"] = schema_dir
        logging.debug("Set GSETTINGS_SCHEMA_DIR to %s", schema_dir)


def _copy_to_clipboard(url: str) -> None:
    """
    Open URL in default browser.

    Historically copied to clipboard, remains test-patchable.
    """
    try:
        webbrowser.open(url)
    except (OSError, ValueError):
        pass


def _activate_link(url: str) -> bool:
    """
    Open link from GTK dialog and return True on success.

    Args:
        url (str): URL from activate-link signal.

    Returns:
        bool: True if opened successfully.
    """
    try:
        webbrowser.open(url)
        return True
    except (OSError, ValueError):
        return False


def get_release_url(tag: Optional[str] = None) -> str:
    """
    Return GitHub release URL for specified tag or latest release.

    Args:
        tag (str, optional): Release tag name (e.g. "v1.2.3").

    Returns:
        str: URL to release page.
    """
    base = APP_REPOSITORY.rstrip("/")
    if tag:
        return f"{base}/releases/tag/{tag}"
    return f"{base}/releases/latest"

# -----------------------
# === Path to lms-CLI ===
# -----------------------


LMS_CLI = os.path.expanduser(
    "~/.lmstudio/bin/lms.exe" if IS_WINDOWS else "~/.lmstudio/bin/lms"
)


def get_app_version() -> str:
    """
    Load app version from the bundled VERSION file.

    In a PyInstaller bundle the executable sits in ``Contents/MacOS`` while
    the data files are unpacked elsewhere, so ``script_dir`` alone finds no
    VERSION and the app would report itself as a dev build - which also
    disables update checks.

    Falls back to DEFAULT_APP_VERSION.

    Returns:
        str: Version string.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        version = load_version_from_dir(meipass)
        if version != DEFAULT_APP_VERSION:
            return version

    return load_version_from_dir(_AppState.script_dir)


def _ensure_std_streams() -> None:
    """Give a windowed Windows build somewhere to write ``--help`` output.

    PyInstaller's ``--windowed`` bootloader starts the process with no
    console, leaving ``sys.stdout`` and ``sys.stderr`` set to ``None``.
    ``print()`` tolerates that and does nothing, but argparse does not: it
    calls ``file.write()`` unconditionally, so ``--help`` died with an
    ``AttributeError`` traceback instead of printing usage.

    When the app was launched from a terminal, that terminal's console is
    reattached so both flags print where the user typed them. Otherwise -
    a double-click from Explorer, say - the streams are pointed at the
    null device, which loses the text but keeps the process from crashing.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return

    if IS_WINDOWS and _attach_parent_console():
        return

    null_stream = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stdout is None:
        sys.stdout = null_stream
    if sys.stderr is None:
        sys.stderr = null_stream


def _attach_parent_console() -> bool:
    """Reattach the console of the process that launched this one.

    Returns:
        bool: ``True`` when a console was attached and the standard
        streams were reopened onto it.
    """
    try:
        import ctypes  # pylint: disable=import-outside-toplevel

        attach_parent_process = -1
        if not ctypes.windll.kernel32.AttachConsole(attach_parent_process):
            return False

        # CONOUT$/CONIN$ address the attached console directly, whatever
        # the parent had its own handles redirected to.
        if sys.stdout is None:
            sys.stdout = open("CONOUT$", "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open("CONOUT$", "w", encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        return False
    return True


def main() -> None:
    """
    Parse CLI args, load dependencies, configure logging, and start app.

    Raises:
        SystemExit: On --version flag.
    """
    _ensure_std_streams()

    args = parse_args()

    # -------------------------------------------
    # === Model name from argument or default ===
    # -------------------------------------------

    _AppState.apply_cli_args(args)

    load_config()

    module_globals = globals()
    module_globals["script_dir"] = _AppState.script_dir
    module_globals["AUTO_START_DAEMON"] = _AppState.AUTO_START_DAEMON
    module_globals["GUI_MODE"] = _AppState.GUI_MODE
    module_globals["APP_VERSION"] = _AppState.APP_VERSION

    if args.auto_start_daemon and args.gui:
        print(
            "Warning: --auto-start-daemon and --gui are mutually exclusive; "
            "--gui takes precedence.",
            file=sys.stderr
        )

    if args.version:
        print(get_app_version())
        sys.exit(0)

    if IS_MACOS:
        _run_macos(args)
        return

    if IS_WINDOWS:
        _run_windows(args)
        return

    if gi is None:  # noqa: E711
        print(
            "Error: PyGObject (gi) is not installed.",
            file=sys.stderr,
        )
        sys.exit(1)

    _ensure_gsettings_schema()
    gi.require_version("Gtk", "3.0")
    app_namespace = None
    for ns in ("AyatanaAppIndicator3", "AppIndicator3"):
        try:
            gi.require_version(ns, "0.1")
        except ValueError:
            continue
        else:
            app_namespace = ns
            break

    if app_namespace is None:
        print(
            "Error: could not find a suitable AppIndicator3 namespace "
            "(tried AyatanaAppIndicator3 and AppIndicator3).",
            file=sys.stderr,
        )
        print(
            "Please install the required packages for your distribution.",
            file=sys.stderr,
        )
        print(
            "See installation instructions at:",
            file=sys.stderr,
        )
        print(
            "https://github.com/Ajimaru/LM-Studio-Tray-Manager/"
            "blob/main/docs/SETUP.md",
            file=sys.stderr,
        )
        sys.exit(1)

    gtk_module = importlib.import_module("gi.repository.Gtk")
    glib_module = importlib.import_module("gi.repository.GLib")
    gdk_pixbuf_module = importlib.import_module(
        "gi.repository.GdkPixbuf"
    )
    app_indicator_module = importlib.import_module(
        f"gi.repository.{app_namespace}"
    )
    _AppState.set_gtk_modules(
        gtk_module,
        glib_module,
        app_indicator_module,
        gdk_pixbuf_module,
    )

    log_file = _configure_logging()

    app_indicator_module = importlib.import_module(
        f"gi.repository.{app_namespace}"
    )
    _AppState.set_gtk_modules(
        gtk_module,
        glib_module,
        app_indicator_module,
        gdk_pixbuf_module,
    )

    logging.debug("Script directory: %s", _AppState.script_dir)
    logging.debug("Log file location: %s", log_file)
    logging.debug("sys.argv[0]: %s", sys.argv[0] if sys.argv else "N/A")
    logging.debug("os.getcwd(): %s", os.getcwd())

    _AppState.APP_VERSION = get_app_version()
    globals()["APP_VERSION"] = _AppState.APP_VERSION
    logging.info("App version: %s", _AppState.APP_VERSION)

    kill_existing_instances()
    logging.info("Tray script started")

    TrayIcon()
    gtk = _AppState.Gtk
    if gtk is None:
        raise RuntimeError("GTK module is not initialized")
    gtk.main()


def _configure_logging() -> str:
    """Truncate the log file and install the masking handler.

    Shared by all three platform entry points so the log format, level and
    home-directory masking cannot drift between them.

    Returns:
        str: Path to the log file that was configured.
    """
    logs_dir = _get_writable_logs_dir(_AppState.script_dir)
    log_level = (
        logging.DEBUG if _AppState.DEBUG_MODE else logging.INFO
    )
    log_file = os.path.join(logs_dir, "lmstudio_tray.log")

    with open(log_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("LM Studio Tray Monitor Log\n")
        f.write(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n")

    logging.basicConfig(
        filename=log_file,
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        filemode='a',
        force=True,
    )
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(
            HomeMaskFormatter(
                "%(asctime)s - %(levelname)s - %(message)s"
            )
        )

    if _AppState.DEBUG_MODE:
        logging.captureWarnings(True)
        warnings_logger = logging.getLogger('py.warnings')
        warnings_logger.setLevel(logging.DEBUG)
        logging.debug(
            "Debug mode enabled - capturing warnings to log file"
        )

    return log_file


def _run_macos(_args):
    """Set up logging and launch macOS rumps tray."""
    if _rumps_lib is None:
        print(
            "Error: rumps is not installed. Install with:\n"
            "    pip install rumps",
            file=sys.stderr,
        )
        sys.exit(1)

    _configure_logging()

    _AppState.APP_VERSION = get_app_version()
    globals()["APP_VERSION"] = _AppState.APP_VERSION
    logging.info("App version: %s", _AppState.APP_VERSION)

    kill_existing_instances()
    logging.info("Tray script started (macOS / rumps)")

    if _main_thread_dispatcher is None:
        logging.warning(
            "PyObjC (Foundation) unavailable: AppKit calls will run on "
            "whichever thread triggers them. Menu rebuilds from background "
            "threads may crash the app. Install with: pip install rumps"
        )

    MacOSTrayIcon().run()


def _run_windows(_args):
    """Set up logging and launch the Windows pystray tray."""
    missing = []
    if _pystray_lib is None:
        missing.append("pystray")
    if _pil_image is None:
        missing.append("pillow")
    if missing:
        verb = "is" if len(missing) == 1 else "are"
        print(
            f"Error: {' and '.join(missing)} {verb} not installed. "
            f"Install with:\n"
            f"    pip install -r requirements-windows.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    _configure_logging()

    _AppState.APP_VERSION = get_app_version()
    globals()["APP_VERSION"] = _AppState.APP_VERSION
    logging.info("App version: %s", _AppState.APP_VERSION)

    kill_existing_instances()
    logging.info("Tray script started (Windows / pystray)")

    WindowsTrayIcon().run()


def _run_tk_dialog(build_dialog: Callable[[object], None]) -> bool:
    """Run a tkinter dialog on a dedicated thread and wait for it to close.

    pystray delivers menu callbacks on its own worker thread, and every
    tkinter call has to happen on the thread that created the root window.
    Giving each dialog its own thread and its own short-lived root
    satisfies both constraints without keeping a Tk instance alive for the
    lifetime of the tray.

    Args:
        build_dialog: Callable receiving the ``Tk`` root. It populates the
            window; the mainloop and teardown are handled here.

    Returns:
        bool: ``True`` when the dialog ran, ``False`` when tkinter is
        unavailable or the window could not be created (for example on a
        session with no window station).
    """
    if _tk_lib is None:
        logging.error("tkinter is not available; cannot show dialog")
        return False

    outcome = {"shown": False}

    def _dialog_thread() -> None:
        """Create the root, build the dialog, and pump its event loop."""
        try:
            root = _tk_lib.Tk()
        except Exception:  # pylint: disable=broad-except
            # tkinter raises TclError for a missing display, but a frozen
            # build with a broken Tcl data directory fails in other ways
            # too; none of them should take the tray down with them.
            logging.exception("Could not create the dialog window")
            return
        try:
            root.title(APP_NAME)
            icon_path = get_asset_path("img", "lm-studio-tray-manager.png")
            if icon_path:
                try:
                    root.iconphoto(
                        True, _tk_lib.PhotoImage(file=icon_path)
                    )
                except Exception:  # pylint: disable=broad-except
                    logging.debug("Could not set the dialog icon")
            build_dialog(root)
            outcome["shown"] = True
            root.mainloop()
        except Exception:  # pylint: disable=broad-except
            logging.exception("Dialog failed")
        finally:
            try:
                root.destroy()
            except Exception:  # pylint: disable=broad-except
                pass

    thread = threading.Thread(
        target=_dialog_thread, name="tk-dialog", daemon=True
    )
    thread.start()
    thread.join()
    return outcome["shown"]


def _show_tk_message(title: str, message: str) -> bool:
    """Show a read-only scrollable text dialog.

    ``messagebox`` is deliberately not used: the status output is multi-line
    and can be long enough that a fixed-size alert truncates it.

    Args:
        title: Window heading shown above the text.
        message: Body text.

    Returns:
        bool: ``True`` when the dialog was shown.
    """
    def _build(root) -> None:
        """Populate the message window."""
        root.title(f"{APP_NAME} - {title}")
        root.minsize(420, 220)

        if _tk_scrolledtext is None:
            text = _tk_lib.Text(root, wrap="word", height=14, width=64)
        else:
            text = _tk_scrolledtext.ScrolledText(
                root, wrap="word", height=14, width=64
            )
        text.insert("1.0", message)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=12, pady=(12, 6))

        _tk_lib.Button(root, text="Close", command=root.quit, width=12).pack(
            pady=(0, 12)
        )
        root.protocol("WM_DELETE_WINDOW", root.quit)

    return _run_tk_dialog(_build)


def _prompt_tk_endpoint(current: str) -> Optional[str]:
    """Prompt for an ``host:port`` API endpoint.

    Args:
        current: Endpoint to pre-fill the entry with.

    Returns:
        str | None: The submitted text, or ``None`` when the dialog was
        cancelled, closed, or could not be shown.
    """
    result: dict[str, Optional[str]] = {"value": None}

    def _build(root) -> None:
        """Populate the configuration window."""
        root.title(f"{APP_NAME} - Configuration")
        root.resizable(False, False)

        _tk_lib.Label(
            root,
            justify="left",
            text=(
                "LM Studio API endpoint to monitor.\n"
                "Enter as host:port (for example localhost:1234)."
            ),
        ).pack(anchor="w", padx=12, pady=(12, 6))

        entry = _tk_lib.Entry(root, width=40)
        entry.insert(0, current)
        entry.select_range(0, "end")
        entry.pack(fill="x", padx=12)
        entry.focus_set()

        buttons = _tk_lib.Frame(root)
        buttons.pack(anchor="e", padx=12, pady=12)

        def _save() -> None:
            """Record the entered endpoint and close."""
            result["value"] = entry.get()
            root.quit()

        _tk_lib.Button(buttons, text="Cancel", width=10,
                       command=root.quit).pack(side="right", padx=(6, 0))
        _tk_lib.Button(buttons, text="Save", width=10,
                       command=_save).pack(side="right")

        root.bind("<Return>", lambda _event: _save())
        root.bind("<Escape>", lambda _event: root.quit())
        root.protocol("WM_DELETE_WINDOW", root.quit)

    if not _run_tk_dialog(_build):
        return None
    return result["value"]


class HomeMaskFormatter(logging.Formatter):
    """Formatter replacing user's home directory with ~ in log messages."""

    def format(
        self, record: logging.LogRecord
    ) -> str:  # pragma: no cover - simple
        s = super().format(record)
        home = os.path.expanduser("~")
        if home and home != "/":
            s = s.replace(home, "~")
        return s


def get_asset_path(*path_components: str) -> Optional[str]:
    """Locate asset file in PyInstaller bundle, script_dir, or cwd.

    Args:
        *path_components: Path components relative to assets/.

    Returns:
        str | None: Full path if found, else None.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        meipass_asset = os.path.join(
            meipass, "assets", *path_components
        )
        if os.path.isfile(meipass_asset):
            return meipass_asset

    script_asset = os.path.join(
        _AppState.script_dir, "assets", *path_components
    )
    if os.path.isfile(script_asset):
        return script_asset

    cwd_asset = os.path.join(os.getcwd(), "assets", *path_components)
    if os.path.isfile(cwd_asset):
        return cwd_asset

    return None


def _get_config_path() -> str:
    """Return the config file path the app writes to.

    POSIX platforms use ``~/.config/lmstudio_tray.json``. Windows has no
    ``~/.config`` convention, so roaming user settings live under
    ``%APPDATA%`` instead - that keeps them out of the install directory,
    which is read-only for a normal user once the installer has put the app
    under ``Program Files``.

    Returns:
        str: Absolute path to the config file.
    """
    if IS_WINDOWS:
        app_data = os.environ.get("APPDATA")
        if app_data:
            return os.path.join(
                app_data, "lmstudio-tray-manager", "lmstudio_tray.json"
            )
        return os.path.expanduser(
            "~/AppData/Roaming/lmstudio-tray-manager/lmstudio_tray.json"
        )

    return os.path.expanduser("~/.config/lmstudio_tray.json")


def _get_config_read_paths() -> list[str]:
    """Return config paths to try when loading, most specific first.

    Windows moved the config from ``~/.config`` to ``%APPDATA%``. Reading
    the old location as a fallback means an existing install keeps its
    endpoint after an upgrade; the next save migrates it to the new path.

    Returns:
        list[str]: Candidate config paths, without duplicates.
    """
    paths = [_get_config_path()]
    if IS_WINDOWS:
        legacy = os.path.expanduser("~/.config/lmstudio_tray.json")
        if legacy not in paths:
            paths.append(legacy)
    return paths


def _normalize_api_port(value: object) -> Optional[int]:
    """Validate and return port as int (1-65535) or None if invalid."""
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= port <= 65535:
        return port
    return None


def parse_host_port(value: str) -> Optional[tuple[str, int]]:
    """Parse a ``host:port`` string into its parts.

    Used by the macOS configuration prompt, which offers a single text field
    rather than the separate host and port entries the GTK dialog has.
    Accepts bare IPv6 addresses in brackets (``[::1]:1234``) and tolerates a
    leading scheme so a pasted URL still works.

    Args:
        value: Text entered by the user.

    Returns:
        tuple[str, int] | None: ``(host, port)`` when both parts are valid,
        otherwise ``None``.
    """
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    for scheme in ("http://", "https://"):
        if text.lower().startswith(scheme):
            text = text[len(scheme):]
            break
    text = text.split("/", 1)[0].strip()

    if text.startswith("["):
        closing = text.find("]")
        if closing == -1:
            return None
        host = text[1:closing].strip()
        remainder = text[closing + 1:].strip()
        if not remainder.startswith(":"):
            return None
        port_text = remainder[1:]
    else:
        if text.count(":") != 1:
            return None
        host, port_text = text.split(":", 1)
        host = host.strip()

    port = _normalize_api_port(port_text.strip())
    if not host or port is None:
        return None
    return (host, port)


def load_config() -> None:
    """
    Load API endpoint config from file.

    Updates _AppState.API_HOST and API_PORT.
    """
    candidates = _get_config_read_paths()
    data = None
    for config_path in candidates:
        logging.debug("Attempting to load config from %s", config_path)
        try:
            with open(config_path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        except FileNotFoundError:
            continue
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logging.warning(
                "Failed to load config from %s: %s",
                config_path,
                exc
            )
            return
        else:
            break

    if data is None:
        logging.info(
            "Config file not found at %s, using defaults",
            candidates[0]
        )
        return

    host = data.get("api_host") if isinstance(data, dict) else None
    port_raw = data.get("api_port") if isinstance(data, dict) else None

    if isinstance(host, str) and host.strip():
        _AppState.API_HOST = host.strip()
        logging.debug("Loaded API host: %s", _AppState.API_HOST)

    port = _normalize_api_port(port_raw)
    if port is not None:
        _AppState.API_PORT = port
        logging.debug("Loaded API port: %s", _AppState.API_PORT)

    if host or port:
        logging.info(
            "Config loaded successfully: http://%s:%s",
            _AppState.API_HOST,
            _AppState.API_PORT
        )


def save_config(api_host: str, api_port: int) -> None:
    """Save API endpoint config to file.

    Raises:
        ValueError: If api_host or api_port invalid.
    """
    host = api_host.strip() if isinstance(api_host, str) else ""
    port = _normalize_api_port(api_port)

    if not host or port is None:
        logging.error(
            "Invalid config values: host='%s', port='%s'",
            host,
            api_port
        )
        raise ValueError("Invalid api_host/api_port")

    config_path = _get_config_path()
    logging.debug(
        "Saving config to %s: host=%s, port=%s",
        config_path,
        host,
        port
    )
    config_dir = os.path.dirname(config_path)
    os.makedirs(config_dir, exist_ok=True)
    payload = {
        "api_host": host,
        "api_port": port,
    }
    tmp_path = f"{config_path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as config_file:
            json.dump(payload, config_file, indent=2)
            config_file.flush()
            os.fsync(config_file.fileno())
        os.replace(tmp_path, config_path)
        logging.info(
            "Config saved successfully to %s: http://%s:%s",
            config_path,
            host,
            port
        )
    except OSError:
        logging.exception("Failed to write config: %s", config_path)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _validate_url_scheme(url: str) -> str:
    """Validate URL uses http/https and return formatted base URL.

    Args:
        url: URL to validate.

    Raises:
        ValueError: If scheme not http/https or invalid host/port.

    Returns:
        str: Formatted URL.
    """
    parsed = urllib_parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"URL scheme '{parsed.scheme}' not permitted; "
            f"only 'http' and 'https' are allowed"
        )

    host = (_AppState.API_HOST or "").strip()
    if not host or any(ch.isspace() for ch in host):
        raise ValueError("Invalid API host")

    if "://" in host or "/" in host or "?" in host or "#" in host:
        raise ValueError("Invalid API host")

    if ":" in host and not host.startswith("["):
        if host.count(":") == 1:
            raise ValueError("Invalid API host")
        host = f"[{host}]"

    port = _normalize_api_port(_AppState.API_PORT)
    if port is None:
        raise ValueError("Invalid API port")
    return f"http://{host}:{port}"


def get_api_base_url() -> str:
    """Return base API URL from _AppState config.

    Returns:
        str: Base API URL (http://host:port).

    Raises:
        ValueError: If config invalid.
    """
    return _validate_url_scheme(
        f"http://{_AppState.API_HOST}:{_AppState.API_PORT}"
    )


def get_api_models_url() -> str:
    """Return full API models endpoint URL."""
    return f"{get_api_base_url()}/v1/models"


def get_native_api_models_url() -> str:
    """Return LM Studio's own models endpoint URL.

    ``/v1/models`` is the OpenAI-compatible listing and reports only ``id``,
    ``object`` and ``owned_by`` - it cannot distinguish an available model
    from a loaded one. LM Studio's native ``/api/v0/models`` adds a
    ``state`` field (``loaded`` / ``not-loaded``), which is what the tray
    needs to report whether a model is actually active.

    Returns:
        str: Native models endpoint URL.
    """
    return f"{get_api_base_url()}/api/v0/models"


_LOCAL_HOST_NAMES = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",  # nosec B104 - compared against, never bound
        "",
    }
)


def _get_local_addresses() -> set[str]:
    """Return addresses that refer to this machine.

    Includes the loopback names plus every address the host resolves to, so
    that entering a machine's own LAN address (rather than ``localhost``)
    is still recognised as local.

    Returns:
        set[str]: Lower-cased host names and IP addresses.
    """
    addresses = set(_LOCAL_HOST_NAMES)
    try:
        hostname = socket.gethostname()
    except OSError:
        return addresses

    addresses.add(hostname.lower())
    short_name = hostname.split(".", 1)[0].lower()
    addresses.add(short_name)
    addresses.add(f"{short_name}.local")

    for candidate in (hostname, f"{short_name}.local"):
        try:
            infos = socket.getaddrinfo(candidate, None)
        except (OSError, UnicodeError):
            continue
        for info in infos:
            address = info[4][0]
            if isinstance(address, str):
                addresses.add(address.split("%", 1)[0].lower())

    return addresses


def is_remote_endpoint() -> bool:
    """Return True when the configured API host is not this machine.

    Process-based detection (``pgrep llmster``, scanning for LM Studio.app)
    only describes the local machine. When the user points the tray at
    another host, that detection is meaningless and status has to come from
    the HTTP API instead.

    A machine's own LAN address counts as local: entering ``192.168.1.136``
    on the box that actually serves it is not a remote setup.

    Returns:
        bool: ``True`` when the endpoint refers to a different host.
    """
    host = (_AppState.API_HOST or "").strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1].strip()
    host = host.split("%", 1)[0]
    if not host:
        return False
    return host not in _get_local_addresses()


def get_authors() -> list[str]:
    """Parse AUTHORS file from script_dir.

    Returns list or [APP_MAINTAINER] fallback.

    Returns:
        list: Author names.
    """
    authors_path = os.path.join(_AppState.script_dir, "AUTHORS")
    authors = []
    try:
        with open(authors_path, "r", encoding="utf-8") as authors_file:
            for line in authors_file:
                line = line.strip()
                if (
                    line
                    and not line.startswith("#")
                    and not line.startswith("<!--")
                    and line.startswith("-")
                ):
                    author = line[1:].strip()
                    if " - " in author:
                        author = author.split(" - ")[0].strip()
                    if "(@" in author:
                        author = author.split(" (@")[0].strip()
                    if author:
                        authors.append(author)
    except OSError:
        pass
    return authors if authors else [APP_MAINTAINER]


def parse_version(version: Optional[str]) -> tuple[int, ...]:
    """Parse version string to tuple of integers for comparison."""
    if not version:
        return ()
    cleaned = version.strip()
    if cleaned.startswith("v"):
        cleaned = cleaned[1:]
    parts = []
    for part in cleaned.split("."):
        digits = ""
        for char in part:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def is_newer_version(current: Optional[str], latest: Optional[str]) -> bool:
    """Return True if latest version > current version."""
    current_parts = parse_version(current)
    latest_parts = parse_version(latest)
    if not current_parts or not latest_parts:
        return False
    return latest_parts > current_parts


def _is_allowed_update_url(url: str) -> bool:
    """Return True if URL is HTTPS GitHub API repos endpoint.

    Args:
        url: URL to validate.

    Returns:
        bool: True if safe update URL.
    """
    parsed = urllib_parse.urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "api.github.com"
        and parsed.path.startswith("/repos/")
    )


def _build_ssl_context() -> ssl.SSLContext:
    """Return an SSL context with a trust store that survives freezing.

    A PyInstaller bundle ships ``libssl`` but not the CA store it was
    compiled against.  With a Homebrew Python that store lives under
    ``/opt/homebrew/etc/openssl@3``, a path that does not exist on a machine
    without Homebrew - so every HTTPS request fails there with
    ``CERTIFICATE_VERIFY_FAILED`` while working fine on the build machine.

    ``certifi`` is bundled to provide the certificates explicitly.  When it
    is unavailable the platform defaults still apply, which is correct for a
    normal source checkout.

    Returns:
        ssl.SSLContext: Context with certificate verification enabled.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        logging.debug("Update check: certifi unavailable, using system trust")
        return ssl.create_default_context()


def get_latest_release_version() -> tuple[Optional[str], Optional[str]]:
    """Fetch latest GitHub release tag, return (tag, error_msg) tuple."""
    if not _is_allowed_update_url(LATEST_RELEASE_API_URL):
        logging.debug("Update check: invalid update URL")
        return None, "Invalid update URL"

    request = urllib_request.Request(
        LATEST_RELEASE_API_URL,
        headers={"User-Agent": "LM-Studio-Tray-Manager"},
    )
    logging.debug(
        "Update check: requesting %s",
        LATEST_RELEASE_API_URL,
    )
    try:
        https_handler = urllib_request.HTTPSHandler(
            context=_build_ssl_context()
        )
        opener = urllib_request.build_opener(https_handler)

        with opener.open(request, timeout=10) as response:
            payload = response.read().decode("utf-8")
            data = json.loads(payload)
            tag = data.get("tag_name")
            logging.debug("Update check: latest tag %s", tag)
            return (tag.strip(), None) if tag else (None, "No tag found")
    except urllib_error.HTTPError as exc:
        logging.debug("Update check: HTTP error %s", exc.code)
        return None, f"HTTP {exc.code}"
    except (ssl.SSLCertVerificationError, ssl.SSLError) as exc:
        # Reported separately: a missing trust store is a packaging bug, and
        # folding it into the generic branch below hides that entirely.
        logging.debug("Update check: TLS error %s", exc)
        return None, "TLS certificate error"
    except (urllib_error.URLError, OSError, ValueError) as exc:
        # URLError wraps the original failure, so a TLS problem reaches this
        # branch too unless it is unwrapped here.
        reason = getattr(exc, "reason", None)
        if isinstance(reason, ssl.SSLError):
            logging.debug("Update check: TLS error %s", reason)
            return None, "TLS certificate error"
        logging.debug("Update check: network or parse error: %s", exc)
        return None, "Network or parse error"


def _is_executable_file(path: str) -> bool:
    """Return True when ``path`` is a file this platform can execute.

    NTFS carries no execute permission bit, so ``os.access(path, os.X_OK)``
    degrades to an existence check on Windows and tells us nothing. There,
    executability is decided by the extension, which the caller has already
    fixed by looking for ``lms.exe`` rather than ``lms``.

    Args:
        path: Candidate file path.

    Returns:
        bool: ``True`` when the file exists and can be run.
    """
    if not os.path.isfile(path):
        return False
    if IS_WINDOWS:
        return True
    return os.access(path, os.X_OK)


def get_lms_cmd() -> Optional[str]:
    """Return LM Studio CLI path if executable, else resolve from PATH."""
    if _is_executable_file(LMS_CLI):
        return LMS_CLI
    return shutil.which("lms")


_get_llmster_cmd_state = {"last_candidate": None, "seen_call": False}


def get_llmster_cmd() -> Optional[str]:
    """Return llmster path from PATH or install dir.

    Includes debug logging on changes.
    """
    state = _get_llmster_cmd_state

    llmster_cmd = shutil.which("llmster")
    if llmster_cmd:
        candidate = llmster_cmd
    else:
        llmster_root = os.path.expanduser("~/.lmstudio/llmster")
        if not os.path.isdir(llmster_root):
            candidate = None
        else:
            candidates = []
            binary_names = (
                ("llmster.exe", "llmster") if IS_WINDOWS else ("llmster",)
            )
            try:
                for entry in os.listdir(llmster_root):
                    for binary_name in binary_names:
                        candidate_path = os.path.join(
                            llmster_root, entry, binary_name
                        )
                        if _is_executable_file(candidate_path):
                            candidates.append(candidate_path)
                            break
            except (OSError, PermissionError):
                candidate = None
            else:
                candidate = sorted(candidates)[-1] if candidates else None

    log_needed = False
    if not state["seen_call"]:
        log_needed = True
    elif candidate != state["last_candidate"]:
        log_needed = True

    if log_needed:
        if candidate:
            if llmster_cmd:
                msg = "Found llmster on PATH: %s"
            else:
                msg = "Resolved llmster candidate: %s"
            logging.debug(msg, candidate)
        else:
            if not os.path.isdir(os.path.expanduser("~/.lmstudio/llmster")):
                logging.debug("No ~/.lmstudio/llmster directory present")
            else:
                logging.debug(
                    "No executable llmster binaries found under %s",
                    os.path.expanduser("~/.lmstudio/llmster")
                )
    state["last_candidate"] = candidate
    state["seen_call"] = True
    return candidate


_signed_bundle_state: dict = {"checked": False, "signed": False}


def is_signed_bundle() -> bool:
    """Return True when running from a Developer ID signed .app bundle.

    Notifications posted by such a bundle carry the app's own icon and are
    registered under System Settings -> Notifications. An ad-hoc signed or
    unsigned build has no registered identity, so macOS discards its
    notifications silently and ``osascript`` has to stand in.

    The answer cannot change while the process runs, so it is cached: this
    shells out to ``codesign`` and notifications are frequent.

    Returns:
        bool: ``True`` for a bundle signed with a real team identity.
    """
    state = _signed_bundle_state
    if state["checked"]:
        return state["signed"]
    state["checked"] = True

    bundled = (
        getattr(sys, "frozen", False)
        or getattr(sys, "_MEIPASS", None) is not None
    )
    if not IS_MACOS or not bundled:
        return False

    # Derive the bundle from _MEIPASS (Contents/Frameworks or Contents/MacOS)
    # rather than sys.argv[0]: the loader sets it, so no command line input
    # reaches the codesign call below.
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return False
    app_path = os.path.dirname(os.path.dirname(os.path.abspath(meipass)))
    if not app_path.endswith(".app") or not os.path.isdir(app_path):
        return False

    codesign = shutil.which("codesign")
    if not codesign or not os.path.isabs(codesign):
        return False

    try:
        result = _run_safe_command([codesign, "-dv", app_path])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logging.debug("codesign check failed: %s", exc)
        return False

    # codesign writes its report to stderr.
    report = f"{result.stderr or ''}{result.stdout or ''}"
    signed = (
        "TeamIdentifier=" in report
        and "TeamIdentifier=not set" not in report
    )
    state["signed"] = signed
    logging.debug(
        "Bundle signature: %s", "Developer ID" if signed else "ad-hoc"
    )
    return signed


def _notify_via_osascript(title: str, message: str) -> bool:
    """Post a notification through ``osascript``.

    ``rumps`` uses ``NSUserNotification``, deprecated since macOS 11. An
    ad-hoc signed bundle is never registered under System Settings ->
    Notifications, so those notifications are dropped without raising --
    there is nothing to catch and no way to detect the loss. ``osascript``
    posts under the Script Editor identity instead, which is registered, so
    the banner actually appears (with the Script Editor icon).

    Args:
        title: Notification title.
        message: Notification body.

    Returns:
        bool: ``True`` when the notification was handed off successfully.
    """
    if not IS_MACOS:
        return False

    osascript = shutil.which("osascript")
    if not osascript or not os.path.isabs(osascript):
        return False

    # Title and message are passed as arguments rather than interpolated
    # into the script text, so no amount of quoting in a model name can
    # break out of the string literal. The script itself is constant.
    script = (
        "on run argv\n"
        "display notification (item 2 of argv) "
        "with title (item 1 of argv)\n"
        "end run"
    )
    try:
        result = _run_safe_command([osascript, "-e", script, title, message])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logging.debug("osascript notification failed: %s", exc)
        return False
    if result.returncode != 0:
        logging.debug(
            "osascript notification returned %s: %s",
            result.returncode,
            (result.stderr or "").strip(),
        )
        return False
    return True


def is_daemon_available() -> bool:
    """Return True when the llmster daemon can be controlled here.

    Only a standalone llmster binary counts. ``lms`` is deliberately not
    accepted: where LM Studio embeds the daemon, ``lms daemon up`` starts
    the desktop app rather than a headless daemon, so treating ``lms`` as
    "daemon available" offers a start action that cannot work.

    Returns:
        bool: ``True`` when an llmster binary was found.
    """
    return bool(get_llmster_cmd())


def _has_loaded_model(output: str) -> bool:
    """Return True if lms ps output indicates loaded model.

    Includes debug logging.
    """
    if not output or not output.strip():
        return False
    text = output.lower()
    if "no models" in text:
        logging.debug("lms ps output explicitly reports no models")
        return False
    if "available" in text and "loaded" not in text:
        logging.debug("lms ps output contains only available models, ignoring")
        return False
    return True


def _escape_markup(text: str) -> str:
    """Escape the characters Pango markup treats specially.

    Model identifiers are attacker-controlled only in the sense that they
    come from whatever the user loaded, but an ampersand in a name is enough
    to make Pango reject the whole markup string and drop the text.

    Args:
        text: Plain text to embed in markup.

    Returns:
        str: Text safe to place inside a markup element.
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _format_lms_ps_output(output: str) -> str:
    """Reformat the ``lms ps`` table as one labelled block per model.

    ``lms ps`` prints a wide table whose width grows with the model name. In
    a GTK dialog that single long row gets wrapped at arbitrary points, so
    values end up on the line of the next column and the output becomes hard
    to read. Listing each column on its own line keeps the lines short
    enough that no wrapping happens.

    Args:
        output: Raw stdout of ``lms ps``.

    Returns:
        str: Reformatted text, or the unchanged input when it does not look
        like the expected table.
    """
    lines = [line for line in output.splitlines() if line.strip()]

    header_index = None
    for index, line in enumerate(lines):
        if "IDENTIFIER" in line:
            header_index = index
            break

    if header_index is None:
        return output

    # Columns are padded apart with runs of spaces; single spaces occur
    # inside values such as "4.13 GB" or "1h / 1h" and must be preserved.
    columns = re.split(r"\s{2,}", lines[header_index].strip())
    rows = lines[header_index + 1:]
    if len(columns) < 2 or not rows:
        return output

    parsed_rows = []
    for row in rows:
        values = re.split(r"\s{2,}", row.strip())
        if len(values) != len(columns):
            logging.debug(
                "lms ps row does not match header columns, keeping raw output"
            )
            return output
        parsed_rows.append(values)

    label_width = max(len(column) for column in columns)
    blocks = []
    for values in parsed_rows:
        blocks.append(
            "\n".join(
                f"{column + ':':<{label_width + 1}} {value}"
                for column, value in zip(columns, values)
            )
        )

    return "\n\n".join(blocks)


def _api_loaded_model_names(models: object) -> list[str]:
    """Return model names explicitly marked as loaded from API response.

    Args:
        models: Parsed data list from API.

    Returns:
        list[str]: Model names/ids.
    """
    if not isinstance(models, list):
        return []

    loaded_names = []
    active_states = {"loaded", "active", "running"}

    for model in models:
        if not isinstance(model, dict):
            continue

        loaded_flag = model.get("loaded")
        active_flag = model.get("active")
        in_use_flag = model.get("in_use")
        state_val = str(model.get("state", "")).strip().lower()
        status_val = str(model.get("status", "")).strip().lower()

        is_loaded = (
            loaded_flag is True
            or active_flag is True
            or in_use_flag is True
            or state_val in active_states
            or status_val in active_states
        )

        if not is_loaded:
            continue

        model_name = model.get("id") or model.get("name") or "Unknown"
        loaded_names.append(str(model_name))

    return loaded_names


def query_api_models() -> tuple[bool, list[str]]:
    """Query the API for reachability and the names of loaded models.

    The native endpoint is tried first because it is the only one that
    reports load state; ``/v1/models`` is the fallback for LM Studio builds
    that do not serve ``/api/v0``.

    Returns:
        tuple[bool, list[str]]: ``(reachable, loaded_model_names)``.
    """
    reachable = False

    for url_func in (get_native_api_models_url, get_api_models_url):
        try:
            api_url = url_func()
            _validate_url_scheme(api_url)
            req = urllib_request.Request(
                api_url,
                headers={"User-Agent": "lmstudio-tray-manager"},
            )
            with urllib_request.urlopen(  # nosec B310
                req, timeout=3
            ) as response:
                payload = response.read()
                data = json.loads(payload.decode("utf-8"))
        except (
            urllib_error.HTTPError,
            urllib_error.URLError,
            OSError,
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            logging.debug("API endpoint %s failed: %s", url_func.__name__, exc)
            continue

        reachable = True
        if isinstance(data, dict):
            names = _api_loaded_model_names(data.get("data", []))
            if names:
                return (True, names)

    return (reachable, [])


def check_api_reachable() -> tuple[bool, bool]:
    """Query the API, separating reachability from model state.

    ``check_api_models`` collapses "unreachable" and "no model loaded" into
    a single ``False``. For a remote endpoint those mean very different
    things, so this variant reports them separately.

    Returns:
        tuple[bool, bool]: ``(reachable, has_loaded_model)``.
    """
    reachable, names = query_api_models()
    return (reachable, bool(names))


def get_pkill_cmd() -> Optional[str]:
    """Return absolute pkill path from PATH."""
    return shutil.which("pkill")


def get_notify_send_cmd() -> Optional[str]:
    """Return absolute notify-send path from PATH."""
    return shutil.which("notify-send")


def get_ps_cmd() -> Optional[str]:
    """Return absolute ps path from PATH."""
    return shutil.which("ps")


def get_pgrep_cmd() -> Optional[str]:
    """Return absolute pgrep path from PATH."""
    return shutil.which("pgrep")


def get_dpkg_cmd() -> Optional[str]:
    """Return absolute dpkg path from PATH."""
    return shutil.which("dpkg")


def get_tasklist_cmd() -> Optional[str]:
    """Return absolute tasklist.exe path from PATH (Windows only)."""
    return shutil.which("tasklist")


def get_taskkill_cmd() -> Optional[str]:
    """Return absolute taskkill.exe path from PATH (Windows only)."""
    return shutil.which("taskkill")


def _parse_tasklist_csv(output: str) -> list[tuple[str, int]]:
    """Parse ``tasklist /NH /FO CSV`` output into (image name, PID) pairs.

    ``tasklist`` exits 0 even when a filter matches nothing - it prints
    ``INFO: No tasks are running which match...`` instead - so callers have
    to judge by the parsed rows rather than the return code. CSV is parsed
    with :mod:`csv` rather than split by hand because image names contain
    spaces (``LM Studio.exe``) and are therefore quoted.

    Args:
        output: Raw stdout from ``tasklist``.

    Returns:
        list[tuple[str, int]]: One entry per process row. Rows without a
        numeric PID (the INFO line, blank lines) are skipped.
    """
    processes: list[tuple[str, int]] = []
    if not output:
        return processes

    for row in csv.reader(io.StringIO(output)):
        if len(row) < 2:
            continue
        image_name = row[0].strip()
        pid_text = row[1].strip()
        if not image_name or not pid_text.isdigit():
            continue
        processes.append((image_name, int(pid_text)))

    return processes


# -----------------------------------------
# === Windows autostart (Startup folder) ===
# -----------------------------------------


def get_powershell_cmd() -> Optional[str]:
    """Return absolute powershell.exe path from PATH (Windows only)."""
    return shutil.which("powershell")


def _get_startup_dir() -> Optional[str]:
    """Return the current user's Startup folder.

    Asks the shell rather than assuming a path, because the Start-menu
    folders can be redirected (roaming profiles, some corporate policies)
    and a shortcut written to the wrong place would silently never run.
    Falls back to the default location under ``%APPDATA%`` when the shell
    call is unavailable.

    Returns:
        Optional[str]: Absolute path, or ``None`` when it cannot be
        determined.
    """
    if not IS_WINDOWS:
        return None

    csidl_startup = 7
    max_path = 260
    try:
        # Imported here, like the console helper above: ctypes.windll only
        # exists on Windows, and this module must import cleanly elsewhere.
        import ctypes  # pylint: disable=import-outside-toplevel

        buf = ctypes.create_unicode_buffer(max_path)
        # SHGetFolderPathW returns S_OK (0) on success.
        if ctypes.windll.shell32.SHGetFolderPathW(
            None, csidl_startup, None, 0, buf
        ) == 0 and buf.value:
            return buf.value
    except (AttributeError, ImportError, OSError) as exc:
        logging.debug("SHGetFolderPathW failed: %s", exc)

    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return os.path.join(
        appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
    )


def get_autostart_shortcut_path() -> Optional[str]:
    """Return the path of this app's Startup-folder shortcut.

    Returns:
        Optional[str]: Absolute path, or ``None`` off Windows or when the
        Startup folder cannot be located.
    """
    startup_dir = _get_startup_dir()
    if not startup_dir:
        return None
    return os.path.join(startup_dir, AUTOSTART_SHORTCUT_NAME)


def is_autostart_enabled() -> bool:
    """Report whether the tray is registered to start with Windows.

    Returns:
        bool: ``True`` when the Startup-folder shortcut exists.
    """
    shortcut = get_autostart_shortcut_path()
    return bool(shortcut) and os.path.isfile(shortcut)


def _get_autostart_target() -> Optional[tuple[str, list[str], str]]:
    """Return how Windows should relaunch this tray at login.

    Mirrors ``Get-TrayCommand`` in lmstudio_autostart.ps1: a frozen build
    points at its own executable, a source checkout at an interpreter plus
    this script. ``pythonw.exe`` is preferred over ``python.exe`` so the
    login does not flash a console window.

    The working directory follows what is being *run*, not what runs it: a
    source launch has to start in the repository, since the log directory
    and the default ``script_dir`` are resolved relative to the process's
    current directory, and the interpreter's own folder is neither.

    Returns:
        Optional[tuple[str, list[str], str]]: Executable, its arguments and
        the working directory, or ``None`` when nothing can be resolved.
    """
    frozen = (
        getattr(sys, "frozen", False)
        or getattr(sys, "_MEIPASS", None) is not None
    )
    if frozen:
        executable = os.path.abspath(sys.executable)
        if not os.path.isfile(executable):
            return None
        return executable, [], os.path.dirname(executable)

    script = os.path.abspath(__file__)
    if not os.path.isfile(script):
        return None

    interpreter = os.path.abspath(sys.executable)
    pythonw = os.path.join(os.path.dirname(interpreter), "pythonw.exe")
    if os.path.isfile(pythonw):
        interpreter = pythonw
    if not os.path.isfile(interpreter):
        return None
    return interpreter, [script], os.path.dirname(script)


def _ps_quote(value: str) -> str:
    """Quote a string as a PowerShell single-quoted literal.

    Inside single quotes PowerShell expands nothing, so doubling the
    embedded quote is the whole escaping rule. Paths are system-derived
    here, but a checkout under a directory such as ``Rob's Git`` would
    otherwise break the generated command.

    Args:
        value: Text to quote.

    Returns:
        str: The quoted literal, apostrophes included.
    """
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def enable_autostart() -> bool:
    """Register the tray to start with Windows.

    Writes the same Startup-folder shortcut that lmstudio_autostart.ps1 and
    the installer write. Creating a ``.lnk`` needs the Windows shell's COM
    object, so this drives it through ``powershell.exe`` rather than adding
    a pywin32 dependency for one call.

    Returns:
        bool: ``True`` when the shortcut now exists.
    """
    shortcut = get_autostart_shortcut_path()
    if not shortcut:
        logging.error("Cannot enable autostart: Startup folder not found")
        return False

    target = _get_autostart_target()
    if not target:
        logging.error("Cannot enable autostart: tray executable not found")
        return False
    executable, arguments, working_dir = target

    powershell = get_powershell_cmd()
    if not powershell or not os.path.isabs(powershell):
        logging.error("Cannot enable autostart: powershell.exe not found")
        return False

    startup_dir = os.path.dirname(shortcut)
    try:
        os.makedirs(startup_dir, exist_ok=True)
    except OSError as exc:
        logging.error("Cannot create the Startup folder: %s", exc)
        return False

    script = (
        "$s = (New-Object -ComObject WScript.Shell)"
        f".CreateShortcut({_ps_quote(shortcut)});"
        f"$s.TargetPath = {_ps_quote(executable)};"
        f"$s.Arguments = {_ps_quote(' '.join(arguments))};"
        f"$s.WorkingDirectory = {_ps_quote(working_dir)};"
        f"$s.Description = {_ps_quote(APP_NAME)};"
        "$s.Save()"
    )

    try:
        result = _run_safe_command([
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-Command", script,
        ])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logging.error("Failed to create the autostart shortcut: %s", exc)
        return False

    if result.returncode != 0:
        logging.error(
            "Failed to create the autostart shortcut: %s",
            (result.stderr or "").strip() or f"exit {result.returncode}",
        )
        return False

    if not os.path.isfile(shortcut):
        logging.error("Autostart shortcut was not created at %s", shortcut)
        return False

    logging.info("Autostart enabled: %s", shortcut)
    return True


def disable_autostart() -> bool:
    """Remove the Startup-folder shortcut.

    Succeeds when the shortcut is already absent: the requested end state
    is "not registered", which is then already true.

    Returns:
        bool: ``True`` when the tray no longer starts with Windows.
    """
    shortcut = get_autostart_shortcut_path()
    if not shortcut:
        logging.error("Cannot disable autostart: Startup folder not found")
        return False

    if not os.path.isfile(shortcut):
        logging.debug("Autostart was not enabled; nothing to remove")
        return True

    try:
        os.remove(shortcut)
    except OSError as exc:
        logging.error("Failed to remove the autostart shortcut: %s", exc)
        return False

    logging.info("Autostart disabled: %s", shortcut)
    return True


def get_api_loaded_models() -> list[str]:
    """Return names of models the API reports as loaded.

    Returns:
        list[str]: Loaded model names, empty when none or unreachable.
    """
    _, names = query_api_models()
    return names


def _shorten_model_name(name: str, limit: int = 28) -> str:
    """Shorten a model id so it fits a menu bar entry.

    Model ids can be long (``qwen/qwen3-coder-30b-a3b-instruct``). The
    publisher prefix is dropped first since the model name carries the
    useful part; anything still too long is truncated.

    Args:
        name: Model identifier.
        limit: Maximum length of the result.

    Returns:
        str: Display name no longer than ``limit``.
    """
    text = str(name).strip()
    if len(text) > limit and "/" in text:
        text = text.rsplit("/", 1)[-1]
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def check_api_models() -> bool:
    """Check if models loaded via API (fallback when lms ps fails).

    Returns:
        bool: True if at least one model loaded.
    """
    _, has_loaded_model = check_api_reachable()
    return has_loaded_model


def _no_window_kwargs() -> dict:
    """Return the subprocess flags that suppress a console window.

    A ``--windowed`` build has no console of its own, so Windows gives one
    to every console program the tray runs - ``tasklist``, ``taskkill``,
    ``lms``, ``powershell``. Each appears as a black window that flashes up
    and vanishes, and the status poll alone runs one every ``INTERVAL``
    seconds. ``CREATE_NO_WINDOW`` suppresses it while still letting the
    pipes be read.

    Returns:
        dict: ``creationflags`` on Windows, empty elsewhere - POSIX
        ``subprocess`` rejects the argument outright.
    """
    if not IS_WINDOWS:
        return {}
    return {"creationflags": CREATE_NO_WINDOW}


def _run_safe_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run pre-validated command list.

    Caller must ensure trusted absolute-path executable.

    Args:
        command: Command list.

    Returns:
        CompletedProcess: Result.

    Raises:
        ValueError: If format invalid or exe not absolute.
    """
    if not isinstance(command, list) or not command:
        raise ValueError("Command must be a non-empty list")

    if not all(isinstance(arg, str) for arg in command):
        raise ValueError("All command arguments must be strings")

    exe = command[0]
    if not os.path.isabs(exe):
        raise ValueError(f"Executable must be absolute path: {exe}")

    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        shell=False,  # nosec B603 B607
        timeout=10,
        **_no_window_kwargs(),
    )


def _query_tasklist(image_name: str) -> list[tuple[str, int]]:
    """Return processes matching ``image_name`` via ``tasklist``.

    Args:
        image_name: Executable name to filter on, e.g. ``"llmster.exe"``.

    Returns:
        list[tuple[str, int]]: Matching (image name, PID) pairs; empty when
        tasklist is unavailable or the query fails.
    """
    tasklist_cmd = get_tasklist_cmd()
    if not tasklist_cmd or not os.path.isabs(tasklist_cmd):
        return []

    try:
        result = _run_safe_command([
            tasklist_cmd,
            "/FI", f"IMAGENAME eq {image_name}",
            "/NH",
            "/FO", "CSV",
        ])
    except (
        FileNotFoundError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        logging.debug("tasklist query for %r failed: %s", image_name, exc)
        return []

    if result.returncode != 0:
        return []

    return _parse_tasklist_csv(result.stdout)


def _run_taskkill(args: list[str]) -> bool:
    """Run ``taskkill`` with ``args`` appended.

    Args:
        args: Arguments following the executable, e.g.
            ``["/IM", "llmster.exe", "/T"]``.

    Returns:
        bool: ``True`` when taskkill was invoked, ``False`` when it is
        unavailable or the call raised. A non-zero exit is reported as
        ``True``: taskkill returns 128 when nothing matched, which is a
        successful no-op rather than a failure.
    """
    taskkill_cmd = get_taskkill_cmd()
    if not taskkill_cmd or not os.path.isabs(taskkill_cmd):
        logging.warning("taskkill not found; cannot stop process")
        return False

    try:
        _run_safe_command([taskkill_cmd] + args)
    except (
        FileNotFoundError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        logging.debug("taskkill %s failed: %s", args, exc)
        return False

    return True


def is_llmster_running() -> bool:
    """Return True if llmster process running (using pgrep or ps)."""
    if IS_WINDOWS:
        return bool(_query_tasklist(LLMSTER_IMAGE_NAME))

    pgrep_cmd = get_pgrep_cmd()
    if pgrep_cmd and os.path.isabs(pgrep_cmd):
        try:
            result = _run_safe_command([pgrep_cmd, "-x", "llmster"])
            if result.returncode == 0:
                return True
        except (
            FileNotFoundError,
            ValueError,
            OSError,
            subprocess.SubprocessError,
        ):
            pass

        try:
            result = _run_safe_command([pgrep_cmd, "-f", "llmster"])
            if result.returncode == 0:
                return True
        except (
            FileNotFoundError,
            ValueError,
            OSError,
            subprocess.SubprocessError,
        ):
            pass

    ps_cmd = get_ps_cmd()
    if not ps_cmd or not os.path.isabs(ps_cmd):
        return False

    try:
        result = _run_safe_command([ps_cmd, "-eo", "pid=,args="])
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "llmster" in line and "grep" not in line:
                    return True
    except (
        FileNotFoundError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
    ):
        pass

    return False


def _is_lm_studio_appimage_label(value):
    """Return True if value identifies LM Studio Desktop App AppImage.

    Excludes bench/tray tools.
    """
    if not isinstance(value, str):
        return False

    text = value.lower()
    if ".appimage" not in text:
        return False

    has_lm_studio_name = (
        "lm-studio" in text
        or "lm studio" in text
    )
    if not has_lm_studio_name:
        return False

    if any(x in text for x in ("bench", "tray", "manager")):
        return False

    return True


def _get_desktop_app_pids_windows() -> list[int]:
    """Return PIDs of every LM Studio desktop process on Windows.

    Unlike the POSIX branch this cannot exclude Electron helpers:
    ``tasklist`` reports image names only, never a command line, so the
    ``--type=`` renderer filter has no Windows equivalent. Both callers
    tolerate that - the status check only asks whether the list is
    non-empty, and stopping the app kills the whole process tree anyway.

    Returns:
        list[int]: PIDs of all ``LM Studio.exe`` processes.
    """
    return [pid for _name, pid in _query_tasklist(LM_STUDIO_IMAGE_NAME)]


def get_desktop_app_pids():
    """Return PIDs of LM Studio desktop app root processes.

    Excludes workers/helpers (POSIX only - see
    :func:`_get_desktop_app_pids_windows`).
    """
    if IS_WINDOWS:
        return _get_desktop_app_pids_windows()

    pids = []
    ps_cmd = get_ps_cmd()
    if not ps_cmd:
        return pids
    try:
        result = _run_safe_command([ps_cmd, "-eo", "pid=,args="])
        if result.returncode != 0:
            return pids

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue

            parts = line.split(None, 1)
            if len(parts) != 2:
                continue

            pid_text, cmd_args = parts
            if not pid_text.isdigit():
                continue

            if "--type=" in cmd_args:
                continue

            if (
                "systemresourcesworker" in cmd_args
                or "liblmstudioworker" in cmd_args
                or "/llmster/" in cmd_args
            ):
                continue

            if IS_MACOS:
                if (
                    "LM Studio.app/Contents/MacOS" in cmd_args
                    or cmd_args.endswith("/LM Studio")
                    or cmd_args == "LM Studio"
                ):
                    pids.append(int(pid_text))
                    continue
            else:
                cmd_args_lower = cmd_args.lower()
                if (
                    "/opt/LM Studio/lm-studio" in cmd_args
                    or cmd_args.startswith("/usr/bin/lm-studio")
                    or cmd_args.startswith("lm-studio ")
                    or cmd_args == "lm-studio"
                ):
                    pids.append(int(pid_text))
                    continue

                if _is_lm_studio_appimage_label(cmd_args_lower):
                    pids.append(int(pid_text))
                    continue

                is_lm_studio_mount = (
                    "/lm-studio" in cmd_args
                    and ".mount_" in cmd_args
                    and "bench" not in cmd_args_lower
                )
                if is_lm_studio_mount:
                    pids.append(int(pid_text))
                    continue
    except (OSError, subprocess.SubprocessError, ValueError):
        return []

    return pids


def _existing_instance_patterns() -> list[str]:
    """Return pgrep patterns matching other copies of this tray.

    A bundled build runs as ``LM-Studio-Tray-Manager`` inside
    ``Contents/MacOS``, so searching only for the script name misses it and
    a second menu bar icon appears. The bundle pattern is anchored on the
    bundle path so it cannot match unrelated processes that merely mention
    the name.

    Returns:
        list[str]: Patterns for ``pgrep -f``.
    """
    patterns = ["lmstudio_tray.py"]
    if IS_MACOS:
        patterns.append(
            "LM-Studio-Tray-Manager.app/Contents/MacOS/"
            "LM-Studio-Tray-Manager"
        )
    return patterns


def _own_process_pids() -> set[int]:
    """Return the PIDs belonging to this instance, which must not be killed.

    A PyInstaller one-file build runs as two processes under the same image
    name: the bootloader, which unpacks the bundle into a temporary
    directory, and the child it spawns to run this code. Protecting only
    ``getpid()`` therefore made the child terminate its own bootloader -
    and the bootloader is what deletes that temporary directory on exit, so
    every launch leaked an unpacked copy of the app.

    Returns:
        set[int]: This process and, where available, its parent.
    """
    pids = {os.getpid()}
    try:
        pids.add(os.getppid())
    except (AttributeError, OSError):
        # getppid is documented for Windows but guard anyway: losing the
        # parent here only costs the leak this function exists to prevent.
        logging.debug("Could not determine the parent process id")
    return pids


def _kill_existing_instances_windows() -> None:
    """Terminate other copies of the frozen tray executable on Windows.

    Only a frozen build can be identified reliably. Running from source the
    process image is ``python.exe``, which ``tasklist`` cannot distinguish
    from any other Python program on the machine - matching on it would
    terminate unrelated work, so that case is skipped instead.
    """
    if getattr(sys, "frozen", False) is not True:
        logging.debug(
            "Not a frozen build; skipping single-instance check "
            "(python.exe cannot be matched safely)"
        )
        return

    own_pids = _own_process_pids()
    for _name, pid in _query_tasklist(TRAY_IMAGE_NAME):
        if pid in own_pids:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            logging.info("Terminating old instance: PID %s", pid)
        except (OSError, ProcessLookupError, PermissionError) as exc:
            logging.warning("Error terminating PID %s: %s", pid, exc)


def kill_existing_instances():
    """Terminate other running copies of the tray using pgrep/SIGTERM."""
    if IS_WINDOWS:
        _kill_existing_instances_windows()
        return

    pgrep_cmd = get_pgrep_cmd()
    if not pgrep_cmd:
        logging.warning("pgrep not found; cannot detect existing instances")
        return

    current_pid = os.getpid()
    seen: set[int] = set()

    for pattern in _existing_instance_patterns():
        try:
            result = _run_safe_command([pgrep_cmd, "-f", pattern])
        except (OSError, subprocess.SubprocessError) as exc:
            logging.debug("pgrep for %r failed: %s", pattern, exc)
            continue

        for line in result.stdout.strip().split("\n"):
            if not line.isdigit():
                continue
            pid = int(line)
            if pid == current_pid or pid in seen:
                continue
            seen.add(pid)
            try:
                os.kill(pid, signal.SIGTERM)
                logging.info("Terminating old instance: PID %s", pid)
            except (OSError, ProcessLookupError, PermissionError) as e:
                logging.warning("Error terminating PID %s: %s", pid, e)


class TrayIcon:
    """GTK tray icon for LM Studio runtime monitoring and controls.

    Manages daemon/app controls and notifications.
    """
    def __init__(self):
        """Initialize tray indicator, menu, and periodic status checks."""
        gtk = _AppState.Gtk
        glib = _AppState.GLib
        app_indicator3 = _AppState.AppIndicator3
        if gtk is None or glib is None or app_indicator3 is None:
            raise RuntimeError("GTK/AppIndicator modules are not initialized")
        self.indicator = app_indicator3.Indicator.new(
            "lmstudio-monitor",
            ICON_WARN,
            app_indicator3.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_status(
            app_indicator3.IndicatorStatus.ACTIVE
        )
        self.indicator.set_title("LM Studio Monitor")
        self.action_lock_until = 0.0
        self.lms_ps_resume_at = 0.0
        self.last_update_version = None
        self.update_status = "Unknown"
        self.latest_update_version = None
        self.last_update_error = None
        self.menu = gtk.Menu()
        self._seen_desktop_call = False
        self._last_desktop_detection = None
        self._seen_dpkg_missing = False
        self.build_menu()
        self.indicator.set_menu(self.menu)
        self.last_status = None
        self.check_model()
        glib.timeout_add_seconds(INTERVAL, self.check_model)
        glib.timeout_add_seconds(5, self._initial_update_check)
        glib.timeout_add_seconds(
            UPDATE_CHECK_INTERVAL,
            self._check_updates_tick,
        )
        glib.idle_add(self._maybe_auto_start_daemon)
        glib.idle_add(self._maybe_start_gui)

    def _maybe_auto_start_daemon(self):
        """Restart daemon on launch if enabled.

        Ensures fresh passkey for lms CLI.
        """
        if not _AppState.AUTO_START_DAEMON:
            return False

        logging.info(
            "Auto-starting daemon (flag --auto-start-daemon) "
            "with fresh passkey"
        )

        try:
            self._stop_daemon_with_notification()
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            logging.error("Error stopping llmster daemon: %s", e)

        self.action_lock_until = 0.0
        self.start_daemon(None)
        return False

    def _maybe_start_gui(self):
        """Start desktop app on launch if GUI_MODE enabled."""
        if not _AppState.GUI_MODE:
            return False

        logging.info("Auto-starting GUI (flag --gui)")
        self.start_desktop_app(None)
        return False

    def begin_action_cooldown(self, action_name, seconds=2.0):
        """Return False if within cooldown, else set cooldown and return True.
        """
        now = time.monotonic()
        if now < self.action_lock_until:
            remaining = self.action_lock_until - now
            logging.info(
                "Action blocked by cooldown: %s (%.1fs remaining)",
                action_name,
                remaining,
            )
            return False

        self.action_lock_until = now + seconds
        return True

    def _can_use_lms_ps(self, daemon_running, app_running):
        """Return True if safe to run lms ps.

        Respects desktop launch grace period.
        """
        if daemon_running:
            return True
        if not app_running:
            return False

        now = time.monotonic()
        resume_at = getattr(self, "lms_ps_resume_at", 0.0)
        if now < resume_at:
            remaining = max(0.0, resume_at - now)
            logging.debug(
                "Skipping lms ps during desktop launch grace window "
                "(%.1fs remaining)",
                remaining,
            )
            return False
        return True

    def _schedule_menu_refresh(self, delay_seconds=2):
        """Schedule delayed menu rebuild via GLib timeout.

        Args:
            delay_seconds (int): Delay before refresh (default 2).
        """
        glib = _AppState.GLib
        if glib is None:
            logging.debug("GLib is not initialized; skipping menu refresh")
            return

        delay_seconds = max(0, int(delay_seconds))

        def _refresh_once():
            try:
                self.build_menu()
            except (OSError, RuntimeError, ValueError) as exc:
                logging.exception("Delayed menu refresh failed: %s", exc)
            return False

        glib.timeout_add_seconds(delay_seconds, _refresh_once)

    def build_menu(self):
        """Build/rebuild context menu with current status and options.
        """
        gtk = _AppState.Gtk
        if gtk is None:
            raise RuntimeError("GTK module is not initialized")

        for item in self.menu.get_children():
            self.menu.remove(item)

        daemon_status = self.get_daemon_status()
        app_status = self.get_desktop_app_status()
        daemon_indicator = self.get_status_indicator(daemon_status)
        app_indicator = self.get_status_indicator(app_status)

        # ----------------------
        # === DAEMON CONTROL ===
        # ----------------------

        if daemon_status == "running":
            daemon_item = gtk.MenuItem(
                label=f"{daemon_indicator} Daemon (Running)"
            )
            daemon_item.set_sensitive(False)
            self.menu.append(daemon_item)
            stop_daemon_item = gtk.MenuItem(
                label="  → Stop Daemon"
            )
            stop_daemon_item.connect("activate", self.stop_daemon)
            self.menu.append(stop_daemon_item)
        elif daemon_status == "stopped":
            start_daemon_item = gtk.MenuItem(
                label=f"{daemon_indicator} Start Daemon (Headless)"
            )
            start_daemon_item.connect("activate", self.start_daemon)
            self.menu.append(start_daemon_item)
        else:
            not_found_item = gtk.MenuItem(
                label=f"{daemon_indicator} Daemon (Not Installed)"
            )
            not_found_item.set_sensitive(False)
            self.menu.append(not_found_item)

        # ---------------------------
        # === DESKTOP APP CONTROL ===
        # ---------------------------

        if app_status == "running":
            app_item = gtk.MenuItem(
                label=f"{app_indicator} Desktop App (Running)"
            )
            app_item.set_sensitive(False)
            self.menu.append(app_item)
            stop_app_item = gtk.MenuItem(label="  → Stop Desktop App")
            stop_app_item.connect("activate", self.stop_desktop_app)
            self.menu.append(stop_app_item)
        elif app_status == "stopped":
            start_app_item = gtk.MenuItem(
                label=f"{app_indicator} Start Desktop App"
            )
            start_app_item.connect("activate", self.start_desktop_app)
            self.menu.append(start_app_item)
        elif app_status == "not_found":
            not_found_item = gtk.MenuItem(
                label=f"{app_indicator} Desktop App (Not Installed)"
            )
            not_found_item.set_sensitive(False)
            self.menu.append(not_found_item)

        self.menu.append(gtk.SeparatorMenuItem())

        status_item = gtk.MenuItem(label="Show Status")
        status_item.connect("activate", self.show_status_dialog)
        self.menu.append(status_item)

        options_menu = gtk.Menu()
        options_item = gtk.MenuItem(label="Options")
        options_item.set_submenu(options_menu)
        self.menu.append(options_item)

        config_item = gtk.MenuItem(label="Configuration")
        config_item.connect("activate", self.show_config_dialog)
        options_menu.append(config_item)

        update_item = gtk.MenuItem(label="Check for updates")
        update_item.connect("activate", self.manual_check_updates)
        options_menu.append(update_item)

        about_item = gtk.MenuItem(label="About")
        about_item.connect("activate", self.show_about_dialog)
        self.menu.append(about_item)

        self.menu.append(gtk.SeparatorMenuItem())

        quit_item = gtk.MenuItem(label="Quit Tray")
        quit_item.connect("activate", self.quit_app)
        self.menu.append(quit_item)

        self.menu.show_all()
        self.indicator.set_menu(self.menu)

    def get_daemon_status(self) -> str:
        """Return daemon status: 'running', 'stopped', or 'not_found'.

        Returns:
            str: Status string.
        """
        try:
            if not is_daemon_available():
                return "not_found"
            if is_llmster_running():
                return "running"
            return "stopped"
        except (
            OSError,
            subprocess.SubprocessError,
            subprocess.TimeoutExpired,
        ):
            return "not_found"

    def get_desktop_app_status(self) -> str:
        """Return desktop app status: 'running', 'stopped', or 'not_found'.

        Returns:
            str: Status string.
        """

        try:
            if get_desktop_app_pids():
                return "running"
        except (OSError, subprocess.SubprocessError):
            pass

        if not hasattr(self, "_last_desktop_detection"):
            self._last_desktop_detection = None
        if not hasattr(self, "_seen_desktop_call"):
            self._seen_desktop_call = False
        detection = None

        dpkg_cmd = get_dpkg_cmd()
        if dpkg_cmd and os.path.isabs(dpkg_cmd):
            try:
                result = _run_safe_command([dpkg_cmd, "-l"])
                if "lm-studio" in result.stdout:
                    if shutil.which("lm-studio"):
                        detection = "dpkg"
                        status = "stopped"
                        self._seen_dpkg_missing = False
                    else:
                        if not self._seen_dpkg_missing:
                            logging.debug(
                                (
                                    "dpkg reports lm-studio but "
                                    "executable not in PATH"
                                )
                            )
                            self._seen_dpkg_missing = True
                        status = None
                else:
                    status = None
                    self._seen_dpkg_missing = False
            except (OSError, subprocess.SubprocessError) as exc:
                logging.debug("dpkg query failed: %s", exc)
                status = None
                self._seen_dpkg_missing = False
        else:
            status = None
            self._seen_dpkg_missing = False

        if status is None:
            search_paths = [
                _AppState.script_dir,
                os.path.expanduser("~/Apps"),
                os.path.expanduser("~/LM_Studio"),
                os.path.expanduser("~/Applications"),
                os.path.expanduser("~/.local/bin"),
                "/opt/lm-studio",
            ]
            for search_path in search_paths:
                if not os.path.isdir(search_path):
                    continue
                try:
                    candidates = [
                        f for f in os.listdir(search_path)
                        if _is_lm_studio_appimage_label(f)
                    ]
                    picked = None
                    if candidates:
                        picked = sorted(candidates)[0]
                    if picked:
                        app_path = os.path.join(search_path, picked)
                        detection = f"appimage:{app_path}"
                        status = "stopped"
                        break
                    if status is not None:
                        break
                except (OSError, PermissionError) as exc:
                    logging.debug(
                        "Error scanning %s for AppImage: %s",
                        search_path,
                        exc
                    )
        if status is None:
            detection = "none"
            status = (
                "not_found"
            )

        if (
            not self._seen_desktop_call
            or detection != self._last_desktop_detection
        ):
            if detection == "dpkg":
                logging.debug("Detected lm-studio installation via dpkg")
            elif detection and detection.startswith("appimage:"):
                logging.debug(
                    "Detected AppImage at %s",
                    detection.split(":", 1)[1]
                )
            else:
                logging.debug("No desktop app installation found")
            self._last_desktop_detection = detection
            self._seen_desktop_call = True

        return status

    def get_status_indicator(self, status: str) -> str:
        """Return emoji for status ('running' -> 🟢, 'stopped' -> 🟡, else -> 🔴).

        Args:
            status: Status string.

        Returns:
            str: Emoji indicator.
        """
        if status == "running":
            return "🟢"
        elif status == "stopped":
            return "🟡"
        else:
            return "🔴"

    @staticmethod
    def _run_validated_command(
        command: list[str],
    ) -> subprocess.CompletedProcess[str]:
        """Run a pre-validated command list via subprocess.

        The caller MUST ensure that ``command`` contains trusted,
        absolute-path executables from ``get_lms_cmd``,
        ``get_llmster_cmd`` or equivalent helpers.

        Args:
            command: List of strings forming the command.

        Returns:
            CompletedProcess: The completed process result.

        Raises:
            ValueError: If command format is invalid or executable is not
                absolute path.
        """
        if (
            isinstance(command, list)
            and len(command) >= 3
            and isinstance(command[0], str)
            and os.path.basename(command[0]) == "notify-send"
            and isinstance(command[2], str)
        ):
            icon_prefixes = ("✅", "ℹ️", "⚠️", "❌")
            message = command[2].lstrip()
            if not message.startswith(icon_prefixes):
                command = list(command)
                command[2] = f"ℹ️ {command[2]}"
        return _run_safe_command(command)

    def _run_daemon_attempts(
        self,
        attempts: list[list[str]],
        stop_when: Callable[[subprocess.CompletedProcess[str]], bool],
    ) -> Optional[subprocess.CompletedProcess[str]]:
        """Run daemon command attempts until a condition is met.

        Args:
            attempts: Ordered list of command argument lists.
            stop_when: Callable that receives the subprocess result and
                returns True when no further attempts are needed.

        Returns:
            CompletedProcess | None: Last command result, or None if no
            command was executed.
        """
        result = None
        for command in attempts:
            if not isinstance(command, list) or not all(
                isinstance(arg, str) for arg in command
            ):
                logging.error("Invalid command format: %s", command)
                continue

            exe = command[0] if command else ""
            if not os.path.isabs(exe):
                logging.error(
                    "Refusing to run non-absolute executable: %s", exe
                )
                continue

            try:
                result = self._run_validated_command(command)
                if stop_when(result):
                    break
            except subprocess.TimeoutExpired:
                logging.warning("Command timed out: %s", " ".join(command))
                break
        return result

    def _build_daemon_attempts(self, action: str) -> list[list[str]]:
        """Build ordered daemon CLI attempts for one action.

        Args:
            action: Either "start" or "stop".

        Returns:
            list[list[str]]: Commands to try in order.
        """
        lms_cmd = get_lms_cmd()
        llmster_cmd = get_llmster_cmd()
        attempts = []

        if action == "start":
            # lms is deliberately absent here: where LM Studio embeds the
            # daemon, `lms daemon up` launches the desktop app instead of a
            # headless daemon. Only a standalone llmster binary is used to
            # start; lms remains in the stop path below.
            if llmster_cmd:
                attempts.extend(
                    [
                        [llmster_cmd, "daemon", "up"],
                        [llmster_cmd, "daemon", "start"],
                        [llmster_cmd, "up"],
                        [llmster_cmd, "start"],
                    ]
                )
        elif action == "stop":
            if lms_cmd:
                attempts.extend(
                    [
                        [lms_cmd, "daemon", "down"],
                        [lms_cmd, "daemon", "stop"],
                        [lms_cmd, "down"],
                        [lms_cmd, "stop"],
                    ]
                )
            if llmster_cmd:
                attempts.extend(
                    [
                        [llmster_cmd, "daemon", "down"],
                        [llmster_cmd, "daemon", "stop"],
                        [llmster_cmd, "down"],
                        [llmster_cmd, "stop"],
                    ]
                )

        return attempts

    def _force_stop_llmster(self) -> None:
        """Force-stop llmster with SIGTERM then SIGKILL escalation."""
        pkill_cmd = get_pkill_cmd()
        if not pkill_cmd:
            logging.warning("pkill not found; cannot force-stop llmster")
            return

        try:
            self._run_validated_command([pkill_cmd, "-x", "llmster"])
        except subprocess.TimeoutExpired:
            pass

        try:
            self._run_validated_command([pkill_cmd, "-f", "llmster"])
        except subprocess.TimeoutExpired:
            pass

        for _ in range(12):
            if not is_llmster_running():
                return
            time.sleep(0.25)

        if is_llmster_running():
            logging.warning(
                "SIGTERM did not stop llmster; sending SIGKILL"
            )
            try:
                self._run_validated_command(
                    [pkill_cmd, "-9", "-x", "llmster"]
                )
            except subprocess.TimeoutExpired:
                pass
            try:
                self._run_validated_command(
                    [pkill_cmd, "-9", "-f", "llmster"]
                )
            except subprocess.TimeoutExpired:
                pass

            for _ in range(8):
                if not is_llmster_running():
                    break
                time.sleep(0.25)

    def _stop_llmster_best_effort(
        self,
    ) -> tuple[bool, Optional[subprocess.CompletedProcess[str]]]:
        """Stop llmster with graceful attempts and force-stop fallback.

        Always calls force-stop to handle race conditions where pgrep
        reports the process gone but it hasn't fully released its port/socket.

        Returns:
            tuple[bool, CompletedProcess | None]: Tuple containing:
                - True when llmster is no longer running.
                - Last command result used during stop attempts.
        """
        attempts = self._build_daemon_attempts("stop")
        result = self._run_daemon_attempts(
            attempts,
            lambda _result: not is_llmster_running(),
        )

        self._force_stop_llmster()

        return (not is_llmster_running(), result)

    def _stop_daemon_with_notification(
        self,
    ) -> tuple[bool, Optional[subprocess.CompletedProcess[str]]]:
        """Stop daemon and show notification on success/failure.

        Single source of truth for daemon-stop logic with user notifications.
        Used by both stop_daemon() menu action and start_desktop_app() to
        ensure consistent daemon-stopping behavior.

        Returns:
            tuple[bool, CompletedProcess | None]: (stopped, result)
                from _stop_llmster_best_effort().
        """
        if not self._build_daemon_attempts("stop"):
            logging.error("llmster not found")
            notify_cmd = get_notify_send_cmd()
            if notify_cmd:
                self._run_validated_command(
                    [
                        notify_cmd,
                        "Error",
                        "llmster/lms not found. Nothing to stop.",
                    ]
                )
            return (False, None)

        stopped, result = self._stop_llmster_best_effort()

        if stopped:
            logging.info("llmster daemon stopped")
            notify_cmd = get_notify_send_cmd()
            if notify_cmd:
                self._run_validated_command(
                    [
                        notify_cmd,
                        "LLMster",
                        (
                            "Daemon stopped. You can now start the "
                            "desktop app."
                        ),
                    ]
                )
        else:
            err = "llmster process is still running"
            if result is not None:
                detail = result.stderr.strip() or result.stdout.strip()
                if detail:
                    err = f"{err}: {detail}"
            logging.error("Failed to stop llmster daemon: %s", err)
            notify_cmd = get_notify_send_cmd()
            if notify_cmd:
                self._run_validated_command(
                    [
                        notify_cmd,
                        "Error",
                        "Daemon stop failed: " + str(err)
                    ]
                )

        return (stopped, result)

    def _stop_desktop_app_processes(self) -> bool:
        """Stop LM Studio desktop processes using TERM, then KILL.

        Returns:
            bool: True when the desktop app is no longer running.
        """
        desktop_pids = get_desktop_app_pids()
        for pid in desktop_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except (OSError, ProcessLookupError, PermissionError):
                pass

        for _ in range(8):
            if self.get_desktop_app_status() != "running":
                break
            time.sleep(0.25)

        if self.get_desktop_app_status() == "running":
            desktop_pids = get_desktop_app_pids()
            for pid in desktop_pids:
                try:
                    sigkill = getattr(signal, "SIGKILL", 9)
                    os.kill(pid, sigkill)
                except (OSError, ProcessLookupError, PermissionError):
                    pass

            for _ in range(8):
                if self.get_desktop_app_status() != "running":
                    break
                time.sleep(0.25)

        return self.get_desktop_app_status() != "running"

    def start_daemon(self, _widget: object) -> None:
        """Start the headless daemon.

        Stops the desktop app first if needed, then tries daemon start
        variants and notifies on success/failure.

        Args:
            _widget: Widget that triggered the action (unused).
        """
        if not self.begin_action_cooldown("start_daemon"):
            return

        if self.get_desktop_app_status() == "running":
            if not self._stop_desktop_app_processes():
                logging.error(
                    "Cannot start daemon: desktop app is still running"
                )
                notify_cmd = get_notify_send_cmd()
                if notify_cmd:
                    self._run_validated_command(
                        [
                            notify_cmd,
                            "Error",
                            (
                                "Failed to stop desktop app. "
                                "Please stop it first."
                            ),
                        ]
                    )
                self.build_menu()
                return

            logging.info("Desktop app stopped before daemon start")
            self.build_menu()

        start_attempts = self._build_daemon_attempts("start")
        if not start_attempts:
            logging.error("llmster not found")
            notify_cmd = get_notify_send_cmd()
            if notify_cmd:
                self._run_validated_command(
                    [
                        notify_cmd,
                        "Daemon",
                        "llmster not installed. Install it with: "
                        "curl -fsSL https://lmstudio.ai/install.sh | bash",
                    ]
                )
            return
        try:
            result = self._run_daemon_attempts(
                start_attempts,
                lambda current: (
                    current.returncode == 0 and is_llmster_running()
                ),
            )

            if is_llmster_running():
                logging.info("llmster daemon started/ensured")
                notify_cmd = get_notify_send_cmd()
                if notify_cmd:
                    self._run_validated_command(
                        [
                            notify_cmd, "LLMster", "llmster daemon is running",
                        ]
                    )
            else:
                err = "Unknown error"
                if result is not None:
                    err = result.stderr.strip() or result.stdout.strip() or err
                logging.error("Failed to start llmster daemon: %s", err)
                error_msg = "Daemon start failed: " + str(err)
                notify_cmd = get_notify_send_cmd()
                if notify_cmd:
                    self._run_validated_command(
                        [notify_cmd, "Error", error_msg]
                    )
            self.build_menu()
            self._schedule_menu_refresh()
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            logging.error("Error starting llmster daemon: %s", e)
            notify_cmd = get_notify_send_cmd()
            if notify_cmd:
                self._run_validated_command(
                    [notify_cmd, "Error", "Error: " + str(e)]
                )
            self.build_menu()

    def stop_daemon(self, _widget: object) -> None:
        """Stop the headless daemon.

        Uses _stop_daemon_with_notification() for consistent stop logic
        with user notifications.

        Args:
            _widget: Widget that triggered the action (unused).
        """
        if not self.begin_action_cooldown("stop_daemon"):
            return

        try:
            self._stop_daemon_with_notification()
            self.build_menu()
            self._schedule_menu_refresh()
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            logging.error("Error stopping llmster daemon: %s", e)
            notify_cmd = get_notify_send_cmd()
            if notify_cmd:
                self._run_validated_command(
                    [notify_cmd, "Error", "Error: " + str(e)]
                )
            self.build_menu()

    def start_desktop_app(self, _widget: object) -> None:
        """Start the LM Studio desktop app.

        All blocking logic runs in a background thread so the tray
        menu remains responsive while the desktop app is launching.

        Args:
            _widget: Widget that triggered the action (unused).
        """
        if not self.begin_action_cooldown("start_desktop_app"):
            return

        app_thread = threading.Thread(
            target=self._start_desktop_app_body,
            daemon=True,
            name="start-desktop-app",
        )
        app_thread.start()

    def _start_desktop_app_body(self) -> None:
        """Background thread body for start_desktop_app.

        Stops the daemon first using _stop_daemon_with_notification(),
        locates the app (.deb or AppImage), and launches it.
        All GTK menu updates are posted back to the main loop via
        GLib.idle_add() so this method is safe to call from any thread.
        """
        glib = _AppState.GLib

        def _rebuild_menu():
            if glib is not None:
                glib.idle_add(self.build_menu)

        lms_cmd = get_lms_cmd()
        if not lms_cmd:
            logging.error("lms CLI not found")
            notify_cmd = get_notify_send_cmd()
            if notify_cmd:
                self._run_validated_command(
                    [
                        notify_cmd,
                        "Error",
                        "lms CLI not found. Cannot launch app.",
                    ]
                )
            return

        daemon_was_running = is_llmster_running()
        stopped, _result = self._stop_daemon_with_notification()

        if daemon_was_running and (not stopped or is_llmster_running()):
            logging.warning(
                "Daemon still running after stop attempts; "
                "trying force-stop before GUI launch"
            )
            self._force_stop_llmster()
            stopped = not is_llmster_running()

        if not stopped:
            logging.error(
                "Cannot start desktop app: llmster still running"
            )
            _rebuild_menu()
            return

        if daemon_was_running:
            logging.info("llmster daemon stopped before GUI launch")
            time.sleep(2.0)
            logging.debug("Waited 2.0s for daemon port/socket cleanup")

        if is_llmster_running():
            logging.error(
                "Cannot start desktop app: daemon still running "
                "after stop verification"
            )
            notify_cmd = get_notify_send_cmd()
            if notify_cmd:
                self._run_validated_command(
                    [
                        notify_cmd,
                        "Error",
                        (
                            "Daemon could not be stopped. "
                            "Please stop it manually."
                        ),
                    ]
                )
            _rebuild_menu()
            return

        _rebuild_menu()

        app_found = False
        app_path = None

        dpkg_cmd = get_dpkg_cmd()
        if dpkg_cmd:
            try:
                result = _run_safe_command([dpkg_cmd, "-l"])
                if "lm-studio" in result.stdout:
                    resolved = shutil.which("lm-studio")
                    if resolved and os.path.isabs(resolved):
                        app_path = "lm-studio"
                        app_found = True
                        logging.info("Found LM Studio .deb package")
                    else:
                        logging.warning(
                            "dpkg lists lm-studio but executable missing "
                            "from PATH, searching for AppImage instead"
                        )
            except (OSError, subprocess.SubprocessError) as e:
                logging.warning("Error checking for .deb package: %s", e)

        if not app_found:
            search_paths = [
                _AppState.script_dir,
                os.path.expanduser("~/Apps"),
                os.path.expanduser("~/LM_Studio"),
                os.path.expanduser("~/Applications"),
                os.path.expanduser("~/.local/bin"),
                "/opt/lm-studio",
            ]
            for search_path in search_paths:
                if not os.path.isdir(search_path):
                    continue
                try:
                    candidates = [
                        f for f in os.listdir(search_path)
                        if _is_lm_studio_appimage_label(f)
                    ]
                    if not candidates:
                        continue
                    picked = sorted(candidates)[0]
                    app_path = os.path.join(search_path, picked)
                    app_found = True
                    logging.info("Found AppImage: %s", app_path)
                    break
                except (OSError, PermissionError) as e:
                    logging.warning(
                        "Error searching %s: %s", search_path, e
                    )

        if app_found and app_path:
            try:
                if app_path == "lm-studio":
                    resolved_path = shutil.which("lm-studio")
                    if not resolved_path or not os.path.isabs(resolved_path):
                        raise ValueError(
                            "lm-studio executable not found"
                            " in PATH"
                        )
                    app_path = resolved_path
                if not os.path.isabs(app_path):
                    raise ValueError(f"App path must be absolute: {app_path}")
                if not os.path.isfile(app_path):
                    raise ValueError(f"App path does not exist: {app_path}")
                if not os.access(app_path, os.X_OK):
                    raise ValueError(
                        f"App path is not executable: {app_path}"
                    )
                if not isinstance(app_path, str):
                    raise ValueError("App path must be a string")

                safe_paths = [
                    os.path.expanduser("~/Apps"),
                    os.path.expanduser("~/LM_Studio"),
                    os.path.expanduser("~/Applications"),
                    os.path.expanduser("~/.local/bin"),
                    "/opt/lm-studio",
                    "/usr/bin",
                    "/usr/local/bin",
                ]

                is_safe = any(
                    os.path.commonpath([app_path, safe_path]) == safe_path
                    for safe_path in safe_paths
                    if os.path.isdir(safe_path)
                )

                if shutil.which("lm-studio") == app_path:
                    is_safe = True

                if not is_safe:
                    msg = (
                        "App path not in safe locations: "
                        f"{app_path}"
                    )
                    raise ValueError(msg)

                cmd = [app_path]
                if app_path.lower().endswith(".appimage"):
                    cmd.append("--no-sandbox")

                if not isinstance(cmd, list) or not cmd:
                    raise ValueError("Command must be a non-empty list")
                if not all(isinstance(arg, str) for arg in cmd):
                    raise ValueError("All command arguments must be strings")
                if not os.path.isabs(cmd[0]):
                    raise ValueError(
                        f"Executable must be absolute path: {cmd[0]}"
                    )

                os.spawnv(os.P_NOWAIT, cmd[0], cmd)  # nosec B606

                self.lms_ps_resume_at = time.monotonic() + 12.0

                logging.info(
                    "Started LM Studio desktop app: %s",
                    app_path
                )
                notify_cmd = get_notify_send_cmd()
                if notify_cmd:
                    self._run_validated_command(
                        [
                            notify_cmd,
                            "LM Studio",
                            "LM Studio GUI is starting...",
                        ]
                    )
                _rebuild_menu()
                self._schedule_menu_refresh()
            except (OSError, subprocess.SubprocessError, ValueError) as e:
                logging.error("Failed to start desktop app: %s", e)
                notify_cmd = get_notify_send_cmd()
                if notify_cmd:
                    error_msg = "Failed to start app: " + str(e)
                    self._run_validated_command(
                        [notify_cmd, "Error", error_msg]
                    )
        else:
            logging.warning(
                "No LM Studio desktop app found (.deb or AppImage)"
            )
            notify_cmd = get_notify_send_cmd()
            if notify_cmd:
                self._run_validated_command(
                    [
                        notify_cmd,
                        "Error",
                        (
                            "No LM Studio desktop app found.\n"
                            "Please install from "
                            "https://lmstudio.ai/download"
                        ),
                    ]
                )

    def stop_desktop_app(self, _widget: object) -> None:
        """Stop the LM Studio desktop app process.

        Useful when the window closes to tray but the process remains active.

        Args:
            _widget: Widget that triggered the action (unused).
        """
        if not self.begin_action_cooldown("stop_desktop_app"):
            return

        desktop_pids = get_desktop_app_pids()
        if not desktop_pids:
            logging.info("No LM Studio desktop app process found to stop")
            notify_cmd = get_notify_send_cmd()
            if notify_cmd:
                self._run_validated_command(
                    [
                        notify_cmd,
                        "LM Studio",
                        "No running desktop app found",
                    ]
                )
            return

        try:
            stopped = self._stop_desktop_app_processes()

            if stopped:
                logging.info("LM Studio desktop app stopped")
                notify_cmd = get_notify_send_cmd()
                if notify_cmd:
                    self._run_validated_command(
                        [
                            notify_cmd,
                            "LM Studio",
                            "Desktop app stopped",
                        ]
                    )
            else:
                logging.warning("Failed to stop desktop app processes")
                notify_cmd = get_notify_send_cmd()
                if notify_cmd:
                    self._run_validated_command(
                        [
                            notify_cmd,
                            "LM Studio",
                            "Desktop app may still be running",
                        ]
                    )

            self.build_menu()
            self._schedule_menu_refresh()
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            logging.error("Failed to stop desktop app: %s", e)
            notify_cmd = get_notify_send_cmd()
            if notify_cmd:
                self._run_validated_command(
                    [
                        notify_cmd,
                        "Error",
                        "Desktop app stop failed: " + str(e),
                    ]
                )

    def quit_app(self, _widget):
        """Handle the tray quit action by logging and exiting the Gtk main
        loop.
        """
        logging.info("Tray icon terminated")
        gtk = _AppState.Gtk
        if gtk is None:
            logging.error(
                "GTK module is not initialized; "
                "cannot quit main loop"
            )
            return
        gtk.main_quit()

    def show_status_dialog(self, _widget):
        """
        Show a GTK message dialog containing the LM Studio CLI status output.

        Runs `lms ps` to retrieve status information. If daemon is not
        running, falls back to querying the LM Studio API directly.
        Formats a friendly message on success or error, and displays it in
        an informational dialog. Errors are caught and shown to the user
        instead of raising.

        To avoid misleading the user, the CLI output is inspected for a
        *loaded* model.  Some versions of `lms ps` simply list all
        **available** models even when none are active, which would make the
        tray think a model is loaded.  The helper ``_has_loaded_model``
        implements a simple heuristic to ignore such outputs.
        """
        _ = _widget
        text = "No models loaded or error."

        def _models_text_from_api():
            """Return loaded-model text from API or default error text."""
            try:
                api_url = get_api_models_url()
                _validate_url_scheme(api_url)
                req = urllib_request.Request(
                    api_url,
                    headers={"User-Agent": "lmstudio-tray-manager"},
                )
                with urllib_request.urlopen(  # nosec B310
                    req, timeout=2
                ) as response:
                    payload = response.read()
                    data = json.loads(payload.decode("utf-8"))

                if isinstance(data, dict):
                    models = data.get("data", [])
                    loaded_models = _api_loaded_model_names(models)
                    if len(loaded_models) > 0:
                        model_names = "\n".join(loaded_models)
                        return (
                            "Models loaded via desktop app:\n"
                            f"{model_names}"
                        )
            except (
                urllib_error.HTTPError,
                urllib_error.URLError,
                OSError,
                ValueError,
                UnicodeDecodeError,
                json.JSONDecodeError,
            ):
                return "No models loaded or error."

            return "No models loaded or error."

        try:
            lms_cmd = get_lms_cmd()
            daemon_running = self.get_daemon_status() == "running"
            app_running = self.get_desktop_app_status() == "running"
            can_use_lms_ps = self._can_use_lms_ps(
                daemon_running,
                app_running,
            )

            if lms_cmd and can_use_lms_ps:
                result = _run_safe_command([lms_cmd, "ps"])
                if result.returncode == 0:
                    if _has_loaded_model(result.stdout):
                        text = _format_lms_ps_output(result.stdout.strip())
                    else:
                        text = "No models loaded or error."
                else:
                    text = _models_text_from_api()
            else:
                text = _models_text_from_api()
        except (
            OSError,
            RuntimeError,
            subprocess.SubprocessError,
            subprocess.TimeoutExpired
        ) as e:
            text = f"Error retrieving status: {str(e)}"

        gtk = _AppState.Gtk
        if gtk is None:
            logging.error(
                "GTK module is not initialized; cannot show status dialog"
            )
            return

        dialog = gtk.MessageDialog(
            parent=None,
            modal=True,
            message_type=gtk.MessageType.INFO,
            buttons=gtk.ButtonsType.OK,
            text="LM Studio Status"
        )
        dialog.format_secondary_text(text)
        self._apply_status_dialog_style(dialog)
        dialog.run()
        dialog.destroy()

    @staticmethod
    def _apply_status_dialog_style(dialog) -> None:
        """Render the status text monospaced and unwrapped.

        The labelled blocks only line up in a fixed-width font, and letting
        GTK wrap them would reintroduce the very problem the formatting
        avoids. Every step is optional: test doubles for Gtk do not
        implement the message-area API, and a missing widget must not stop
        the dialog from being shown.
        """
        get_message_area = getattr(dialog, "get_message_area", None)
        if not callable(get_message_area):
            return

        try:
            message_area = get_message_area()
            children = message_area.get_children()
        except (AttributeError, TypeError):
            return

        # The secondary label is the last child of the message area.
        for label in children[1:]:
            for setter, value in (
                ("set_line_wrap", False),
                ("set_selectable", True),
            ):
                method = getattr(label, setter, None)
                if callable(method):
                    method(value)

            set_markup = getattr(label, "set_markup", None)
            get_text = getattr(label, "get_text", None)
            if callable(set_markup) and callable(get_text):
                set_markup(f"<tt>{_escape_markup(get_text())}</tt>")

    def _drain_gtk_events(self, gtk_module):
        """Drain pending GTK events when the API is available.

        Some test doubles for Gtk do not provide events_pending/
        main_iteration_do. Guarding these calls keeps dialog cleanup
        behavior in production while remaining test-friendly.
        """
        events_pending = getattr(gtk_module, "events_pending", None)
        main_iteration_do = getattr(gtk_module, "main_iteration_do", None)
        if not callable(events_pending) or not callable(main_iteration_do):
            return
        while events_pending():
            main_iteration_do(False)

    def show_about_dialog(self, _widget):
        """Show application information in a GTK dialog."""
        gtk = _AppState.Gtk
        gdk_pixbuf = _AppState.GdkPixbuf
        glib = _AppState.GLib

        if gtk is None:
            logging.error(
                "GTK module is not initialized; cannot show about dialog"
            )
            return

        dialog = gtk.AboutDialog()
        dialog.set_program_name(APP_NAME)
        dialog.set_version(self.get_version_label())
        dialog.set_authors(get_authors())

        if (
            self.update_status == "Update available"
            and self.latest_update_version
        ):
            dialog.set_website(get_release_url(self.latest_update_version))
            dialog.set_website_label("Release")
        else:
            dialog.set_website(APP_REPOSITORY)
            dialog.set_website_label("GitHub Repository")

        comment_text = (
            "Monitors and controls LM Studio daemon and desktop app."
        )
        dialog.set_comments(comment_text)
        dialog.set_copyright(f"© 2025-2026 {APP_MAINTAINER}")
        dialog.set_license("This program comes WITHOUT ANY WARRANTY.")

        def _iter_children(widget):
            if not hasattr(widget, "get_children"):
                return []
            try:
                return widget.get_children()
            except (AttributeError, TypeError, ValueError):
                return []

        def _find_label(widget, target):
            for child in _iter_children(widget):
                if hasattr(child, "get_text"):
                    try:
                        if child.get_text() == target:
                            return child
                    except (AttributeError, TypeError, ValueError):
                        pass
                found = _find_label(child, target)
                if found is not None:
                    return found
            return None

        def _insert_link(parent, text, label, after_widget):
            link_label = gtk.Label()
            link_label.set_markup(f'<a href="{text}">{label}</a>')
            align_center = getattr(
                getattr(gtk, "Align", object),
                "CENTER",
                0.5
            )
            try:
                link_label.set_halign(align_center)
            except (AttributeError, TypeError, ValueError):
                pass
            if hasattr(link_label, "set_xalign"):
                link_label.set_xalign(0.5)
            link_label.connect(
                "activate-link",
                lambda _w, uri: _activate_link(uri),
            )
            parent.pack_start(link_label, False, False, 0)
            if after_widget is not None and hasattr(parent, "reorder_child"):
                try:
                    idx = parent.get_children().index(after_widget)
                    parent.reorder_child(link_label, idx + 1)
                except (AttributeError, TypeError, ValueError):
                    pass
            link_label.show()
            return link_label

        content_area = dialog.get_content_area()
        comment_label = _find_label(content_area, comment_text)
        if comment_label is not None and hasattr(comment_label, "get_parent"):
            try:
                parent_box = comment_label.get_parent()
            except (AttributeError, TypeError, ValueError):
                parent_box = content_area
        else:
            parent_box = content_area

        _insert_link(parent_box, APP_DOCUMENTATION, "Documentation",
                     comment_label)

        is_frozen = getattr(sys, "_MEIPASS", None) is not None
        logo_loaded = False

        if gdk_pixbuf is not None:
            error_types = (OSError,)
            if glib is not None:
                error_types = (OSError, glib.Error)

            primary_ext = "png" if is_frozen else "svg"
            fallback_ext = "svg" if is_frozen else "png"

            for ext in (primary_ext, fallback_ext):
                logo_path = get_asset_path(
                    "img", f"lm-studio-tray-manager.{ext}"
                )
                if not logo_path:
                    continue

                try:
                    logo = gdk_pixbuf.Pixbuf.new_from_file_at_scale(
                        logo_path, 128, 128, True
                    )
                    dialog.set_logo(logo)
                    logo_loaded = True
                    break
                except error_types as e:
                    log_level = (
                        logging.DEBUG if (is_frozen and ext == "svg")
                        else logging.WARNING
                    )
                    logging.log(
                        log_level,
                        "Failed to load logo from %s: %s",
                        logo_path,
                        e,
                    )

            if not logo_loaded:
                logging.debug(
                    "Could not load any logo format"
                )
        else:
            logging.debug("GdkPixbuf not initialized; skipping logo")

        dialog.set_modal(True)
        dialog.run()
        dialog.destroy()
        self._drain_gtk_events(gtk)

    def show_config_dialog(self, _widget):
        """Show configuration dialog for LM Studio API endpoint."""
        gtk = _AppState.Gtk
        if gtk is None:
            logging.error(
                "GTK module is not initialized; cannot show config dialog"
            )
            return

        dialog = gtk.Dialog(
            title="Configuration",
            modal=True,
        )
        dialog.add_buttons(
            "Cancel",
            gtk.ResponseType.CANCEL,
            "Save",
            gtk.ResponseType.OK,
        )

        content = dialog.get_content_area()
        grid = gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(6)

        host_label = gtk.Label(label="LM Studio API host")
        host_label.set_halign(gtk.Align.START)
        host_entry = gtk.Entry()
        host_entry.set_text(_AppState.API_HOST)

        port_label = gtk.Label(label="LM Studio API port")
        port_label.set_halign(gtk.Align.START)
        port_entry = gtk.Entry()
        port_entry.set_text(str(_AppState.API_PORT))

        grid.attach(host_label, 0, 0, 1, 1)
        grid.attach(host_entry, 1, 0, 1, 1)
        grid.attach(port_label, 0, 1, 1, 1)
        grid.attach(port_entry, 1, 1, 1, 1)

        content.add(grid)
        dialog.show_all()

        response = dialog.run()
        if response == gtk.ResponseType.OK:
            host = host_entry.get_text().strip()
            port = _normalize_api_port(port_entry.get_text())
            if host and port is not None:
                try:
                    save_config(host, port)
                    _AppState.API_HOST = host
                    _AppState.API_PORT = port
                    logging.info(
                        "Updated API endpoint to http://%s:%s",
                        host,
                        port,
                    )
                except (OSError, ValueError) as exc:
                    logging.error(
                        "Failed to save configuration: %s",
                        exc,
                        exc_info=True,
                    )
                    error_dialog = gtk.MessageDialog(
                        parent=dialog,
                        modal=True,
                        message_type=gtk.MessageType.ERROR,
                        buttons=gtk.ButtonsType.OK,
                        text=(
                            "Failed to save configuration.\n"
                            "Please check disk space and permissions."
                        ),
                    )
                    error_dialog.run()
                    error_dialog.destroy()
                    self._drain_gtk_events(gtk)
            else:
                logging.warning("Invalid API host/port; config not saved")

        dialog.destroy()
        self._drain_gtk_events(gtk)

    def get_version_label(self) -> str:
        """Return version text with update status for the About dialog.

        The version string is deliberately kept free of URLs; when an update
        is available the corresponding link is surfaced via the dialog's
        "website" field instead (see :meth:`show_about_dialog`).

        Returns:
            str: Version text in the format '<APP_VERSION> (<status>)'.
        """
        status = self.update_status or "Unknown"
        if status == "Update available" and self.latest_update_version:
            status = f"Update available: {self.latest_update_version}"
        return f"{_AppState.APP_VERSION} ({status})"

    def _check_updates_tick(self) -> bool:
        """Run the update check for scheduled timers."""
        self.check_updates()
        return True

    def _initial_update_check(self) -> bool:
        """Run a single update check shortly after startup."""
        self.check_updates()
        return False

    def _format_update_check_message(
        self,
        status: str,
        latest: Optional[str],
        error: Optional[str],
    ) -> str:
        """Build the update check notification message."""
        if status == "Update available" and latest:
            url = get_release_url(latest)
            return (
                "New version available: "
                f"{latest} (current {_AppState.APP_VERSION}) {url}"
            )

        messages = {
            "Up to date": f"You are up to date ({_AppState.APP_VERSION})",
            "Ahead of release": (
                f"Ahead of release "
                f"(current {_AppState.APP_VERSION}, latest {latest})"
            ),
            "Dev build": "Dev build: update checks disabled",
        }
        message = messages.get(status)
        if message:
            return message

        detail = f" ({error})" if error else ""
        return "Unable to check for updates." + detail

    def manual_check_updates(self, _widget: object) -> None:
        """Run update check on demand and notify about the result."""
        notified = self.check_updates()
        notify_cmd = get_notify_send_cmd()
        if not notify_cmd or notified:
            return

        status = self.update_status or "Unknown"
        latest = self.latest_update_version
        error = self.last_update_error
        message = self._format_update_check_message(status, latest, error)

        self._run_validated_command([notify_cmd, "Update Check", message])

    def check_updates(self) -> bool:
        """Check GitHub for a newer release and notify the user.

        Returns:
            bool: True if a notification was sent.
        """
        if _AppState.APP_VERSION == DEFAULT_APP_VERSION:
            self.update_status = "Dev build"
            logging.debug("Update check skipped: dev build")
            return False

        latest, error = get_latest_release_version()
        self.last_update_error = error
        if not latest:
            self.update_status = "Unknown"
            logging.debug("Update check failed: %s", error)
            return False

        self.latest_update_version = latest
        self.last_update_error = None

        newer = is_newer_version(_AppState.APP_VERSION, latest)
        current_parts = parse_version(_AppState.APP_VERSION)
        latest_parts = parse_version(latest)
        is_ahead = current_parts > latest_parts if (
            current_parts and latest_parts
        ) else False

        if newer:
            self.update_status = "Update available"
        elif is_ahead:
            self.update_status = "Ahead of release"
        else:
            self.update_status = "Up to date"

        logging.debug(
            "Update check status: %s (latest %s)",
            self.update_status,
            latest,
        )

        if not newer:
            return False

        if self.last_update_version == latest:
            return False

        self.last_update_version = latest
        notify_cmd = get_notify_send_cmd()
        if notify_cmd:
            url = get_release_url(latest)
            message = (
                "New version available: "
                f"{latest} (current {_AppState.APP_VERSION}) {url}"
            )
            self._run_validated_command(
                [notify_cmd, "Update Available", message]
            )
            return True
        return False

    def check_model(self) -> bool:
        """Check LM Studio runtime/model status and update tray icon.

        The ``_has_loaded_model`` helper is used to interpret the output of
        ``lms ps``.  This keeps the icon from flipping to OK when the CLI
        merely reports a catalogue of available models.

        Updates the tray icon using this schema:
        - FAIL: neither daemon nor desktop app is installed
        - WARN: neither daemon nor desktop app is running
        - INFO: daemon or desktop app is running, but no model loaded
        - OK: a model is loaded

        Sends desktop notifications when status changes from a
        previous non-None state, and logs status changes and errors.

        Returns:
            bool: True to indicate the check completed (used for
            scheduled callbacks).
        """
        try:
            lms_cmd = get_lms_cmd()
            current_status = None
            reason = ""
            daemon_status = self.get_daemon_status()
            app_status = self.get_desktop_app_status()

            daemon_running = daemon_status == "running"
            app_running = app_status == "running"
            any_running = daemon_running or app_running
            both_missing = (
                daemon_status == "not_found" and app_status == "not_found"
            )

            if both_missing:
                current_status = "FAIL"
                reason = "daemon and desktop app not installed"
                self.indicator.set_icon_full(
                    ICON_FAIL,
                    "Daemon and desktop app not installed"
                )
            elif not any_running:
                current_status = "WARN"
                reason = "daemon and desktop app stopped"
                self.indicator.set_icon_full(
                    ICON_WARN,
                    "Daemon and desktop app stopped"
                )
            else:
                if daemon_running and lms_cmd:
                    can_use_lms_ps = self._can_use_lms_ps(
                        daemon_running,
                        app_running,
                    )
                    if can_use_lms_ps:
                        result = _run_safe_command([lms_cmd, "ps"])
                        if result.returncode == 0:
                            if _has_loaded_model(result.stdout):
                                current_status = "OK"
                                reason = "lms ps indicates model loaded"
                                self.indicator.set_icon_full(
                                    ICON_OK, "Model loaded"
                                )
                            else:
                                current_status = "INFO"
                                reason = "lms ps indicates no model loaded"
                                self.indicator.set_icon_full(
                                    ICON_INFO,
                                    "No model loaded"
                                )
                        else:
                            if check_api_models():
                                current_status = "OK"
                                reason = "API reported models loaded"
                                self.indicator.set_icon_full(
                                    ICON_OK,
                                    "Model loaded"
                                )
                            else:
                                current_status = "INFO"
                                reason = "API reported no models"
                                self.indicator.set_icon_full(
                                    ICON_INFO,
                                    "No model loaded"
                                )
                    elif any_running and check_api_models():
                        current_status = "OK"
                        reason = "API reported models loaded"
                        self.indicator.set_icon_full(
                            ICON_OK,
                            "Model loaded",
                        )
                    else:
                        current_status = "INFO"
                        reason = "running, no model via API"
                        self.indicator.set_icon_full(
                            ICON_INFO,
                            "No model loaded",
                        )
                elif app_running and lms_cmd:
                    can_use_lms_ps = self._can_use_lms_ps(
                        daemon_running,
                        app_running,
                    )
                    if can_use_lms_ps:
                        result = _run_safe_command([lms_cmd, "ps"])
                        if result.returncode == 0:
                            if _has_loaded_model(result.stdout):
                                current_status = "OK"
                                reason = "lms ps indicates model loaded"
                                self.indicator.set_icon_full(
                                    ICON_OK,
                                    "Model loaded",
                                )
                            else:
                                current_status = "INFO"
                                reason = "lms ps indicates no model loaded"
                                self.indicator.set_icon_full(
                                    ICON_INFO,
                                    "No model loaded",
                                )
                        elif check_api_models():
                            current_status = "OK"
                            reason = "API reported models loaded"
                            self.indicator.set_icon_full(
                                ICON_OK,
                                "Model loaded",
                            )
                        else:
                            current_status = "INFO"
                            reason = "API reported no models"
                            self.indicator.set_icon_full(
                                ICON_INFO,
                                "No model loaded",
                            )
                    elif any_running and check_api_models():
                        current_status = "OK"
                        reason = "API reported models loaded"
                        self.indicator.set_icon_full(
                            ICON_OK,
                            "Model loaded",
                        )
                    else:
                        current_status = "INFO"
                        reason = "running, no model via API"
                        self.indicator.set_icon_full(
                            ICON_INFO,
                            "No model loaded",
                        )
                elif any_running and check_api_models():
                    current_status = "OK"
                    reason = "API reported models loaded"
                    self.indicator.set_icon_full(ICON_OK, "Model loaded")
                else:
                    current_status = "INFO"
                    reason = "running, no model via API"
                    self.indicator.set_icon_full(
                        ICON_INFO,
                        "No model loaded"
                    )

            if (
                self.last_status != current_status
                and self.last_status is not None
            ):
                logging.debug(
                    "Status change reason: %s -> %s (%s)",
                    self.last_status,
                    current_status,
                    reason,
                )
                notify_cmd = get_notify_send_cmd()
                if notify_cmd:
                    if current_status == "OK":
                        msg = "✅ A model is loaded"
                        self._run_validated_command(
                            [notify_cmd, "LM Studio", msg]
                        )
                    elif current_status == "INFO":
                        info_msg = ("ℹ️ Daemon or desktop app is running, "
                                    + "but no model is loaded")
                        self._run_validated_command(
                            [
                                notify_cmd,
                                "LM Studio",
                                info_msg,
                            ]
                        )
                    elif current_status == "WARN":
                        self._run_validated_command(
                            [
                                notify_cmd,
                                "LM Studio",
                                "⚠️ Neither daemon nor desktop app is running",
                            ]
                        )
                    elif current_status == "FAIL":
                        self._run_validated_command(
                            [
                                notify_cmd,
                                "LM Studio",
                                "❌ Daemon and desktop app are not installed",
                            ]
                        )
                logging.info(
                    "Status change: %s -> %s",
                    self.last_status,
                    current_status
                )
                self.build_menu()

            self.last_status = current_status
            self.build_menu()

        except subprocess.TimeoutExpired:
            logging.debug("Timeout in lms ps check (keeping previous status)")
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            self.indicator.set_icon_full(ICON_FAIL, "Error checking status")
            logging.error("Error in status check: %s", e)
            self.build_menu()
        return True


class MacOSTrayIcon(_RumpsBase):
    """macOS menu-bar tray using the ``rumps`` library.

    Provides the same runtime monitoring and daemon/desktop-app control
    as :class:`TrayIcon` but is implemented on top of PyObjC/rumps rather
    than GTK3/AppIndicator.  Menu items are rebuilt on every status change
    so that the correct start/stop actions are always shown.
    """

    _APP_LOCATIONS = [
        "/Applications/LM Studio.app",
        os.path.expanduser("~/Applications/LM Studio.app"),
    ]

    def __init__(self) -> None:
        """Initialize the macOS tray icon and start monitoring timers."""
        if _rumps_lib is None:
            raise RuntimeError(
                "rumps is not installed; cannot create MacOSTrayIcon"
            )
        super().__init__("LM Studio", quit_button=None)
        self.last_status = None
        self.action_lock_until = 0.0
        self.lms_ps_resume_at = 0.0
        self.remote_loaded_models: list[str] = []
        self._seen_desktop_call = False
        self._last_desktop_detection = None
        self._desktop_detection = {
            "seen_call": False,
            "last_detection": None,
        }
        self.last_update_version = None
        self.update_status = "Unknown"
        self.latest_update_version = None
        self.last_update_error = None
        self._update_info = {
            "status": "Unknown",
            "last_error": None,
            "latest_version": None,
            "last_version": None,
        }
        self.title = "⚠️"
        self.build_menu()

        self._status_timer = _rumps_lib.Timer(
            self._check_model_tick, INTERVAL
        )
        self._status_timer.start()

        self._update_timer = _rumps_lib.Timer(
            self._update_check_tick, UPDATE_CHECK_INTERVAL
        )
        self._update_timer.start()

        self._initial_timer = _rumps_lib.Timer(
            self._initial_update_check_once, 5
        )
        self._initial_timer.start()

        if _AppState.AUTO_START_DAEMON:
            threading.Thread(
                target=self._maybe_auto_start_daemon,
                daemon=True,
                name="macos-auto-start",
            ).start()
        if _AppState.GUI_MODE:
            threading.Thread(
                target=self._maybe_start_gui,
                daemon=True,
                name="macos-auto-gui",
            ).start()

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def get_daemon_status(self) -> str:
        """Check if llmster headless daemon is running.

        Returns:
            str: ``"running"``, ``"stopped"``, or ``"not_found"``.
        """
        try:
            if not is_daemon_available():
                return "not_found"
            if is_llmster_running():
                return "running"
            return "stopped"
        except (
            OSError,
            subprocess.SubprocessError,
            subprocess.TimeoutExpired,
        ):
            return "not_found"

    def get_desktop_app_status(self) -> str:
        """Check if LM Studio desktop app is running or installed (macOS).

        Returns:
            str: ``"running"``, ``"stopped"``, or ``"not_found"``.
        """
        try:
            if get_desktop_app_pids():
                return "running"
        except (OSError, subprocess.SubprocessError):
            pass

        for loc in self._APP_LOCATIONS:
            if os.path.isdir(loc):
                detection = f"app:{loc}"
                if (
                    not self._desktop_detection["seen_call"]
                    or detection != self._desktop_detection["last_detection"]
                ):
                    logging.debug(
                        "Detected LM Studio.app at %s", loc
                    )
                    self._desktop_detection["last_detection"] = detection
                    self._desktop_detection["seen_call"] = True
                    self._seen_desktop_call = True
                return "stopped"

        detection = "none"
        if (
            not self._desktop_detection["seen_call"]
            or detection != self._desktop_detection["last_detection"]
        ):
            logging.debug("No LM Studio desktop app found")
            self._desktop_detection["last_detection"] = detection
            self._desktop_detection["seen_call"] = True
            self._seen_desktop_call = True
        return "not_found"

    def get_status_indicator(self, status: str) -> str:
        """Return an emoji indicator for a status string.

        Args:
            status (str): One of ``"running"``, ``"stopped"``,
                ``"not_found"``.

        Returns:
            str: Emoji representing the status.
        """
        if status == "running":
            return "🟢"
        if status == "stopped":
            return "🟡"
        return "🔴"

    # ------------------------------------------------------------------
    # Notification
    # ------------------------------------------------------------------

    _base_title = getattr(_RumpsBase, "title", None)

    @property
    def title(self):
        """Menu-bar title text.

        Returns:
            The current status-item title.
        """
        if not isinstance(type(self)._base_title, property):
            return self.__dict__.get("_title")
        return type(self)._base_title.fget(self)

    @title.setter
    def title(self, value) -> None:
        """Set the menu-bar title from any thread.

        The status item is an AppKit object, so the assignment is
        marshalled onto the main thread when called from a worker.

        Args:
            value: New title text.
        """
        base = type(self)._base_title
        if not isinstance(base, property):
            self.__dict__["_title"] = value
            return

        def _apply() -> None:
            base.fset(self, value)

        if not is_main_thread():
            if run_on_main_thread(_apply):
                return
        _apply()

    def _notify(self, title: str, message: str) -> None:
        """Send a macOS notification.

        A Developer ID signed bundle has a registered notification identity,
        so the native API delivers banners carrying this app's own icon. An
        ad-hoc or unsigned build has no such identity and macOS discards its
        notifications silently, so ``osascript`` stands in -- at the cost of
        showing the Script Editor icon.

        Args:
            title (str): Notification title.
            message (str): Notification body text.
        """
        if is_signed_bundle():
            if self._notify_via_rumps(title, message):
                return
            _notify_via_osascript(title, message)
            return

        if _notify_via_osascript(title, message):
            return
        self._notify_via_rumps(title, message)

    def _notify_via_rumps(self, title: str, message: str) -> bool:
        """Post a notification through rumps' native API.

        Args:
            title (str): Notification title.
            message (str): Notification body text.

        Returns:
            bool: ``True`` when rumps accepted the notification. Note that
            macOS may still drop it for an unregistered bundle without
            raising, which is why the caller checks the signature first.
        """
        rumps_lib = _rumps_lib
        if rumps_lib is None:
            logging.debug("Notification skipped: rumps is not installed")
            return False

        if not is_main_thread():
            if run_on_main_thread(
                lambda: self._notify_via_rumps(title, message)
            ):
                return True

        try:
            try:
                rumps_lib.notification(
                    title=title,
                    subtitle="",
                    message=message,
                    sound=False,
                )
            except TypeError:
                rumps_lib.notification(
                    title=title,
                    subtitle="",
                    message=message,
                    _sound=False,
                )
        except (AttributeError, OSError, RuntimeError, TypeError) as exc:
            logging.debug("Notification failed: %s", exc)
            return False
        return True

    # ------------------------------------------------------------------
    # Menu building
    # ------------------------------------------------------------------

    def build_menu(self) -> None:
        """Rebuild the macOS menu-bar menu with current status.

        Safe to call from any thread: the actual AppKit mutation is
        marshalled onto the main thread, since touching ``NSMenu`` from a
        worker thread crashes the app and can wedge the WindowServer.
        """
        if not is_main_thread():
            if run_on_main_thread(self._build_menu_impl):
                return
        self._build_menu_impl()

    def _build_options_menu(self, rumps_lib):
        """Return the shared Options submenu.

        Args:
            rumps_lib: The rumps module.

        Returns:
            The populated Options menu item.
        """
        options = rumps_lib.MenuItem("Options")
        options.add(
            rumps_lib.MenuItem(
                "Configuration",
                callback=self.show_config_dialog,
            )
        )

        # Launching at login is not managed here: macOS already offers it
        # under System Settings > General > Login Items, and duplicating that
        # in a LaunchAgent only adds a second place for the setting to drift.
        options.add(
            rumps_lib.MenuItem(
                "Check for Updates",
                callback=self.manual_check_updates,
            )
        )
        options.add(
            rumps_lib.MenuItem(
                "About",
                callback=self.show_about_dialog,
            )
        )
        return options

    def _build_remote_menu_items(self, rumps_lib) -> list:
        """Return menu entries for a remote endpoint.

        Start/stop actions operate on local processes, so they are omitted
        here rather than offered as controls that cannot work.

        Args:
            rumps_lib: The rumps module.

        Returns:
            list: Menu items describing the remote endpoint.
        """
        endpoint = f"{_AppState.API_HOST}:{_AppState.API_PORT}"
        names = getattr(self, "remote_loaded_models", []) or []

        if self.last_status == "OK":
            indicator = "🟢"
            if len(names) == 1:
                state = f"{_shorten_model_name(names[0])} loaded"
            elif len(names) > 1:
                state = f"{len(names)} models loaded"
            else:
                state = "Model loaded"
        elif self.last_status == "INFO":
            indicator, state = "🟡", "No model loaded"
        else:
            indicator, state = "🔴", "Unreachable"

        items = [
            rumps_lib.MenuItem(f"{indicator} Remote: {endpoint}"),
            rumps_lib.MenuItem(f"  → {state}"),
        ]
        if len(names) > 1:
            items.extend(
                rumps_lib.MenuItem(f"     • {_shorten_model_name(name)}")
                for name in names
            )
        return items

    def _build_menu_impl(self) -> None:
        """Rebuild the menu. Must run on the main thread."""
        rumps_lib = _rumps_lib
        if rumps_lib is None:
            raise RuntimeError("rumps is not installed")

        if is_remote_endpoint():
            items = self._build_remote_menu_items(rumps_lib)
            items.append(None)
            items.append(
                rumps_lib.MenuItem(
                    "Show Status",
                    callback=self.show_status_dialog,
                )
            )
            items.append(self._build_options_menu(rumps_lib))
            items.append(None)
            items.append(
                rumps_lib.MenuItem("Quit Tray", callback=self.quit_app)
            )
            self.menu.clear()
            self.menu.update(items)
            return

        daemon_status = self.get_daemon_status()
        app_status = self.get_desktop_app_status()
        d_ind = self.get_status_indicator(daemon_status)
        a_ind = self.get_status_indicator(app_status)

        items = []

        if daemon_status == "running":
            items.append(
                rumps_lib.MenuItem(f"{d_ind} Daemon (Running)")
            )
            items.append(
                rumps_lib.MenuItem(
                    "  \u2192 Stop Daemon",
                    callback=self.stop_daemon,
                )
            )
        elif daemon_status == "stopped":
            items.append(
                rumps_lib.MenuItem(
                    f"{d_ind} Start Daemon (Headless)",
                    callback=self.start_daemon,
                )
            )
        else:
            items.append(
                rumps_lib.MenuItem(
                    f"{d_ind} Daemon (Not Installed)"
                )
            )

        if app_status == "running":
            items.append(
                rumps_lib.MenuItem(f"{a_ind} Desktop App (Running)")
            )
            items.append(
                rumps_lib.MenuItem(
                    "  \u2192 Stop Desktop App",
                    callback=self.stop_desktop_app,
                )
            )
        elif app_status == "stopped":
            items.append(
                rumps_lib.MenuItem(
                    f"{a_ind} Start Desktop App",
                    callback=self.start_desktop_app,
                )
            )
        else:
            items.append(
                rumps_lib.MenuItem(
                    f"{a_ind} Desktop App (Not Installed)"
                )
            )

        items.append(None)

        items.append(
            rumps_lib.MenuItem(
                "Show Status",
                callback=self.show_status_dialog,
            )
        )

        items.append(self._build_options_menu(rumps_lib))

        items.append(None)

        items.append(
            rumps_lib.MenuItem(
                "Quit Tray",
                callback=self.quit_app,
            )
        )

        self.menu.clear()
        self.menu.update(items)

    # ------------------------------------------------------------------
    # Timer callbacks
    # ------------------------------------------------------------------

    def _check_model_tick(self, _sender: object) -> None:
        """Periodic timer callback that runs check_model."""
        self.check_model()

    def _update_check_tick(self, _sender: object) -> None:
        """Periodic timer callback that runs check_updates."""
        self.check_updates()

    def _initial_update_check_once(self, sender: object) -> None:
        """One-shot timer: run update check then stop the timer."""
        self.check_updates()
        sender.stop()

    def _schedule_menu_refresh(self, delay_seconds: float = 2) -> None:
        """Schedule a delayed menu rebuild using a background thread.

        Args:
            delay_seconds (int): Seconds to wait before rebuilding.
        """
        def _refresh():
            self.build_menu()

        t = threading.Timer(delay_seconds, _refresh)
        t.daemon = True
        t.start()

    # ------------------------------------------------------------------
    # Action cooldown
    # ------------------------------------------------------------------

    def begin_action_cooldown(
        self, action_name: str, seconds: float = 2.0
    ) -> bool:
        """Prevent rapid double-triggering of tray actions.

        Args:
            action_name (str): Name used for logging.
            seconds (float): Cooldown duration in seconds.

        Returns:
            bool: ``True`` when the action may proceed.
        """
        now = time.monotonic()
        if now < self.action_lock_until:
            remaining = self.action_lock_until - now
            logging.info(
                "Action blocked by cooldown: %s (%.1fs remaining)",
                action_name,
                remaining,
            )
            return False
        self.action_lock_until = now + seconds
        return True

    # ------------------------------------------------------------------
    # Status / model check
    # ------------------------------------------------------------------

    def _check_remote_status(self) -> tuple[str, str]:
        """Determine status for a remote endpoint via the HTTP API.

        Local process detection says nothing about another machine, so the
        API is the only signal available here.

        Returns:
            tuple[str, str]: ``(status, reason)`` where status is one of
            ``"OK"``, ``"INFO"`` or ``"WARN"``.
        """
        reachable, names = query_api_models()
        # Cached so the menu can name the model without re-querying on
        # every rebuild.
        self.remote_loaded_models = names
        if not reachable:
            self.title = "⚠️"
            return ("WARN", "remote endpoint unreachable")
        if names:
            self.title = "✅"
            return ("OK", "remote API reported models loaded")
        self.title = "ℹ️"
        return ("INFO", "remote API reachable, no model loaded")

    def _finish_status_check(
        self, current_status: Optional[str], reason: str
    ) -> None:
        """Emit transition notifications and refresh the menu.

        Args:
            current_status: Newly determined status, or ``None``.
            reason: Human-readable explanation used for logging.
        """
        if (
            self.last_status != current_status
            and self.last_status is not None
        ):
            logging.debug(
                "Status change: %s -> %s (%s)",
                self.last_status,
                current_status,
                reason,
            )
            remote = is_remote_endpoint()
            if current_status == "OK":
                self._notify("LM Studio", "✅ A model is loaded")
            elif current_status == "INFO":
                self._notify(
                    "LM Studio",
                    "ℹ️ Runtime active, no model loaded",
                )
            elif current_status == "WARN":
                self._notify(
                    "LM Studio",
                    "⚠️ Remote endpoint is unreachable"
                    if remote
                    else "⚠️ Neither daemon nor desktop app is running",
                )
            elif current_status == "FAIL":
                self._notify(
                    "LM Studio",
                    "❌ Daemon and desktop app are not installed",
                )
            logging.info(
                "Status change: %s -> %s",
                self.last_status,
                current_status,
            )
            self.build_menu()

        self.last_status = current_status
        self.build_menu()

    def check_model(self) -> bool:
        """Check LM Studio status and update the menu-bar title emoji.

        Updates the menu-bar title according to the FAIL/WARN/INFO/OK
        schema used by the Linux backend and sends macOS notifications
        on status transitions.

        Returns:
            bool: Always ``True`` (keeps timer active).
        """
        try:
            lms_cmd = get_lms_cmd()
            current_status = None
            reason = ""

            if is_remote_endpoint():
                current_status, reason = self._check_remote_status()
                self._finish_status_check(current_status, reason)
                return True

            daemon_status = self.get_daemon_status()
            app_status = self.get_desktop_app_status()

            daemon_running = daemon_status == "running"
            app_running = app_status == "running"
            any_running = daemon_running or app_running
            both_missing = (
                daemon_status == "not_found"
                and app_status == "not_found"
            )

            if both_missing:
                current_status = "FAIL"
                reason = "daemon and desktop app not installed"
                self.title = "❌"
            elif not any_running:
                current_status = "WARN"
                reason = "daemon and desktop app stopped"
                self.title = "⚠️"
            else:
                now = time.monotonic()
                can_use_lms_ps = (
                    daemon_running
                    or now >= self.lms_ps_resume_at
                )
                if lms_cmd and can_use_lms_ps:
                    result = _run_safe_command([lms_cmd, "ps"])
                    if result.returncode == 0:
                        if _has_loaded_model(result.stdout):
                            current_status = "OK"
                            reason = "lms ps indicates model loaded"
                            self.title = "✅"
                        else:
                            current_status = "INFO"
                            reason = "lms ps indicates no model"
                            self.title = "ℹ️"
                    elif check_api_models():
                        current_status = "OK"
                        reason = "API reported models loaded"
                        self.title = "✅"
                    else:
                        current_status = "INFO"
                        reason = "API reported no models"
                        self.title = "ℹ️"
                elif any_running and check_api_models():
                    current_status = "OK"
                    reason = "API reported models loaded"
                    self.title = "✅"
                else:
                    current_status = "INFO"
                    reason = "running, no model via API"
                    self.title = "ℹ️"

            self._finish_status_check(current_status, reason)

        except subprocess.TimeoutExpired:
            logging.debug("Timeout in status check (keeping status)")
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            self.title = "❌"
            logging.error("Error in status check: %s", e)
            self.build_menu()
        return True

    # ------------------------------------------------------------------
    # Daemon control helpers
    # ------------------------------------------------------------------

    def _build_daemon_attempts(self, action: str) -> list[list[str]]:
        """Return ordered CLI command lists for daemon start or stop.

        Args:
            action (str): ``"start"`` or ``"stop"``.

        Returns:
            list[list[str]]: Ordered list of commands to try.
        """
        lms_cmd = get_lms_cmd()
        llmster_cmd = get_llmster_cmd()
        attempts = []
        if action == "start":
            # lms is deliberately absent here. When LM Studio embeds the
            # daemon -- the norm on macOS -- `lms daemon up` prints
            # "Waking up LM Studio service..." and launches the desktop app,
            # reporting {"isDaemon": false}. A menu entry promising a
            # headless daemon must never start a GUI, so only a standalone
            # llmster binary qualifies. lms still serves status and stop.
            if llmster_cmd:
                attempts.extend([
                    [llmster_cmd, "daemon", "up"],
                    [llmster_cmd, "daemon", "start"],
                    [llmster_cmd, "up"],
                    [llmster_cmd, "start"],
                ])
        elif action == "stop":
            if lms_cmd:
                attempts.extend([
                    [lms_cmd, "daemon", "down"],
                    [lms_cmd, "daemon", "stop"],
                    [lms_cmd, "down"],
                    [lms_cmd, "stop"],
                ])
            if llmster_cmd:
                attempts.extend([
                    [llmster_cmd, "daemon", "down"],
                    [llmster_cmd, "daemon", "stop"],
                    [llmster_cmd, "down"],
                    [llmster_cmd, "stop"],
                ])
        return attempts

    def _force_stop_llmster(self) -> None:
        """Force-kill llmster with SIGTERM then SIGKILL escalation."""
        pkill_cmd = get_pkill_cmd()
        if not pkill_cmd or not os.path.isabs(pkill_cmd):
            logging.warning("pkill not found; cannot force-stop llmster")
            return
        for flag in ("-x", "-f"):
            try:
                _run_safe_command([pkill_cmd, flag, "llmster"])
            except (OSError, subprocess.SubprocessError):
                pass
        for _ in range(12):
            if not is_llmster_running():
                return
            time.sleep(0.25)
        if is_llmster_running():
            logging.warning(
                "SIGTERM did not stop llmster; sending SIGKILL"
            )
            for flag in ("-x", "-f"):
                try:
                    _run_safe_command(
                        [pkill_cmd, "-9", flag, "llmster"]
                    )
                except (OSError, subprocess.SubprocessError):
                    pass
            for _ in range(8):
                if not is_llmster_running():
                    break
                time.sleep(0.25)

    def _stop_daemon_with_notification(
        self,
    ) -> tuple[bool, Optional[subprocess.CompletedProcess[str]]]:
        """Stop daemon and send a macOS notification on result.

        Returns:
            tuple[bool, object]: ``(stopped, last_result)``
        """
        stop_attempts = self._build_daemon_attempts("stop")
        if not stop_attempts:
            logging.error("llmster not found")
            self._notify(
                "Error",
                "llmster/lms not found. Nothing to stop.",
            )
            return (False, None)

        result = None
        for attempt in stop_attempts:
            try:
                result = _run_safe_command(attempt)
                if not is_llmster_running():
                    break
            except (OSError, subprocess.SubprocessError):
                pass

        self._force_stop_llmster()
        stopped = not is_llmster_running()

        if stopped:
            logging.info("llmster daemon stopped")
            self._notify(
                "LLMster",
                "Daemon stopped. You can now start the desktop app.",
            )
        else:
            err = "llmster process is still running"
            if result is not None:
                detail = (
                    result.stderr.strip() or result.stdout.strip()
                )
                if detail:
                    err = f"{err}: {detail}"
            logging.error("Failed to stop daemon: %s", err)
            self._notify("Error", "Daemon stop failed: " + str(err))

        return (stopped, result)

    def _stop_desktop_app_processes(self) -> bool:
        """Stop LM Studio desktop processes via SIGTERM then SIGKILL.

        Returns:
            bool: ``True`` when the desktop app is no longer running.
        """
        pids = get_desktop_app_pids()
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except (OSError, ProcessLookupError, PermissionError):
                pass
        for _ in range(8):
            if self.get_desktop_app_status() != "running":
                break
            time.sleep(0.25)
        if self.get_desktop_app_status() == "running":
            for pid in get_desktop_app_pids():
                try:
                    sigkill = getattr(signal, "SIGKILL", 9)
                    os.kill(pid, sigkill)
                except (OSError, ProcessLookupError, PermissionError):
                    pass
            for _ in range(8):
                if self.get_desktop_app_status() != "running":
                    break
                time.sleep(0.25)
        return self.get_desktop_app_status() != "running"

    # ------------------------------------------------------------------
    # Daemon start / stop
    # ------------------------------------------------------------------

    def start_daemon(self, _sender: object) -> None:
        """Start the llmster headless daemon (menu-bar callback).

        Args:
            _sender: rumps sender object (unused).
        """
        if not self.begin_action_cooldown("start_daemon"):
            return
        threading.Thread(
            target=self._start_daemon_body,
            daemon=True,
            name="macos-start-daemon",
        ).start()

    def _start_daemon_body(self) -> None:
        """Background thread body for :meth:`start_daemon`.

        Wrapped so an unexpected error still reaches the user: a bare
        exception in a worker thread would otherwise kill it silently,
        leaving the click with no feedback at all.
        """
        try:
            self._start_daemon_body_impl()
        except Exception:  # pylint: disable=broad-except
            logging.exception("Daemon start failed unexpectedly")
            self._notify("Error", "Daemon start failed. See the log.")

    def _start_daemon_body_impl(self) -> None:
        """Do the actual daemon start work."""
        if self.get_desktop_app_status() == "running":
            if not self._stop_desktop_app_processes():
                self._notify(
                    "Error",
                    "Failed to stop desktop app. Please stop it first.",
                )
                return
        start_attempts = self._build_daemon_attempts("start")
        if not start_attempts:
            self._notify(
                "Daemon",
                "llmster not installed. Install it with: "
                "curl -fsSL https://lmstudio.ai/install.sh | bash",
            )
            return
        for attempt in start_attempts:
            try:
                _run_safe_command(attempt)
                for _ in range(10):
                    if is_llmster_running():
                        break
                    time.sleep(0.5)
                if is_llmster_running():
                    # Logged like the stop path, so the action is visible
                    # even where notifications never reach the user.
                    logging.info("llmster daemon started")
                    self._notify("LLMster", "llmster daemon is running")
                    self.build_menu()
                    self._schedule_menu_refresh()
                    return
            except (OSError, subprocess.SubprocessError) as e:
                logging.error("Daemon start attempt failed: %s", e)
        logging.error("Daemon start failed")
        self._notify("Error", "Daemon start failed")
        self.build_menu()

    def stop_daemon(self, _sender: object) -> None:
        """Stop the llmster headless daemon (menu-bar callback).

        Args:
            _sender: rumps sender object (unused).
        """
        if not self.begin_action_cooldown("stop_daemon"):
            return
        threading.Thread(
            target=self._stop_daemon_body,
            daemon=True,
            name="macos-stop-daemon",
        ).start()

    def _stop_daemon_body(self) -> None:
        """Background thread body for :meth:`stop_daemon`."""
        try:
            self._stop_daemon_with_notification()
            self.build_menu()
            self._schedule_menu_refresh()
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            logging.error("Error stopping daemon: %s", e)
            self._notify("Error", str(e))
            self.build_menu()
        except Exception:  # pylint: disable=broad-except
            # Anything else would kill the worker thread without a trace.
            logging.exception("Daemon stop failed unexpectedly")
            self._notify("Error", "Daemon stop failed. See the log.")

    # ------------------------------------------------------------------
    # Desktop app start / stop
    # ------------------------------------------------------------------

    def start_desktop_app(self, _sender: object) -> None:
        """Start LM Studio desktop app (menu-bar callback).

        Args:
            _sender: rumps sender object (unused).
        """
        if not self.begin_action_cooldown("start_desktop_app"):
            return
        threading.Thread(
            target=self._start_desktop_app_body,
            daemon=True,
            name="macos-start-app",
        ).start()

    def _start_desktop_app_body(self) -> None:
        """Background thread body for :meth:`start_desktop_app` (macOS).

        Stops the daemon first, then launches LM Studio via the system
        ``open`` command.
        """
        if is_llmster_running():
            self._stop_daemon_with_notification()

        open_cmd = shutil.which("open")
        if not open_cmd:
            self._notify("Error", "'open' command not found")
            return

        for app_path in self._APP_LOCATIONS:
            if not os.path.isdir(app_path):
                continue
            try:
                subprocess.Popen(  # nosec B603
                    [open_cmd, app_path],
                    start_new_session=True,
                    close_fds=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.lms_ps_resume_at = time.monotonic() + 12.0
                logging.info("Started LM Studio: %s", app_path)
                self._notify(
                    "LM Studio", "LM Studio GUI is starting..."
                )
                self.build_menu()
                self._schedule_menu_refresh()
                return
            except (OSError, subprocess.SubprocessError) as e:
                logging.error("Failed to start desktop app: %s", e)
                self._notify(
                    "Error", "Failed to start app: " + str(e)
                )
                return

        self._notify(
            "Error",
            "No LM Studio.app found in /Applications or "
            "~/Applications.\nPlease install from "
            "https://lmstudio.ai/download",
        )
        self.build_menu()

    def stop_desktop_app(self, _sender: object) -> None:
        """Stop LM Studio desktop app (menu-bar callback).

        Args:
            _sender: rumps sender object (unused).
        """
        if not self.begin_action_cooldown("stop_desktop_app"):
            return
        desktop_pids = get_desktop_app_pids()
        if not desktop_pids:
            self.build_menu()
            return
        stopped = 0
        for pid in desktop_pids:
            try:
                os.kill(pid, signal.SIGTERM)
                stopped += 1
                logging.info(
                    "Sent SIGTERM to desktop app PID %s", pid
                )
            except (OSError, ProcessLookupError, PermissionError) as e:
                logging.warning("Error stopping PID %s: %s", pid, e)
        if stopped:
            self._notify("LM Studio", "Desktop app stopped")
        else:
            self._notify("Error", "Could not stop the desktop app")
        self.build_menu()
        self._schedule_menu_refresh()

    # ------------------------------------------------------------------
    # Dialogs
    # ------------------------------------------------------------------

    def _collect_status_text(self) -> str:
        """Return status text without starting anything.

        ``lms ps`` is not a read-only command: with no service running it
        prints "Waking up LM Studio service..." and boots LM Studio. It is
        therefore only invoked when something is already running locally.

        Returns:
            str: Human-readable status description.
        """
        endpoint = f"{_AppState.API_HOST}:{_AppState.API_PORT}"

        if is_remote_endpoint():
            reachable, has_model = check_api_reachable()
            if not reachable:
                return f"Remote endpoint {endpoint} is not reachable."
            if not has_model:
                return f"Connected to {endpoint}.\nNo model is loaded."
            names = get_api_loaded_models()
            if not names:
                return f"Connected to {endpoint}.\nA model is loaded."
            listed = "\n".join(f"  • {name}" for name in names)
            label = "Loaded model" if len(names) == 1 else "Loaded models"
            return f"Connected to {endpoint}.\n\n{label}:\n{listed}"

        daemon_running = self.get_daemon_status() == "running"
        app_running = self.get_desktop_app_status() == "running"
        if not (daemon_running or app_running):
            return (
                "Neither the daemon nor the desktop app is running.\n"
                "Start one of them to query the model status."
            )

        lms_cmd = get_lms_cmd()
        if not lms_cmd:
            return "LM Studio CLI (lms) not found."

        try:
            result = _run_safe_command([lms_cmd, "ps"])
        except (OSError, subprocess.SubprocessError) as exc:
            return f"Error running lms ps: {exc}"

        if result.returncode == 0 and result.stdout.strip():
            return _format_lms_ps_output(result.stdout.strip())
        return "No model loaded (lms ps returned no output)."

    def show_status_dialog(self, sender: object) -> None:
        """Show a rumps alert with the current LM Studio CLI status.

        Args:
            sender: rumps sender object (unused).
        """
        _ = sender
        text = self._collect_status_text()

        rumps_lib = _rumps_lib
        if rumps_lib is None:
            logging.error("rumps is not installed; cannot show status dialog")
            return
        rumps_lib.alert(title="LM Studio Status", message=text)

    def show_config_dialog(self, sender: object) -> None:
        """Prompt for the LM Studio API endpoint and persist it.

        The GTK backend offers separate host and port fields; rumps windows
        only carry a single text field, so the endpoint is entered as
        ``host:port``.

        Args:
            sender: rumps sender object (unused).
        """
        _ = sender
        rumps_lib = _rumps_lib
        if rumps_lib is None:
            logging.error("rumps is not installed; cannot show config dialog")
            return

        current = f"{_AppState.API_HOST}:{_AppState.API_PORT}"
        window = rumps_lib.Window(
            title="Configuration",
            message=(
                "LM Studio API endpoint to monitor.\n"
                "Enter as host:port (for example localhost:1234)."
            ),
            default_text=current,
            ok="Save",
            cancel="Cancel",
            dimensions=(260, 24),
        )

        response = window.run()
        if not response.clicked:
            return

        parsed = parse_host_port(response.text)
        if parsed is None:
            logging.warning(
                "Rejected invalid API endpoint input: %r", response.text
            )
            rumps_lib.alert(
                title="Configuration",
                message=(
                    "Could not read that endpoint.\n"
                    "Expected host:port, for example localhost:1234."
                ),
            )
            return

        host, port = parsed
        try:
            save_config(host, port)
        except (OSError, ValueError) as exc:
            logging.error("Failed to save configuration: %s", exc)
            rumps_lib.alert(
                title="Configuration",
                message=f"Could not save the configuration:\n{exc}",
            )
            return

        _AppState.API_HOST = host
        _AppState.API_PORT = port
        logging.info("Updated API endpoint to http://%s:%s", host, port)
        self._notify("Configuration", f"API endpoint set to {host}:{port}")
        self.build_menu()

    def show_about_dialog(self, sender: object) -> None:
        """Show basic application information in a rumps alert.

        Args:
            sender: rumps sender object (unused).
        """
        _ = sender
        # APP_VERSION already carries its own "v" prefix when it comes from
        # the VERSION file, and is the bare word "dev" otherwise - so no
        # prefix is added here.
        msg = (
            f"LM Studio Tray Manager "
            f"{_AppState.APP_VERSION}\n"
            f"Maintainer: {APP_MAINTAINER}\n"
            f"{APP_REPOSITORY}\n"
            f"\n"
            f"This program comes WITHOUT ANY WARRANTY."
        )

        rumps_lib = _rumps_lib
        if rumps_lib is None:
            logging.error("rumps is not installed; cannot show about dialog")
            return
        rumps_lib.alert(title=APP_NAME, message=msg)

    # ------------------------------------------------------------------
    # Update check
    # ------------------------------------------------------------------

    def check_updates(self) -> bool:
        """Check GitHub for a newer release and notify if found.

        Returns:
            bool: ``True`` when an update notification was sent.
        """
        if _AppState.APP_VERSION == DEFAULT_APP_VERSION:
            self._update_info["status"] = "Dev build"
            self.update_status = "Dev build"
            logging.debug("Update check skipped: dev build")
            return False

        latest, error = get_latest_release_version()
        self._update_info["last_error"] = error
        self.last_update_error = error
        if not latest:
            self._update_info["status"] = "Unknown"
            self.update_status = "Unknown"
            logging.debug("Update check failed: %s", error)
            return False

        self._update_info["latest_version"] = latest
        self.latest_update_version = latest
        self._update_info["last_error"] = None
        self.last_update_error = None

        newer = is_newer_version(_AppState.APP_VERSION, latest)
        current_parts = parse_version(_AppState.APP_VERSION)
        latest_parts = parse_version(latest)
        is_ahead = (
            current_parts > latest_parts
            if current_parts and latest_parts
            else False
        )

        if newer:
            self._update_info["status"] = "Update available"
            self.update_status = "Update available"
        elif is_ahead:
            self._update_info["status"] = "Ahead of release"
            self.update_status = "Ahead of release"
        else:
            self._update_info["status"] = "Up to date"
            self.update_status = "Up to date"

        logging.debug(
            "Update check: %s (latest %s)",
            self._update_info["status"],
            latest,
        )

        if not newer:
            return False
        if self._update_info["last_version"] == latest:
            return False

        self._update_info["last_version"] = latest
        self.last_update_version = latest
        url = get_release_url(latest)
        self._notify(
            "Update Available",
            f"New version available: {latest} "
            f"(current {_AppState.APP_VERSION})\n{url}",
        )
        return True

    def manual_check_updates(self, _sender: object) -> None:
        """Run an on-demand update check and show result via alert.

        Args:
            _sender: rumps sender object (unused).
        """
        _ = _sender
        notified = self.check_updates()
        if notified:
            return
        status = self.update_status or "Unknown"
        latest = self.latest_update_version
        error = self.last_update_error
        if status == "Update available" and latest:
            url = get_release_url(latest)
            msg = (
                f"New version available: {latest} "
                f"(current {_AppState.APP_VERSION})\n{url}"
            )
        elif status == "Up to date":
            msg = f"You are up to date ({_AppState.APP_VERSION})"
        elif status == "Dev build":
            msg = "Dev build: update checks disabled"
        elif status == "Ahead of release":
            msg = (
                f"Ahead of release "
                f"(current {_AppState.APP_VERSION}, latest {latest})"
            )
        else:
            detail = f" ({error})" if error else ""
            msg = "Unable to check for updates." + detail

        rumps_lib = _rumps_lib
        if rumps_lib is None:
            logging.error("rumps is not installed; cannot show update dialog")
            return
        rumps_lib.alert(title="Update Check", message=msg)

    # ------------------------------------------------------------------
    # Auto-start helpers
    # ------------------------------------------------------------------

    def _maybe_auto_start_daemon(self) -> None:
        """Start daemon at launch when --auto-start-daemon is set."""
        logging.info(
            "Auto-starting daemon (--auto-start-daemon) "
            "with fresh passkey"
        )
        try:
            self._stop_daemon_with_notification()
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            logging.error("Error stopping llmster: %s", e)
        self.action_lock_until = 0.0
        self.start_daemon(None)

    def _maybe_start_gui(self) -> None:
        """Start the desktop app at launch when --gui is set."""
        logging.info("Auto-starting GUI (--gui)")
        self.start_desktop_app(None)

    # ------------------------------------------------------------------
    # Quit
    # ------------------------------------------------------------------

    def quit_app(self, _sender: object) -> None:
        """Quit the tray application (menu-bar callback).

        Args:
            _sender: rumps sender object (unused).
        """
        _ = _sender
        logging.info("Tray icon terminated")
        rumps_lib = _rumps_lib
        if rumps_lib is None:
            logging.error("rumps is not installed; cannot quit application")
            return
        rumps_lib.quit_application()


class WindowsTrayIcon:
    """Windows notification-area tray using the ``pystray`` library.

    Provides the same monitoring and daemon/desktop-app control as
    :class:`TrayIcon` and :class:`MacOSTrayIcon`. Two things differ from the
    macOS backend and shape the code below:

    * The notification area shows an icon, never text, so the status emoji
      goes into the tooltip rather than a menu-bar title.
    * ``pystray`` has no timer facility and no dialogs, so periodic checks
      run on background threads and dialogs are drawn with tkinter.

    Unlike AppKit there is no main-thread restriction: ``update_menu`` and
    the tooltip may be set from any thread, so menu rebuilds happen in
    place rather than being marshalled.
    """

    _APP_LOCATIONS = [
        os.path.join(
            os.environ.get(
                "LOCALAPPDATA",
                os.path.expanduser("~/AppData/Local"),
            ),
            "Programs", "LM Studio", "LM Studio.exe",
        ),
        os.path.join(
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            "LM Studio", "LM Studio.exe",
        ),
    ]

    def __init__(self) -> None:
        """Initialize the tray icon and start the monitoring threads."""
        if _pystray_lib is None:
            raise RuntimeError(
                "pystray is not installed; cannot create WindowsTrayIcon"
            )

        self.last_status = None
        self.action_lock_until = 0.0
        self.lms_ps_resume_at = 0.0
        self.remote_loaded_models: list[str] = []
        self._desktop_detection = {
            "seen_call": False,
            "last_detection": None,
        }
        self.last_update_version = None
        self.update_status = "Unknown"
        self.latest_update_version = None
        self.last_update_error = None
        self._update_info = {
            "status": "Unknown",
            "last_error": None,
            "latest_version": None,
            "last_version": None,
        }
        self._status_emoji = "⚠️"
        self._stop_event = threading.Event()

        self.icon = _pystray_lib.Icon(
            APP_NAME,
            icon=self._load_icon_image(),
            title=self._tooltip_text(),
        )
        self.build_menu()

    # ------------------------------------------------------------------
    # Icon and tooltip
    # ------------------------------------------------------------------

    @staticmethod
    def _load_icon_image():
        """Return the tray image, or a plain fallback when it is missing.

        A tray icon with no image is invisible in the notification area, so
        a missing asset falls back to a solid square rather than leaving
        the user with nothing to click.

        Returns:
            The PIL image to display.
        """
        if _pil_image is None:
            raise RuntimeError("Pillow is not installed; cannot build icon")

        icon_path = get_asset_path("img", "lm-studio-tray-manager.png")
        if icon_path:
            try:
                return _pil_image.open(icon_path)
            except (OSError, ValueError) as exc:
                logging.warning(
                    "Could not load tray icon %s: %s", icon_path, exc
                )
        else:
            logging.warning("Tray icon asset not found; using a fallback")

        return _pil_image.new("RGBA", (64, 64), (60, 100, 200, 255))

    def _tooltip_text(self) -> str:
        """Return the hover text for the notification-area icon.

        Returns:
            str: Status emoji followed by the application name.
        """
        return f"{self._status_emoji} {APP_NAME}"

    @property
    def title(self) -> str:
        """Status emoji shown in the tooltip.

        Named ``title`` so the status logic reads the same across all three
        backends, where macOS puts this text in the menu bar itself.

        Returns:
            str: The current status emoji.
        """
        return self._status_emoji

    @title.setter
    def title(self, value: str) -> None:
        """Update the status emoji and push it to the tooltip.

        Args:
            value: New status emoji.
        """
        self._status_emoji = value
        icon = getattr(self, "icon", None)
        if icon is None:
            return
        try:
            icon.title = self._tooltip_text()
        except (AttributeError, OSError, RuntimeError) as exc:
            logging.debug("Could not update the tray tooltip: %s", exc)

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def get_daemon_status(self) -> str:
        """Check if the llmster headless daemon is running.

        Returns:
            str: ``"running"``, ``"stopped"``, or ``"not_found"``.
        """
        try:
            if not is_daemon_available():
                return "not_found"
            if is_llmster_running():
                return "running"
            return "stopped"
        except (
            OSError,
            subprocess.SubprocessError,
            subprocess.TimeoutExpired,
        ):
            return "not_found"

    def get_desktop_app_status(self) -> str:
        """Check if the LM Studio desktop app is running or installed.

        Returns:
            str: ``"running"``, ``"stopped"``, or ``"not_found"``.
        """
        try:
            if get_desktop_app_pids():
                return "running"
        except (OSError, subprocess.SubprocessError):
            pass

        for exe_path in self._APP_LOCATIONS:
            if os.path.isfile(exe_path):
                self._log_desktop_detection(f"app:{exe_path}")
                return "stopped"

        self._log_desktop_detection("none")
        return "not_found"

    def _log_desktop_detection(self, detection: str) -> None:
        """Log where the desktop app was found, but only when it changes.

        The status check runs every few seconds; logging the same result
        each time would bury everything else in the log.

        Args:
            detection: Token describing the current detection result.
        """
        state = self._desktop_detection
        if state["seen_call"] and detection == state["last_detection"]:
            return

        if detection == "none":
            logging.debug("No LM Studio desktop app found")
        else:
            logging.debug(
                "Detected LM Studio at %s", detection.split(":", 1)[1]
            )
        state["last_detection"] = detection
        state["seen_call"] = True

    def get_status_indicator(self, status: str) -> str:
        """Return an emoji indicator for a status string.

        Args:
            status (str): One of ``"running"``, ``"stopped"``,
                ``"not_found"``.

        Returns:
            str: Emoji representing the status.
        """
        if status == "running":
            return "🟢"
        if status == "stopped":
            return "🟡"
        return "🔴"

    # ------------------------------------------------------------------
    # Notification
    # ------------------------------------------------------------------

    def _notify(self, title: str, message: str) -> None:
        """Show a notification balloon.

        Args:
            title: Notification title.
            message: Notification body.
        """
        try:
            self.icon.notify(message, title)
        except (AttributeError, NotImplementedError, OSError,
                RuntimeError) as exc:
            # A tray notification is a courtesy, never a requirement; the
            # log entry beside each call carries the same information.
            logging.debug("Notification failed: %s", exc)

    # ------------------------------------------------------------------
    # Menu building
    # ------------------------------------------------------------------

    def build_menu(self) -> None:
        """Rebuild the tray menu with the current status."""
        self._build_menu_impl()

    def _build_options_menu(self, pystray_lib):
        """Return the shared Options submenu.

        Args:
            pystray_lib: The pystray module.

        Returns:
            The populated Options menu item.
        """
        return pystray_lib.MenuItem(
            "Options",
            pystray_lib.Menu(
                pystray_lib.MenuItem(
                    "Configuration", self.show_config_dialog
                ),
                # Unlike macOS, Windows offers no built-in per-app login
                # item, so the setting belongs here. checked is a callable
                # so the box reflects the Startup folder itself: whether it
                # was the installer, the PowerShell script or this menu that
                # registered the tray, the state shown stays truthful.
                pystray_lib.MenuItem(
                    "Start with Windows",
                    self.toggle_autostart,
                    checked=lambda _item: is_autostart_enabled(),
                ),
                pystray_lib.MenuItem(
                    "Check for Updates", self.manual_check_updates
                ),
                pystray_lib.MenuItem("About", self.show_about_dialog),
            ),
        )

    def toggle_autostart(self, _icon=None, _item=None) -> None:
        """Turn "start with Windows" on or off.

        Args:
            _icon: pystray icon (unused).
            _item: pystray menu item (unused).
        """
        if is_autostart_enabled():
            if disable_autostart():
                self._notify(
                    "Autostart", "The tray no longer starts with Windows."
                )
            else:
                _show_tk_message(
                    "Autostart",
                    "Could not remove the autostart entry.\n"
                    "See the log for details.",
                )
        elif enable_autostart():
            self._notify("Autostart", "The tray now starts with Windows.")
        else:
            _show_tk_message(
                "Autostart",
                "Could not register the tray to start with Windows.\n"
                "See the log for details.",
            )

        # The checkbox is only re-evaluated when pystray rebuilds the menu.
        self.build_menu()

    def _build_remote_menu_items(self, pystray_lib) -> list:
        """Return menu entries for a remote endpoint.

        Start/stop actions operate on local processes, so they are omitted
        here rather than offered as controls that cannot work.

        Args:
            pystray_lib: The pystray module.

        Returns:
            list: Menu items describing the remote endpoint.
        """
        endpoint = f"{_AppState.API_HOST}:{_AppState.API_PORT}"
        names = getattr(self, "remote_loaded_models", []) or []

        if self.last_status == "OK":
            indicator = "🟢"
            if len(names) == 1:
                state = f"{_shorten_model_name(names[0])} loaded"
            elif len(names) > 1:
                state = f"{len(names)} models loaded"
            else:
                state = "Model loaded"
        elif self.last_status == "INFO":
            indicator, state = "🟡", "No model loaded"
        else:
            indicator, state = "🔴", "Unreachable"

        items = [
            self._label_item(pystray_lib, f"{indicator} Remote: {endpoint}"),
            self._label_item(pystray_lib, f"  → {state}"),
        ]
        if len(names) > 1:
            items.extend(
                self._label_item(
                    pystray_lib, f"     • {_shorten_model_name(name)}"
                )
                for name in names
            )
        return items

    @staticmethod
    def _label_item(pystray_lib, text):
        """Return a non-clickable informational menu entry.

        Args:
            pystray_lib: The pystray module.
            text: Label to display.

        Returns:
            A disabled menu item.
        """
        return pystray_lib.MenuItem(text, None, enabled=False)

    def _build_menu_impl(self) -> None:
        """Assemble the menu and hand it to pystray."""
        pystray_lib = _pystray_lib
        if pystray_lib is None:
            raise RuntimeError("pystray is not installed")

        if is_remote_endpoint():
            items = self._build_remote_menu_items(pystray_lib)
        else:
            items = self._build_local_menu_items(pystray_lib)

        items.append(pystray_lib.Menu.SEPARATOR)
        items.append(
            pystray_lib.MenuItem("Show Status", self.show_status_dialog)
        )
        items.append(self._build_options_menu(pystray_lib))
        items.append(pystray_lib.Menu.SEPARATOR)
        items.append(pystray_lib.MenuItem("Quit Tray", self.quit_app))

        self.icon.menu = pystray_lib.Menu(*items)
        try:
            self.icon.update_menu()
        except (AttributeError, RuntimeError) as exc:
            # Before icon.run() there is no live menu to refresh yet.
            logging.debug("Menu update skipped: %s", exc)

    def _build_local_menu_items(self, pystray_lib) -> list:
        """Return the daemon and desktop-app entries for a local endpoint.

        Args:
            pystray_lib: The pystray module.

        Returns:
            list: Menu items reflecting the current local status.
        """
        daemon_status = self.get_daemon_status()
        app_status = self.get_desktop_app_status()
        d_ind = self.get_status_indicator(daemon_status)
        a_ind = self.get_status_indicator(app_status)

        items = []

        if daemon_status == "running":
            items.append(
                self._label_item(pystray_lib, f"{d_ind} Daemon (Running)")
            )
            items.append(
                pystray_lib.MenuItem("  → Stop Daemon", self.stop_daemon)
            )
        elif daemon_status == "stopped":
            items.append(
                pystray_lib.MenuItem(
                    f"{d_ind} Start Daemon (Headless)", self.start_daemon
                )
            )
        else:
            items.append(
                self._label_item(
                    pystray_lib, f"{d_ind} Daemon (Not Installed)"
                )
            )

        if app_status == "running":
            items.append(
                self._label_item(
                    pystray_lib, f"{a_ind} Desktop App (Running)"
                )
            )
            items.append(
                pystray_lib.MenuItem(
                    "  → Stop Desktop App", self.stop_desktop_app
                )
            )
        elif app_status == "stopped":
            items.append(
                pystray_lib.MenuItem(
                    f"{a_ind} Start Desktop App", self.start_desktop_app
                )
            )
        else:
            items.append(
                self._label_item(
                    pystray_lib, f"{a_ind} Desktop App (Not Installed)"
                )
            )

        return items

    # ------------------------------------------------------------------
    # Monitoring threads
    # ------------------------------------------------------------------

    def _status_loop(self) -> None:
        """Re-check status every ``INTERVAL`` seconds until quit."""
        while not self._stop_event.wait(INTERVAL):
            try:
                self.check_model()
            except Exception:  # pylint: disable=broad-except
                # An unhandled error here would silently end the thread and
                # freeze the tray on its last status.
                logging.exception("Status check failed")

    def _update_loop(self) -> None:
        """Check for updates shortly after start, then daily until quit."""
        if self._stop_event.wait(5):
            return
        while True:
            try:
                self.check_updates()
            except Exception:  # pylint: disable=broad-except
                logging.exception("Update check failed")
            if self._stop_event.wait(UPDATE_CHECK_INTERVAL):
                return

    def _start_background_threads(self) -> None:
        """Start the monitoring threads and any auto-start actions."""
        threading.Thread(
            target=self._status_loop, daemon=True, name="windows-status"
        ).start()
        threading.Thread(
            target=self._update_loop, daemon=True, name="windows-updates"
        ).start()

        if _AppState.AUTO_START_DAEMON:
            threading.Thread(
                target=self._maybe_auto_start_daemon,
                daemon=True,
                name="windows-auto-start",
            ).start()
        if _AppState.GUI_MODE:
            threading.Thread(
                target=self._maybe_start_gui,
                daemon=True,
                name="windows-auto-gui",
            ).start()

    def run(self) -> None:
        """Show the tray icon and block until the user quits."""
        self.icon.run(setup=lambda _icon: self._on_icon_ready())

    def _on_icon_ready(self) -> None:
        """Run once the icon is visible: first status check, then timers.

        pystray calls this on its own thread after the notification-area
        icon exists, which is the first moment a menu refresh can take
        effect.
        """
        try:
            self.icon.visible = True
        except (AttributeError, OSError, RuntimeError) as exc:
            logging.debug("Could not set icon visibility: %s", exc)

        try:
            self.check_model()
        except Exception:  # pylint: disable=broad-except
            logging.exception("Initial status check failed")

        self._start_background_threads()

    def _schedule_menu_refresh(self, delay_seconds: float = 2) -> None:
        """Schedule a delayed menu rebuild.

        Start and stop commands return before the process has finished
        appearing or disappearing, so the menu is rebuilt once more a
        moment later.

        Args:
            delay_seconds: Seconds to wait before rebuilding.
        """
        timer = threading.Timer(delay_seconds, self.build_menu)
        timer.daemon = True
        timer.start()

    # ------------------------------------------------------------------
    # Action cooldown
    # ------------------------------------------------------------------

    def begin_action_cooldown(
        self, action_name: str, seconds: float = 2.0
    ) -> bool:
        """Prevent rapid double-triggering of tray actions.

        Args:
            action_name (str): Name used for logging.
            seconds (float): Cooldown duration in seconds.

        Returns:
            bool: ``True`` when the action may proceed.
        """
        now = time.monotonic()
        if now < self.action_lock_until:
            remaining = self.action_lock_until - now
            logging.info(
                "Action blocked by cooldown: %s (%.1fs remaining)",
                action_name,
                remaining,
            )
            return False
        self.action_lock_until = now + seconds
        return True

    # ------------------------------------------------------------------
    # Status / model check
    # ------------------------------------------------------------------

    def _check_remote_status(self) -> tuple[str, str]:
        """Determine status for a remote endpoint via the HTTP API.

        Returns:
            tuple[str, str]: ``(status, reason)`` where status is one of
            ``"OK"``, ``"INFO"`` or ``"WARN"``.
        """
        reachable, names = query_api_models()
        self.remote_loaded_models = names
        if not reachable:
            self.title = "⚠️"
            return ("WARN", "remote endpoint unreachable")
        if names:
            self.title = "✅"
            return ("OK", "remote API reported models loaded")
        self.title = "ℹ️"
        return ("INFO", "remote API reachable, no model loaded")

    def _finish_status_check(
        self, current_status: Optional[str], reason: str
    ) -> None:
        """Emit transition notifications and refresh the menu.

        Args:
            current_status: Newly determined status, or ``None``.
            reason: Human-readable explanation used for logging.
        """
        if (
            self.last_status != current_status
            and self.last_status is not None
        ):
            logging.debug(
                "Status change: %s -> %s (%s)",
                self.last_status,
                current_status,
                reason,
            )
            remote = is_remote_endpoint()
            if current_status == "OK":
                self._notify("LM Studio", "✅ A model is loaded")
            elif current_status == "INFO":
                self._notify(
                    "LM Studio",
                    "ℹ️ Runtime active, no model loaded",
                )
            elif current_status == "WARN":
                self._notify(
                    "LM Studio",
                    "⚠️ Remote endpoint is unreachable"
                    if remote
                    else "⚠️ Neither daemon nor desktop app is running",
                )
            elif current_status == "FAIL":
                self._notify(
                    "LM Studio",
                    "❌ Daemon and desktop app are not installed",
                )
            logging.info(
                "Status change: %s -> %s",
                self.last_status,
                current_status,
            )

        self.last_status = current_status
        self.build_menu()

    def check_model(self) -> bool:
        """Check LM Studio status and update the tooltip indicator.

        Returns:
            bool: Always ``True`` (keeps the monitoring loop going).
        """
        try:
            lms_cmd = get_lms_cmd()

            if is_remote_endpoint():
                current_status, reason = self._check_remote_status()
                self._finish_status_check(current_status, reason)
                return True

            daemon_status = self.get_daemon_status()
            app_status = self.get_desktop_app_status()

            daemon_running = daemon_status == "running"
            app_running = app_status == "running"
            any_running = daemon_running or app_running
            both_missing = (
                daemon_status == "not_found"
                and app_status == "not_found"
            )

            if both_missing:
                current_status = "FAIL"
                reason = "daemon and desktop app not installed"
                self.title = "❌"
            elif not any_running:
                current_status = "WARN"
                reason = "daemon and desktop app stopped"
                self.title = "⚠️"
            else:
                current_status, reason = self._check_loaded_model(
                    lms_cmd, daemon_running, any_running
                )

            self._finish_status_check(current_status, reason)

        except subprocess.TimeoutExpired:
            logging.debug("Timeout in status check (keeping status)")
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            self.title = "❌"
            logging.error("Error in status check: %s", e)
            self.build_menu()
        return True

    def _check_loaded_model(
        self, lms_cmd: Optional[str], daemon_running: bool,
        any_running: bool,
    ) -> tuple[str, str]:
        """Determine whether a model is loaded on a running runtime.

        Args:
            lms_cmd: Resolved ``lms`` path, or ``None``.
            daemon_running: Whether the headless daemon is up.
            any_running: Whether daemon or desktop app is up.

        Returns:
            tuple[str, str]: ``(status, reason)``.
        """
        now = time.monotonic()
        can_use_lms_ps = daemon_running or now >= self.lms_ps_resume_at

        if lms_cmd and can_use_lms_ps:
            result = _run_safe_command([lms_cmd, "ps"])
            if result.returncode == 0:
                if _has_loaded_model(result.stdout):
                    self.title = "✅"
                    return ("OK", "lms ps indicates model loaded")
                self.title = "ℹ️"
                return ("INFO", "lms ps indicates no model")
            if check_api_models():
                self.title = "✅"
                return ("OK", "API reported models loaded")
            self.title = "ℹ️"
            return ("INFO", "API reported no models")

        if any_running and check_api_models():
            self.title = "✅"
            return ("OK", "API reported models loaded")

        self.title = "ℹ️"
        return ("INFO", "running, no model via API")

    # ------------------------------------------------------------------
    # Daemon control helpers
    # ------------------------------------------------------------------

    def _build_daemon_attempts(self, action: str) -> list[list[str]]:
        """Return ordered CLI command lists for daemon start or stop.

        Args:
            action (str): ``"start"`` or ``"stop"``.

        Returns:
            list[list[str]]: Ordered list of commands to try.
        """
        lms_cmd = get_lms_cmd()
        llmster_cmd = get_llmster_cmd()
        attempts = []
        if action == "start":
            # lms is deliberately absent here: where LM Studio embeds the
            # daemon, `lms daemon up` launches the desktop app rather than
            # a headless daemon, so a menu entry promising a daemon would
            # start a GUI instead. lms still serves status and stop.
            if llmster_cmd:
                attempts.extend([
                    [llmster_cmd, "daemon", "up"],
                    [llmster_cmd, "daemon", "start"],
                    [llmster_cmd, "up"],
                    [llmster_cmd, "start"],
                ])
        elif action == "stop":
            if lms_cmd:
                attempts.extend([
                    [lms_cmd, "daemon", "down"],
                    [lms_cmd, "daemon", "stop"],
                    [lms_cmd, "down"],
                    [lms_cmd, "stop"],
                ])
            if llmster_cmd:
                attempts.extend([
                    [llmster_cmd, "daemon", "down"],
                    [llmster_cmd, "daemon", "stop"],
                    [llmster_cmd, "down"],
                    [llmster_cmd, "stop"],
                ])
        return attempts

    def _force_stop_llmster(self) -> None:
        """Force-stop llmster, escalating to a forced kill if needed.

        ``taskkill /T`` ends the process tree the way ``pkill`` does on
        POSIX; ``/F`` is the equivalent of the SIGKILL escalation.
        """
        if not _run_taskkill(["/IM", LLMSTER_IMAGE_NAME, "/T"]):
            return

        for _ in range(12):
            if not is_llmster_running():
                return
            time.sleep(0.25)

        logging.warning(
            "llmster did not stop gracefully; forcing termination"
        )
        _run_taskkill(["/IM", LLMSTER_IMAGE_NAME, "/T", "/F"])
        for _ in range(8):
            if not is_llmster_running():
                return
            time.sleep(0.25)

    def _stop_daemon_with_notification(
        self,
    ) -> tuple[bool, Optional[subprocess.CompletedProcess[str]]]:
        """Stop the daemon and notify about the outcome.

        Returns:
            tuple[bool, object]: ``(stopped, last_result)``
        """
        stop_attempts = self._build_daemon_attempts("stop")
        if not stop_attempts:
            logging.error("llmster not found")
            self._notify(
                "Error", "llmster/lms not found. Nothing to stop."
            )
            return (False, None)

        result = None
        for attempt in stop_attempts:
            try:
                result = _run_safe_command(attempt)
                if not is_llmster_running():
                    break
            except (OSError, subprocess.SubprocessError):
                pass

        self._force_stop_llmster()
        stopped = not is_llmster_running()

        if stopped:
            logging.info("llmster daemon stopped")
            self._notify(
                "LLMster",
                "Daemon stopped. You can now start the desktop app.",
            )
        else:
            err = "llmster process is still running"
            if result is not None:
                detail = result.stderr.strip() or result.stdout.strip()
                if detail:
                    err = f"{err}: {detail}"
            logging.error("Failed to stop daemon: %s", err)
            self._notify("Error", "Daemon stop failed: " + str(err))

        return (stopped, result)

    def _stop_desktop_app_processes(self) -> bool:
        """Stop the LM Studio desktop app, escalating to a forced kill.

        Returns:
            bool: ``True`` when the desktop app is no longer running.
        """
        if not _run_taskkill(["/IM", LM_STUDIO_IMAGE_NAME, "/T"]):
            return self.get_desktop_app_status() != "running"

        for _ in range(8):
            if self.get_desktop_app_status() != "running":
                return True
            time.sleep(0.25)

        _run_taskkill(["/IM", LM_STUDIO_IMAGE_NAME, "/T", "/F"])
        for _ in range(8):
            if self.get_desktop_app_status() != "running":
                break
            time.sleep(0.25)

        return self.get_desktop_app_status() != "running"

    # ------------------------------------------------------------------
    # Daemon start / stop
    # ------------------------------------------------------------------

    def start_daemon(self, _icon=None, _item=None) -> None:
        """Start the llmster headless daemon (menu callback).

        Args:
            _icon: pystray icon (unused).
            _item: pystray menu item (unused).
        """
        if not self.begin_action_cooldown("start_daemon"):
            return
        threading.Thread(
            target=self._start_daemon_body,
            daemon=True,
            name="windows-start-daemon",
        ).start()

    def _start_daemon_body(self) -> None:
        """Background thread body for :meth:`start_daemon`.

        Wrapped so an unexpected error still reaches the user: a bare
        exception in a worker thread would otherwise kill it silently,
        leaving the click with no feedback at all.
        """
        try:
            self._start_daemon_body_impl()
        except Exception:  # pylint: disable=broad-except
            logging.exception("Daemon start failed unexpectedly")
            self._notify("Error", "Daemon start failed. See the log.")

    def _start_daemon_body_impl(self) -> None:
        """Do the actual daemon start work."""
        if self.get_desktop_app_status() == "running":
            if not self._stop_desktop_app_processes():
                self._notify(
                    "Error",
                    "Failed to stop desktop app. Please stop it first.",
                )
                return

        start_attempts = self._build_daemon_attempts("start")
        if not start_attempts:
            self._notify(
                "Daemon",
                "llmster not installed. Install LM Studio from "
                "https://lmstudio.ai/download",
            )
            return

        for attempt in start_attempts:
            try:
                _run_safe_command(attempt)
                for _ in range(10):
                    if is_llmster_running():
                        break
                    time.sleep(0.5)
                if is_llmster_running():
                    logging.info("llmster daemon started")
                    self._notify("LLMster", "llmster daemon is running")
                    self.build_menu()
                    self._schedule_menu_refresh()
                    return
            except (OSError, subprocess.SubprocessError) as e:
                logging.error("Daemon start attempt failed: %s", e)

        logging.error("Daemon start failed")
        self._notify("Error", "Daemon start failed")
        self.build_menu()

    def stop_daemon(self, _icon=None, _item=None) -> None:
        """Stop the llmster headless daemon (menu callback).

        Args:
            _icon: pystray icon (unused).
            _item: pystray menu item (unused).
        """
        if not self.begin_action_cooldown("stop_daemon"):
            return
        threading.Thread(
            target=self._stop_daemon_body,
            daemon=True,
            name="windows-stop-daemon",
        ).start()

    def _stop_daemon_body(self) -> None:
        """Background thread body for :meth:`stop_daemon`."""
        try:
            self._stop_daemon_with_notification()
            self.build_menu()
            self._schedule_menu_refresh()
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            logging.error("Error stopping daemon: %s", e)
            self._notify("Error", str(e))
            self.build_menu()
        except Exception:  # pylint: disable=broad-except
            logging.exception("Daemon stop failed unexpectedly")
            self._notify("Error", "Daemon stop failed. See the log.")

    # ------------------------------------------------------------------
    # Desktop app start / stop
    # ------------------------------------------------------------------

    def start_desktop_app(self, _icon=None, _item=None) -> None:
        """Start the LM Studio desktop app (menu callback).

        Args:
            _icon: pystray icon (unused).
            _item: pystray menu item (unused).
        """
        if not self.begin_action_cooldown("start_desktop_app"):
            return
        threading.Thread(
            target=self._start_desktop_app_body,
            daemon=True,
            name="windows-start-app",
        ).start()

    def _start_desktop_app_body(self) -> None:
        """Background thread body for :meth:`start_desktop_app`.

        Stops the daemon first - the two compete for the same port - then
        launches the installed executable directly.
        """
        if is_llmster_running():
            self._stop_daemon_with_notification()

        for exe_path in self._APP_LOCATIONS:
            if not os.path.isfile(exe_path):
                continue
            try:
                subprocess.Popen(  # nosec B603
                    [exe_path],
                    close_fds=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(
                        subprocess, "DETACHED_PROCESS", 0
                    ),
                )
                # The desktop app boots its own runtime; querying `lms ps`
                # during that window would wake a second service.
                self.lms_ps_resume_at = time.monotonic() + 12.0
                logging.info("Started LM Studio: %s", exe_path)
                self._notify("LM Studio", "LM Studio is starting...")
                self.build_menu()
                self._schedule_menu_refresh()
                return
            except (OSError, subprocess.SubprocessError) as e:
                logging.error("Failed to start desktop app: %s", e)
                self._notify("Error", "Failed to start app: " + str(e))
                return

        self._notify(
            "Error",
            "LM Studio was not found.\n"
            "Please install it from https://lmstudio.ai/download",
        )
        self.build_menu()

    def stop_desktop_app(self, _icon=None, _item=None) -> None:
        """Stop the LM Studio desktop app (menu callback).

        Args:
            _icon: pystray icon (unused).
            _item: pystray menu item (unused).
        """
        if not self.begin_action_cooldown("stop_desktop_app"):
            return
        if not get_desktop_app_pids():
            self.build_menu()
            return

        if self._stop_desktop_app_processes():
            logging.info("LM Studio desktop app stopped")
            self._notify("LM Studio", "Desktop app stopped")
        else:
            logging.error("Could not stop the desktop app")
            self._notify("Error", "Could not stop the desktop app")
        self.build_menu()
        self._schedule_menu_refresh()

    # ------------------------------------------------------------------
    # Dialogs
    # ------------------------------------------------------------------

    def _collect_status_text(self) -> str:
        """Return status text without starting anything.

        ``lms ps`` is not a read-only command: with no service running it
        prints "Waking up LM Studio service..." and boots LM Studio. It is
        therefore only invoked when something is already running locally.

        Returns:
            str: Human-readable status description.
        """
        endpoint = f"{_AppState.API_HOST}:{_AppState.API_PORT}"

        if is_remote_endpoint():
            reachable, has_model = check_api_reachable()
            if not reachable:
                return f"Remote endpoint {endpoint} is not reachable."
            if not has_model:
                return f"Connected to {endpoint}.\nNo model is loaded."
            names = get_api_loaded_models()
            if not names:
                return f"Connected to {endpoint}.\nA model is loaded."
            listed = "\n".join(f"  • {name}" for name in names)
            label = "Loaded model" if len(names) == 1 else "Loaded models"
            return f"Connected to {endpoint}.\n\n{label}:\n{listed}"

        daemon_running = self.get_daemon_status() == "running"
        app_running = self.get_desktop_app_status() == "running"
        if not (daemon_running or app_running):
            return (
                "Neither the daemon nor the desktop app is running.\n"
                "Start one of them to query the model status."
            )

        lms_cmd = get_lms_cmd()
        if not lms_cmd:
            return "LM Studio CLI (lms) not found."

        try:
            result = _run_safe_command([lms_cmd, "ps"])
        except (OSError, subprocess.SubprocessError) as exc:
            return f"Error running lms ps: {exc}"

        if result.returncode == 0 and result.stdout.strip():
            return _format_lms_ps_output(result.stdout.strip())
        return "No model loaded (lms ps returned no output)."

    def show_status_dialog(self, _icon=None, _item=None) -> None:
        """Show the current LM Studio status in a dialog.

        Args:
            _icon: pystray icon (unused).
            _item: pystray menu item (unused).
        """
        _show_tk_message("Status", self._collect_status_text())

    def show_config_dialog(self, _icon=None, _item=None) -> None:
        """Prompt for the LM Studio API endpoint and persist it.

        Args:
            _icon: pystray icon (unused).
            _item: pystray menu item (unused).
        """
        current = f"{_AppState.API_HOST}:{_AppState.API_PORT}"
        response = _prompt_tk_endpoint(current)
        if response is None:
            return

        parsed = parse_host_port(response)
        if parsed is None:
            logging.warning(
                "Rejected invalid API endpoint input: %r", response
            )
            _show_tk_message(
                "Configuration",
                "Could not read that endpoint.\n"
                "Expected host:port, for example localhost:1234.",
            )
            return

        host, port = parsed
        try:
            save_config(host, port)
        except (OSError, ValueError) as exc:
            logging.error("Failed to save configuration: %s", exc)
            _show_tk_message(
                "Configuration",
                f"Could not save the configuration:\n{exc}",
            )
            return

        _AppState.API_HOST = host
        _AppState.API_PORT = port
        logging.info("Updated API endpoint to http://%s:%s", host, port)
        self._notify(
            "Configuration", f"API endpoint set to {host}:{port}"
        )
        self.build_menu()

    def show_about_dialog(self, _icon=None, _item=None) -> None:
        """Show basic application information.

        Args:
            _icon: pystray icon (unused).
            _item: pystray menu item (unused).
        """
        # APP_VERSION already carries its own "v" prefix when it comes from
        # the VERSION file, and is the bare word "dev" otherwise - so no
        # prefix is added here.
        _show_tk_message(
            "About",
            f"LM Studio Tray Manager {_AppState.APP_VERSION}\n"
            f"Maintainer: {APP_MAINTAINER}\n"
            f"{APP_REPOSITORY}\n"
            f"{APP_DOCUMENTATION}\n"
            f"\n"
            f"This program comes WITHOUT ANY WARRANTY.",
        )

    # ------------------------------------------------------------------
    # Update check
    # ------------------------------------------------------------------

    def check_updates(self) -> bool:
        """Check GitHub for a newer release and notify if found.

        Returns:
            bool: ``True`` when an update notification was sent.
        """
        if _AppState.APP_VERSION == DEFAULT_APP_VERSION:
            self._update_info["status"] = "Dev build"
            self.update_status = "Dev build"
            logging.debug("Update check skipped: dev build")
            return False

        latest, error = get_latest_release_version()
        self._update_info["last_error"] = error
        self.last_update_error = error
        if not latest:
            self._update_info["status"] = "Unknown"
            self.update_status = "Unknown"
            logging.debug("Update check failed: %s", error)
            return False

        self._update_info["latest_version"] = latest
        self.latest_update_version = latest
        self._update_info["last_error"] = None
        self.last_update_error = None

        newer = is_newer_version(_AppState.APP_VERSION, latest)
        current_parts = parse_version(_AppState.APP_VERSION)
        latest_parts = parse_version(latest)
        is_ahead = (
            current_parts > latest_parts
            if current_parts and latest_parts
            else False
        )

        if newer:
            self._update_info["status"] = "Update available"
            self.update_status = "Update available"
        elif is_ahead:
            self._update_info["status"] = "Ahead of release"
            self.update_status = "Ahead of release"
        else:
            self._update_info["status"] = "Up to date"
            self.update_status = "Up to date"

        logging.debug(
            "Update check: %s (latest %s)",
            self._update_info["status"],
            latest,
        )

        if not newer:
            return False
        if self._update_info["last_version"] == latest:
            return False

        self._update_info["last_version"] = latest
        self.last_update_version = latest
        url = get_release_url(latest)
        self._notify(
            "Update Available",
            f"New version available: {latest} "
            f"(current {_AppState.APP_VERSION})\n{url}",
        )
        return True

    def manual_check_updates(self, _icon=None, _item=None) -> None:
        """Run an on-demand update check and show the result.

        Args:
            _icon: pystray icon (unused).
            _item: pystray menu item (unused).
        """
        notified = self.check_updates()
        if notified:
            return

        status = self.update_status or "Unknown"
        latest = self.latest_update_version
        error = self.last_update_error
        if status == "Update available" and latest:
            url = get_release_url(latest)
            msg = (
                f"New version available: {latest} "
                f"(current {_AppState.APP_VERSION})\n{url}"
            )
        elif status == "Up to date":
            msg = f"You are up to date ({_AppState.APP_VERSION})"
        elif status == "Dev build":
            msg = "Dev build: update checks disabled"
        elif status == "Ahead of release":
            msg = (
                f"Ahead of release "
                f"(current {_AppState.APP_VERSION}, latest {latest})"
            )
        else:
            detail = f" ({error})" if error else ""
            msg = "Unable to check for updates." + detail

        _show_tk_message("Update Check", msg)

    # ------------------------------------------------------------------
    # Auto-start helpers
    # ------------------------------------------------------------------

    def _maybe_auto_start_daemon(self) -> None:
        """Start the daemon at launch when --auto-start-daemon is set."""
        logging.info(
            "Auto-starting daemon (--auto-start-daemon) with fresh passkey"
        )
        try:
            self._stop_daemon_with_notification()
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            logging.error("Error stopping llmster: %s", e)
        self.action_lock_until = 0.0
        self.start_daemon()

    def _maybe_start_gui(self) -> None:
        """Start the desktop app at launch when --gui is set."""
        logging.info("Auto-starting GUI (--gui)")
        self.start_desktop_app()

    # ------------------------------------------------------------------
    # Quit
    # ------------------------------------------------------------------

    def quit_app(self, _icon=None, _item=None) -> None:
        """Quit the tray application (menu callback).

        Args:
            _icon: pystray icon (unused).
            _item: pystray menu item (unused).
        """
        logging.info("Tray icon terminated")
        self._stop_event.set()
        try:
            self.icon.stop()
        except (AttributeError, RuntimeError) as exc:
            logging.debug("Could not stop the tray icon: %s", exc)


if __name__ == "__main__":
    main()
