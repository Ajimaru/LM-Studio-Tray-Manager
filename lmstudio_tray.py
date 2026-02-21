#!/usr/bin/env python3.10
"""LM Studio Tray Icon Monitor.

A GTK3-based system tray application that monitors the status of the LM Studio
daemon and desktop app. It displays visual indicators and notifications when
status changes, and supports starting/stopping daemon and desktop app as well
as viewing status information through a context menu.

Usage:
    lmstudio_tray.py [model] [script_dir] [options]

Notes:
    Command-line arguments:
        model: Model name to monitor (optional, default: "no-model-passed").
        script_dir: Script directory for logs and VERSION file (optional,
            default: current working directory).
        --debug, -d: Enable debug logging (flag).
        --auto-start-daemon, -a: Start llmster daemon on launch (flag).
        --gui, -g: Start LM Studio GUI on launch, stops daemon first (flag).
        --version, -v: Print version and exit (flag).
        --help: Show help message and exit (flag).

    Logging is written to .logs/lmstudio_tray.log in the script directory.
    If the VERSION file is missing, a default version string is used.
"""

# nosec B404 - subprocess is required for system process management
import argparse
import subprocess  # nosec B404
import sys
import os
import time
import signal
import logging
import shutil
import importlib
import json
from urllib import request as urllib_request
from urllib import error as urllib_error
from urllib import parse as urllib_parse

import gi

DEFAULT_APP_VERSION = "dev"


def load_version_from_dir(base_dir):
    """Load app version from the VERSION file.

    Args:
        base_dir (str): Directory path containing the VERSION file.

    Returns:
        str: Version string read from the VERSION file, or DEFAULT_APP_VERSION
            if the file is missing or empty.
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


def parse_args():
    """Parse command-line arguments from sys.argv.

    This function reads all arguments and flags provided on the command line
    via sys.argv and returns them as a structured namespace object.

    Command-line Arguments:
        model (str): Model name to monitor; positional, optional.
        script_dir (str): Script directory for logs; positional, optional.
        --debug, -d (bool): Flag to enable debug logging.
        --auto-start-daemon, -a (bool): Start daemon on launch.
        --gui, -g (bool): Start LM Studio GUI on launch.
        --version, -v (bool): Print version and exit.
        --help (bool): Print help message and exit.

    Returns:
        argparse.Namespace: Parsed arguments as an object with attributes
            matching argument names (e.g., namespace.model, namespace.debug).

    Raises:
        SystemExit: If --help or --version flags are used, or if the
            argument parser encounters invalid arguments (handled by
            argparse.ArgumentParser).
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
        default=os.getcwd(),
        help="Script directory for logs and VERSION file"
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
    args, unknown = parser.parse_known_args()
    if unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    return args


# === Module-level defaults for args-derived globals ===
# These are overridden by main() when run as __main__.
MODEL = "no-model-passed"
script_dir = os.getcwd()
DEBUG_MODE = False
GUI_MODE = False
AUTO_START_DAEMON = False
APP_VERSION = DEFAULT_APP_VERSION

# GTK module globals - populated by main() before TrayIcon is created.
Gtk = None
GLib = None
AppIndicator3 = None

INTERVAL = 10
UPDATE_CHECK_INTERVAL = 60 * 60 * 24

# === GTK icon names from the icon browser ===
ICON_OK = "emblem-default"         # ✅ Model loaded
ICON_FAIL = "emblem-unreadable"    # ❌ Daemon and app not installed
ICON_WARN = "dialog-warning"       # ⚠️ Daemon and app stopped
ICON_INFO = "help-info"            # ℹ️ Runtime active, no model
APP_NAME = "LM Studio Tray Monitor"
APP_MAINTAINER = "Ajimaru"
APP_REPOSITORY = "https://github.com/Ajimaru/LM-Studio-Tray-Manager"
LATEST_RELEASE_API_URL = (
    "https://api.github.com/repos/Ajimaru/LM-Studio-Tray-Manager"
    "/releases/latest"
)
# === Path to lms-CLI ===
LMS_CLI = os.path.expanduser("~/.lmstudio/bin/lms")


def get_app_version():
    """Load app version from VERSION file in script directory.

    Reads the app version from the VERSION file located in the script
    directory. Falls back to DEFAULT_APP_VERSION if the file is missing
    or unreadable.

    Returns:
        str: Version string read from the VERSION file, or
            DEFAULT_APP_VERSION if loading fails.
    """
    return load_version_from_dir(script_dir)


def main():
    """Initialize module globals from CLI args and run the tray application.

    Parses command-line arguments, loads GTK dependencies, configures
    logging, and starts the GTK main loop. Exits immediately when the
    --version flag is provided, without loading GTK.

    Args:
        None. Reads sys.argv internally via parse_args().

    Returns:
        None

    Raises:
        SystemExit: When --version flag is provided (via sys.exit(0)).
    """
    global MODEL, script_dir, DEBUG_MODE, GUI_MODE, AUTO_START_DAEMON
    global Gtk, GLib, AppIndicator3, APP_VERSION

    args = parse_args()

    # === Model name from argument or default ===
    MODEL = args.model
    script_dir = args.script_dir
    DEBUG_MODE = args.debug
    GUI_MODE = args.gui

    if args.auto_start_daemon and args.gui:
        print(
            "Warning: --auto-start-daemon and --gui are mutually exclusive; "
            "--gui takes precedence.",
            file=sys.stderr
        )

    AUTO_START_DAEMON = args.auto_start_daemon and not GUI_MODE

    if args.version:
        print(load_version_from_dir(script_dir))
        sys.exit(0)

    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    Gtk = importlib.import_module("gi.repository.Gtk")
    GLib = importlib.import_module("gi.repository.GLib")
    AppIndicator3 = importlib.import_module(
        "gi.repository.AyatanaAppIndicator3"
    )
    logs_dir = os.path.join(script_dir, ".logs")

    # === Create logs directory if not exists ===
    os.makedirs(logs_dir, exist_ok=True)

    # === Set up logging ===
    LOG_LEVEL = logging.DEBUG if DEBUG_MODE else logging.INFO
    log_file = os.path.join(logs_dir, "lmstudio_tray.log")

    # Write header to log file
    with open(log_file, 'w', encoding='utf-8') as f:
        f.write("="*80 + "\n")
        f.write("LM Studio Tray Monitor Log\n")
        f.write(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("="*80 + "\n")

    logging.basicConfig(
        filename=log_file,
        level=LOG_LEVEL,
        format="%(asctime)s - %(levelname)s - %(message)s",
        filemode='a',
        force=True
    )

    # Redirect Python warnings to log file in debug mode
    if DEBUG_MODE:
        logging.captureWarnings(True)
        warnings_logger = logging.getLogger('py.warnings')
        warnings_logger.setLevel(logging.DEBUG)
        logging.debug(
            "Debug mode enabled - capturing warnings to log file"
        )

    APP_VERSION = get_app_version()

    kill_existing_instances()
    logging.info("Tray script started")

    TrayIcon()
    Gtk.main()


def get_authors():
    """Load authors from AUTHORS file in script directory."""
    authors_path = os.path.join(script_dir, "AUTHORS")
    authors = []
    try:
        with open(authors_path, "r", encoding="utf-8") as authors_file:
            for line in authors_file:
                line = line.strip()
                # Skip empty lines, comments, and headers
                if (
                    line
                    and not line.startswith("#")
                    and not line.startswith("<!--")
                    and line.startswith("-")
                ):
                    # Extract name from markdown list item
                    # Format: "- Name (@handle) - description"
                    author = line[1:].strip()  # Remove leading "-"
                    # Take only the name part before any description
                    if " - " in author:
                        author = author.split(" - ")[0].strip()
                    # Remove GitHub handle if present
                    if "(@" in author:
                        author = author.split(" (@")[0].strip()
                    if author:
                        authors.append(author)
    except OSError:
        pass
    # Fallback to maintainer if no authors found
    return authors if authors else [APP_MAINTAINER]


def parse_version(version):
    """Parse a version string into a comparable tuple of integers."""
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


def is_newer_version(current, latest):
    """Return True when latest is newer than current."""
    current_parts = parse_version(current)
    latest_parts = parse_version(latest)
    if not current_parts or not latest_parts:
        return False
    return latest_parts > current_parts


def _is_allowed_update_url(url):
    """Validate update URL to prevent unsafe schemes or hosts.

    Args:
        url: URL string to validate.

    Returns:
        bool: True when the URL uses HTTPS and GitHub API host.
    """
    parsed = urllib_parse.urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "api.github.com"
        and parsed.path.startswith("/repos/")
    )


def get_latest_release_version():
    """Fetch the latest GitHub release tag name."""
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
        # Create opener with HTTPS support and default handlers
        https_handler = urllib_request.HTTPSHandler()
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
    except (urllib_error.URLError, OSError, ValueError):
        logging.debug("Update check: network or parse error")
        return None, "Network or parse error"


def get_lms_cmd():
    """Return the LM Studio CLI path if executable or resolve it from PATH."""
    if os.path.isfile(LMS_CLI) and os.access(LMS_CLI, os.X_OK):
        return LMS_CLI
    return shutil.which("lms")


def get_llmster_cmd():
    """Return llmster executable path from PATH or LM Studio install dir."""
    llmster_cmd = shutil.which("llmster")
    if llmster_cmd:
        return llmster_cmd

    llmster_root = os.path.expanduser("~/.lmstudio/llmster")
    if not os.path.isdir(llmster_root):
        return None

    candidates = []
    try:
        for entry in os.listdir(llmster_root):
            candidate = os.path.join(llmster_root, entry, "llmster")
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                candidates.append(candidate)
    except (OSError, PermissionError):
        return None

    if not candidates:
        return None
    return sorted(candidates)[-1]


def get_pkill_cmd():
    """Return the absolute pkill path from PATH if available."""
    return shutil.which("pkill")


def get_notify_send_cmd():
    """Return the absolute notify-send path from PATH if available."""
    return shutil.which("notify-send")


def get_ps_cmd():
    """Return the absolute ps path from PATH if available."""
    return shutil.which("ps")


def get_pgrep_cmd():
    """Return the absolute pgrep path from PATH if available."""
    return shutil.which("pgrep")


def get_dpkg_cmd():
    """Return the absolute dpkg path from PATH if available."""
    return shutil.which("dpkg")


def _run_safe_command(command):
    """Run a pre-validated command list via subprocess.

    The caller MUST ensure that ``command`` only contains trusted,
    absolute-path executables resolved through helper functions.

    Args:
        command: List of strings forming the command.

    Returns:
        CompletedProcess: The completed process result.

    Raises:
        ValueError: If command format is invalid or executable is not
            an absolute path.
    """
    if not isinstance(command, list) or not command:
        raise ValueError("Command must be a non-empty list")

    if not all(isinstance(arg, str) for arg in command):
        raise ValueError("All command arguments must be strings")

    exe = command[0]
    if not os.path.isabs(exe):
        raise ValueError(f"Executable must be absolute path: {exe}")

    return subprocess.run(  # nosec B603 B607
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        shell=False,
    )


def is_llmster_running():
    """Return True when a llmster process is currently running."""
    pgrep_cmd = get_pgrep_cmd()
    if not pgrep_cmd or not os.path.isabs(pgrep_cmd):
        return False

    try:
        result = _run_safe_command([pgrep_cmd, "-x", "llmster"])
        if result.returncode == 0:
            return True
    except (FileNotFoundError, ValueError):
        return False
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        result = _run_safe_command([pgrep_cmd, "-f", "llmster"])
        return result.returncode == 0
    except (FileNotFoundError, ValueError):
        return False
    except (OSError, subprocess.SubprocessError):
        return False


def get_desktop_app_pids():
    """Return PIDs of LM Studio desktop app root processes."""
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

            # Exclude daemon worker processes (llmster, systemresourcesworker,
            # liblmstudioworker, etc.). These are child processes managed by
            # the daemon and should not count as desktop app running.
            if (
                "systemresourcesworker" in cmd_args
                or "liblmstudioworker" in cmd_args
                or "/llmster/" in cmd_args
            ):
                continue

            if (
                "/opt/LM Studio/lm-studio" in cmd_args
                or cmd_args.startswith("/usr/bin/lm-studio")
                or cmd_args.startswith("lm-studio ")
                or cmd_args == "lm-studio"
            ):
                pids.append(int(pid_text))
    except (OSError, subprocess.SubprocessError, ValueError):
        return []

    return pids

# === Terminate other instances of this script ===


def kill_existing_instances():
    """Terminate other running instances of this script."""
    pgrep_cmd = get_pgrep_cmd()
    if not pgrep_cmd:
        logging.warning("pgrep not found; cannot detect existing instances")
        return
    result = _run_safe_command([pgrep_cmd, "-f", "lmstudio_tray.py"])
    pids = [
        int(pid)
        for pid in result.stdout.strip().split("\n")
        if pid.isdigit()
    ]
    current_pid = os.getpid()
    for pid in pids:
        if pid != current_pid:
            try:
                os.kill(pid, signal.SIGTERM)
                logging.info("Terminating old instance: PID %s", pid)
            except (OSError, ProcessLookupError, PermissionError) as e:
                logging.warning("Error terminating PID %s: %s", pid, e)


class TrayIcon:
    """Manage the GTK tray icon for LM Studio runtime monitoring.

    The tray displays runtime status, provides daemon/app controls, and sends
    desktop notifications on status transitions.
    """
    def __init__(self):
        """Initialize tray indicator, menu, and periodic status checks."""
        # Use AppIndicator3 instead of deprecated StatusIcon
        self.indicator = AppIndicator3.Indicator.new(
            "lmstudio-monitor",
            ICON_WARN,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title("LM Studio Monitor")
        self.action_lock_until = 0.0
        self.last_update_version = None
        self.update_status = "Unknown"
        self.latest_update_version = None
        self.last_update_error = None

        # Create persistent menu (AppIndicator requires static menu)
        self.menu = Gtk.Menu()
        self.build_menu()
        self.indicator.set_menu(self.menu)
        self.last_status = None
        self.check_model()
        GLib.timeout_add_seconds(INTERVAL, self.check_model)
        GLib.timeout_add_seconds(5, self._initial_update_check)
        GLib.timeout_add_seconds(
            UPDATE_CHECK_INTERVAL,
            self._check_updates_tick,
        )
        if hasattr(GLib, "idle_add"):
            GLib.idle_add(self._maybe_auto_start_daemon)
            GLib.idle_add(self._maybe_start_gui)

    def _maybe_auto_start_daemon(self):
        """Start llmster daemon on launch when enabled."""
        if not AUTO_START_DAEMON:
            return False

        if self.get_daemon_status() == "running":
            logging.info("Auto-start skipped: daemon already running")
            return False

        logging.info("Auto-starting daemon (flag --auto-start-daemon)")
        self.start_daemon(None)
        return False

    def _maybe_start_gui(self):
        """Start LM Studio GUI on launch when enabled."""
        if not GUI_MODE:
            return False

        logging.info("Auto-starting GUI (flag --gui)")
        self.start_desktop_app(None)
        return False

    def begin_action_cooldown(self, action_name, seconds=2.0):
        """Prevent rapid double-triggering of tray actions."""
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

    def build_menu(self):
        """Build or rebuild the context menu with current status and
        options.
        """
        # Clear existing menu items
        for item in self.menu.get_children():
            self.menu.remove(item)

        # Get current status indicators
        daemon_status = self.get_daemon_status()
        app_status = self.get_desktop_app_status()
        daemon_indicator = self.get_status_indicator(daemon_status)
        app_indicator = self.get_status_indicator(app_status)

        # === DAEMON CONTROL ===
        if daemon_status == "running":
            daemon_item = Gtk.MenuItem(
                label=f"{daemon_indicator} Daemon (Running)"
            )
            daemon_item.set_sensitive(False)
            self.menu.append(daemon_item)
            stop_daemon_item = Gtk.MenuItem(
                label="  → Stop Daemon"
            )
            stop_daemon_item.connect("activate", self.stop_daemon)
            self.menu.append(stop_daemon_item)
        elif daemon_status == "stopped":
            start_daemon_item = Gtk.MenuItem(
                label=f"{daemon_indicator} Start Daemon (Headless)"
            )
            start_daemon_item.connect("activate", self.start_daemon)
            self.menu.append(start_daemon_item)
        else:  # not_found
            not_found_item = Gtk.MenuItem(
                label=f"{daemon_indicator} Daemon (Not Installed)"
            )
            not_found_item.set_sensitive(False)
            self.menu.append(not_found_item)

        # === DESKTOP APP CONTROL ===
        if app_status == "running":
            app_item = Gtk.MenuItem(
                label=f"{app_indicator} Desktop App (Running)"
            )
            app_item.set_sensitive(False)
            self.menu.append(app_item)
            stop_app_item = Gtk.MenuItem(label="  → Stop Desktop App")
            stop_app_item.connect("activate", self.stop_desktop_app)
            self.menu.append(stop_app_item)
        elif app_status == "stopped":
            start_app_item = Gtk.MenuItem(
                label=f"{app_indicator} Start Desktop App"
            )
            start_app_item.connect("activate", self.start_desktop_app)
            self.menu.append(start_app_item)
        elif app_status == "not_found":
            not_found_item = Gtk.MenuItem(
                label=f"{app_indicator} Desktop App (Not Installed)"
            )
            not_found_item.set_sensitive(False)
            self.menu.append(not_found_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        status_item = Gtk.MenuItem(label="Show Status")
        status_item.connect("activate", self.show_status_dialog)
        self.menu.append(status_item)

        update_item = Gtk.MenuItem(label="Check for updates")
        update_item.connect("activate", self.manual_check_updates)
        self.menu.append(update_item)

        about_item = Gtk.MenuItem(label="About")
        about_item.connect("activate", self.show_about_dialog)
        self.menu.append(about_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit Tray")
        quit_item.connect("activate", self.quit_app)
        self.menu.append(quit_item)

        self.menu.show_all()

    def get_daemon_status(self):
        """Check if llmster headless daemon is running.

        Returns:
            str: "running" if daemon process is active,
                 "stopped" if llmster is installed but daemon not running,
                 "not_found" if llmster is not installed.
        """
        try:
            llmster_cmd = get_llmster_cmd()
            if not llmster_cmd:
                return "not_found"

            if is_llmster_running():
                return "running"

            # llmster exists but daemon process is not active
            return "stopped"
        except (
            OSError,
            subprocess.SubprocessError,
            subprocess.TimeoutExpired,
        ):
            return "not_found"

    def get_desktop_app_status(self):
        """Check if LM Studio desktop app is running.

        The desktop app is started via lmstudio_autostart.sh --gui or directly,
        and runs WITHOUT the --run-as-service flag.

        This is different from the headless daemon (--run-as-service).

        Returns:
            str: "running" if desktop app process is active,
                 "stopped" if installed but not running,
                 "not_found" if not installed.
        """
        # Check if LM Studio app process exists.
        # On this system, LM Studio may run with --run-as-service while still
        # representing the desktop app (minimized to tray), so count it as app
        # running.
        try:
            if get_desktop_app_pids():
                return "running"
        except (OSError, subprocess.SubprocessError):
            pass

        # Check if app is available but not running
        # Check for .deb package
        dpkg_cmd = get_dpkg_cmd()
        if dpkg_cmd and os.path.isabs(dpkg_cmd):
            try:
                result = _run_safe_command([dpkg_cmd, "-l"])
                if "lm-studio" in result.stdout:
                    return "stopped"
            except (OSError, subprocess.SubprocessError):
                pass

        # Check for AppImage
        search_paths = [
            script_dir,
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
                for entry in os.listdir(search_path):
                    if entry.endswith(".AppImage"):
                        return "stopped"
            except (OSError, PermissionError):
                pass

        return "not_found"

    def get_status_indicator(self, status):
        """Convert status string to emoji indicator.

        Args:
            status: "running", "stopped", or "not_found"

        Returns:
            str: Emoji indicator (🟢 running, 🟡 stopped, 🔴 not_found)
        """
        if status == "running":
            return "🟢"
        elif status == "stopped":
            return "🟡"
        else:
            return "🔴"

    @staticmethod
    def _run_validated_command(command):
        """Run a pre-validated command list via subprocess.

        The caller MUST ensure that ``command`` only contains trusted,
        absolute-path executables resolved through ``get_lms_cmd``,
        ``get_llmster_cmd`` or equivalent helpers.

        Args:
            command: List of strings forming the command.

        Returns:
            CompletedProcess: The completed process result.

        Raises:
            ValueError: If command format is invalid or executable is not
                absolute path.
        """
        return _run_safe_command(command)

    def _run_daemon_attempts(self, attempts, stop_when):
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
            # Validate command is a list of strings to prevent injection
            if not isinstance(command, list) or not all(
                isinstance(arg, str) for arg in command
            ):
                logging.error("Invalid command format: %s", command)
                continue

            # Ensure the executable is an absolute path
            exe = command[0] if command else ""
            if not os.path.isabs(exe):
                logging.error(
                    "Refusing to run non-absolute executable: %s", exe
                )
                continue

            result = self._run_validated_command(command)
            if stop_when(result):
                break
        return result

    def _build_daemon_attempts(self, action):
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
            if lms_cmd:
                attempts.extend(
                    [
                        [lms_cmd, "daemon", "up"],
                        [lms_cmd, "daemon", "start"],
                        [lms_cmd, "up"],
                        [lms_cmd, "start"],
                    ]
                )
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

    def _force_stop_llmster(self):
        """Force-stop llmster and wait briefly for process exit."""
        pkill_cmd = get_pkill_cmd()
        if not pkill_cmd:
            logging.warning("pkill not found; cannot force-stop llmster")
            return

        self._run_validated_command([pkill_cmd, "-x", "llmster"])
        self._run_validated_command([pkill_cmd, "-f", "llmster"])

        for _ in range(8):
            if not is_llmster_running():
                break
            time.sleep(0.25)

    def _stop_llmster_best_effort(self):
        """Stop llmster with graceful attempts and force-stop fallback.

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

        if is_llmster_running():
            self._force_stop_llmster()

        return (not is_llmster_running(), result)

    def _stop_desktop_app_processes(self):
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
                    os.kill(pid, signal.SIGKILL)
                except (OSError, ProcessLookupError, PermissionError):
                    pass

            for _ in range(8):
                if self.get_desktop_app_status() != "running":
                    break
                time.sleep(0.25)

        return self.get_desktop_app_status() != "running"

    def start_daemon(self, _widget):
        """Start the headless daemon.

        Stops the desktop app first if needed, then tries daemon start
        variants and notifies on success/failure.

        Args:
            _widget: Widget that triggered the action (unused).
        """
        if not self.begin_action_cooldown("start_daemon"):
            return

        # Stop desktop app first to avoid daemon/app conflict
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
                            ("Failed to stop desktop app. "
                             "Please stop it first."),
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
                        "Error",
                        "llmster/lms not found. Please install LM Studio CLI.",
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
                # Avoid f-string in subprocess to prevent injection
                error_msg = "Daemon start failed: " + str(err)
                notify_cmd = get_notify_send_cmd()
                if notify_cmd:
                    self._run_validated_command(
                        [notify_cmd, "Error", error_msg]
                    )
            self.build_menu()
            GLib.timeout_add_seconds(
                2, lambda: (self.build_menu(), False)[1]
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            logging.error("Error starting llmster daemon: %s", e)
            notify_cmd = get_notify_send_cmd()
            if notify_cmd:
                self._run_validated_command(
                    [notify_cmd, "Error", "Error: " + str(e)]
                )
            self.build_menu()

    def stop_daemon(self, _widget):
        """Stop the headless daemon.

        Tries graceful stop variants first and falls back to force-stop.

        Args:
            _widget: Widget that triggered the action (unused).
        """
        if not self.begin_action_cooldown("stop_daemon"):
            return

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
            return
        try:
            stopped, result = self._stop_llmster_best_effort()

            if stopped:
                logging.info("llmster daemon stopped")
                notify_cmd = get_notify_send_cmd()
                if notify_cmd:
                    self._run_validated_command(
                        [
                            notify_cmd,
                            "LLMster",
                            "Daemon stopped. You can now "
                            "start the desktop app.",
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

            self.build_menu()
            GLib.timeout_add_seconds(
                2, lambda: (self.build_menu(), False)[1]
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            logging.error("Error stopping llmster daemon: %s", e)
            notify_cmd = get_notify_send_cmd()
            if notify_cmd:
                self._run_validated_command(
                    [notify_cmd, "Error", "Error: " + str(e)]
                )
            self.build_menu()

    def start_desktop_app(self, _widget):
        """Start the LM Studio desktop app.

        Stops the daemon first if needed, locates the app (.deb or AppImage),
        and launches it with user notification.

        Args:
            _widget: Widget that triggered the action (unused).
        """
        if not self.begin_action_cooldown("start_desktop_app"):
            return

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

        # Stop headless daemon first to avoid LM Studio conflict dialog
        if is_llmster_running():
            stopped, _result = self._stop_llmster_best_effort()

            if not stopped:
                logging.error(
                    "Cannot start desktop app: llmster still running"
                )
                notify_cmd = get_notify_send_cmd()
                if notify_cmd:
                    self._run_validated_command(
                        [
                            notify_cmd,
                            "Error",
                            "Failed to stop daemon. Please stop it first.",
                        ]
                    )
                self.build_menu()
                return

            logging.info("llmster daemon stopped before GUI launch")
            self.build_menu()

        # Step 1: Look for desktop app - prefer .deb, then AppImage
        app_found = False
        app_path = None

        # Check for .deb package
        dpkg_cmd = get_dpkg_cmd()
        if dpkg_cmd:
            try:
                result = _run_safe_command([dpkg_cmd, "-l"])
                if "lm-studio" in result.stdout:
                    # Start via installed .deb package
                    app_path = "lm-studio"
                    app_found = True
                    logging.info("Found LM Studio .deb package")
            except (OSError, subprocess.SubprocessError) as e:
                logging.warning("Error checking for .deb package: %s", e)

        # If .deb not found, search for AppImage
        if not app_found:
            search_paths = [
                script_dir,
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
                    for entry in os.listdir(search_path):
                        if entry.endswith(".AppImage"):
                            app_path = os.path.join(search_path, entry)
                            app_found = True
                            logging.info("Found AppImage: %s", app_path)
                            break
                    if app_found:
                        break
                except (OSError, PermissionError) as e:
                    logging.warning("Error searching %s: %s", search_path, e)

        # Step 2: Start the app if found
        if app_found and app_path:
            try:
                # Validate app_path to prevent command injection
                # For .deb packages, resolve to absolute path
                if app_path == "lm-studio":
                    resolved_path = shutil.which("lm-studio")
                    if not resolved_path or not os.path.isabs(resolved_path):
                        raise ValueError(
                            "lm-studio executable not found"
                            " in PATH"
                        )
                    app_path = resolved_path

                # Ensure app_path is absolute and exists
                if not os.path.isabs(app_path):
                    raise ValueError(f"App path must be absolute: {app_path}")
                if not os.path.isfile(app_path):
                    raise ValueError(f"App path does not exist: {app_path}")
                if not os.access(app_path, os.X_OK):
                    raise ValueError(f"App path is not executable: {app_path}")

                # Final validation: app_path must be a string and absolute
                if not isinstance(app_path, str):
                    raise ValueError("App path must be a string")

                # Additional security: validate path against
                # known LM Studio locations
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

                # Also allow if it's the resolved lm-studio from PATH
                if shutil.which("lm-studio") == app_path:
                    is_safe = True

                if not is_safe:
                    msg = ("App path not in safe "
                           f"locations: {app_path}")
                    raise ValueError(msg)

                # Create validated command list
                validated_cmd = [app_path]

                # Use context manager for proper resource management
                # pylint: disable=consider-using-with
                # nosec B603 B607 - app_path validated against whitelist
                process = subprocess.Popen(
                    validated_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                )
                # Process is intentionally detached - no need to wait
                logging.info(
                    "Started LM Studio desktop app: %s (PID: %s)",
                    app_path,
                    process.pid
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
                self.build_menu()
                GLib.timeout_add_seconds(
                    2, lambda: (self.build_menu(), False)[1]
                )
            except (OSError, subprocess.SubprocessError) as e:
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
                        "No LM Studio desktop app found.\n"
                        "Please install from "
                        "https://lmstudio.ai/download",
                    ]
                )

    def stop_desktop_app(self, _widget):
        """Stop the LM Studio desktop app process.

        Useful when the window closes to tray but the process remains active.

        Args:
            _widget: Widget that triggered the action (unused).
        """
        if not self.begin_action_cooldown("stop_desktop_app"):
            return

        pkill_cmd = get_pkill_cmd()
        if not pkill_cmd:
            logging.warning("pkill not found; cannot stop desktop app")
            notify_cmd = get_notify_send_cmd()
            if notify_cmd:
                self._run_validated_command(
                    [
                        notify_cmd,
                        "Error",
                        "pkill not found. Cannot stop desktop app.",
                    ]
                )
            return

        try:
            result = self._run_validated_command(
                [pkill_cmd, "-f", "/opt/LM Studio/lm-studio"]
            )
            if result.returncode == 0:
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
            self.build_menu()
            GLib.timeout_add_seconds(
                2, lambda: (self.build_menu(), False)[1]
            )
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
        Gtk.main_quit()

    def show_status_dialog(self, _widget):
        """
        Show a GTK message dialog containing the LM Studio CLI status output.

        Runs `lms ps` to retrieve status information, formats a friendly
        message on success or error, and displays it in an informational
        dialog. Errors are caught and shown to the user instead of raising.
        """
        try:
            lms_cmd = get_lms_cmd()
            if not lms_cmd:
                raise RuntimeError("lms CLI not found")
            result = _run_safe_command([lms_cmd, "ps"])
            if result.returncode == 0 and result.stdout.strip():
                text = result.stdout.strip()
            else:
                text = "No models loaded or error."
        except (
            OSError,
            RuntimeError,
            subprocess.SubprocessError,
            subprocess.TimeoutExpired
        ) as e:
            text = f"Error retrieving status: {str(e)}"

        dialog = Gtk.MessageDialog(
            parent=None,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="LM Studio Status"
        )
        dialog.format_secondary_text(text)
        dialog.run()
        dialog.destroy()

    def show_about_dialog(self, _widget):
        """Show application information in a GTK dialog."""
        dialog = Gtk.AboutDialog()
        dialog.set_program_name(APP_NAME)
        dialog.set_version(self.get_version_label())
        dialog.set_authors(get_authors())
        dialog.set_website(APP_REPOSITORY)
        dialog.set_website_label("GitHub Repository")
        dialog.set_comments(
            "Monitors and controls LM Studio daemon and desktop app."
        )
        dialog.set_modal(True)
        dialog.run()
        dialog.destroy()

    def get_version_label(self):
        """Return version text with update status for the About dialog.

        Returns:
            str: Version text in the format '<APP_VERSION> (<status>)'.
        """
        status = self.update_status or "Unknown"
        return f"{APP_VERSION} ({status})"

    def _check_updates_tick(self):
        """Run the update check for scheduled timers."""
        self.check_updates()
        return True

    def _initial_update_check(self):
        """Run a single update check shortly after startup."""
        self.check_updates()
        return False

    def _format_update_check_message(self, status, latest, error):
        """Build the update check notification message."""
        if status == "Update available" and latest:
            return (
                f"New version available: {latest} (current {APP_VERSION})"
            )

        messages = {
            "Up to date": f"You are up to date ({APP_VERSION})",
            "Dev build": "Dev build: update checks disabled",
        }
        message = messages.get(status)
        if message:
            return message

        detail = f" ({error})" if error else ""
        return "Unable to check for updates." + detail

    def manual_check_updates(self, _widget):
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

    def check_updates(self):
        """Check GitHub for a newer release and notify the user.

        Returns:
            bool: True if a notification was sent.
        """
        if APP_VERSION == DEFAULT_APP_VERSION:
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

        newer = is_newer_version(APP_VERSION, latest)
        self.update_status = "Update available" if newer else "Up to date"
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
            message = (
                f"New version available: {latest} (current {APP_VERSION})"
            )
            self._run_validated_command(
                [notify_cmd, "Update Available", message]
            )
            return True
        return False

    def check_model(self):
        """Check LM Studio runtime/model status and update tray icon.

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
                self.indicator.set_icon_full(
                    ICON_FAIL,
                    "Daemon and desktop app not installed"
                )
            elif not any_running:
                current_status = "WARN"
                self.indicator.set_icon_full(
                    ICON_WARN,
                    "Daemon and desktop app stopped"
                )
            else:
                current_status = "INFO"
                self.indicator.set_icon_full(
                    ICON_INFO,
                    "No model loaded"
                )

                # Query lms ps whenever daemon or desktop app is running.
                # This avoids daemon wake-up in fully stopped state while still
                # allowing model detection in GUI-only mode.
                if any_running and lms_cmd:
                    result = _run_safe_command([lms_cmd, "ps"])
                    if result.returncode == 0 and result.stdout.strip():
                        current_status = "OK"
                        self.indicator.set_icon_full(ICON_OK, "Model loaded")
                else:
                    current_status = "INFO"
                    self.indicator.set_icon_full(ICON_INFO, "No model loaded")

            if (
                self.last_status != current_status
                and self.last_status is not None
            ):
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
                # Update menu to reflect new status
                self.build_menu()

            self.last_status = current_status
            self.build_menu()

        except subprocess.TimeoutExpired:
            # Timeout usually means lms ps is slow. Keep previous status to
            # avoid flashing tray state.
            logging.debug("Timeout in lms ps check (keeping previous status)")
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            self.indicator.set_icon_full(ICON_FAIL, "Error checking status")
            logging.error("Error in status check: %s", e)
            self.build_menu()
        return True


if __name__ == "__main__":
    main()
