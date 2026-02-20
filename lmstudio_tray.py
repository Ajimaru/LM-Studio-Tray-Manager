#!/usr/bin/env python3.10
"""LM Studio Tray Icon Monitor.

A GTK3-based system tray application that monitors the status of the LM Studio
daemon and desktop app. It displays visual indicators and notifications when
status changes, and supports starting/stopping daemon and desktop app as well
as viewing status information through a context menu.

The script accepts optional command-line arguments:
    - sys.argv[1]: Model name to monitor (default: "no-model-passed")
    - sys.argv[2]: Script directory for logging (default: current working dir)

Logging is written to ".logs/lmstudio_tray.log" in the script directory.
"""

import subprocess
import sys
import os
import time
import signal
import logging
import shutil
import importlib
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
Gtk = importlib.import_module("gi.repository.Gtk")
GLib = importlib.import_module("gi.repository.GLib")
AppIndicator3 = importlib.import_module("gi.repository.AyatanaAppIndicator3")


# === Model name from argument or default ===
MODEL = sys.argv[1] if len(sys.argv) > 1 else "no-model-passed"
script_dir = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
DEBUG_MODE = sys.argv[3].lower() == "debug" if len(sys.argv) > 3 else False
logs_dir = os.path.join(script_dir, ".logs")

# === Create logs directory if not exists ===
os.makedirs(logs_dir, exist_ok=True)

# === Set up logging ===
LOG_LEVEL = logging.DEBUG if DEBUG_MODE else logging.INFO
logging.basicConfig(
    filename=os.path.join(logs_dir, "lmstudio_tray.log"),
    level=LOG_LEVEL,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filemode='w'
)

# Redirect Python warnings to log file in debug mode
if DEBUG_MODE:
    logging.captureWarnings(True)
    warnings_logger = logging.getLogger('py.warnings')
    warnings_logger.setLevel(logging.DEBUG)
    logging.debug("Debug mode enabled - capturing warnings to log file")

INTERVAL = 10

# === GTK icon names from the icon browser ===
ICON_OK = "emblem-default"         # ✅ Model loaded
ICON_FAIL = "emblem-unreadable"    # ❌ Daemon and app not installed
ICON_WARN = "dialog-warning"       # ⚠️ Daemon and app stopped
ICON_INFO = "help-info"            # ℹ️ Runtime active, no model
APP_NAME = "LM Studio Tray Monitor"
APP_MAINTAINER = "Ajimaru"
APP_REPOSITORY = "https://github.com/Ajimaru/LM-Studio-Tray-Manager"
DEFAULT_APP_VERSION = "dev"

# === Path to lms-CLI ===
LMS_CLI = os.path.expanduser("~/.lmstudio/bin/lms")


def get_app_version():
    """Load app version from VERSION file in script directory."""
    version_path = os.path.join(script_dir, "VERSION")
    try:
        with open(version_path, "r", encoding="utf-8") as version_file:
            version = version_file.read().strip()
            if version:
                return version
    except OSError:
        pass
    return DEFAULT_APP_VERSION


APP_VERSION = get_app_version()


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


def is_llmster_running():
    """Return True when a llmster process is currently running."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "llmster"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode == 0:
            return True
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        result = subprocess.run(
            ["pgrep", "-f", "llmster"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def get_desktop_app_pids():
    """Return PIDs of LM Studio desktop app root processes."""
    pids = []
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return pids

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue

            parts = line.split(None, 1)
            if len(parts) != 2:
                continue

            pid_text, args = parts
            if not pid_text.isdigit():
                continue

            if "--type=" in args:
                continue

            if (
                "/opt/LM Studio/lm-studio" in args
                or args.startswith("/usr/bin/lm-studio")
                or args.startswith("lm-studio ")
                or args == "lm-studio"
            ):
                pids.append(int(pid_text))
    except (OSError, subprocess.SubprocessError, ValueError):
        return []

    return pids

# === Terminate other instances of this script ===


def kill_existing_instances():
    """Terminate other running instances of this script."""
    result = subprocess.run(
        ["pgrep", "-f", "lmstudio_tray.py"],
        stdout=subprocess.PIPE,
        text=True,
        check=False
    )
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


kill_existing_instances()

logging.info("Tray script started")


class TrayIcon:
    """Manage the GTK tray icon for LM Studio runtime monitoring.

    The tray displays runtime status, provides daemon/app controls, and sends
    desktop notifications on status transitions.
    """
    def __init__(self):
        # Use AppIndicator3 instead of deprecated StatusIcon
        self.indicator = AppIndicator3.Indicator.new(
            "lmstudio-monitor",
            ICON_WARN,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title("LM Studio Monitor")
        self.action_lock_until = 0.0

        # Create persistent menu (AppIndicator requires static menu)
        self.menu = Gtk.Menu()
        self.build_menu()
        self.indicator.set_menu(self.menu)
        self.last_status = None
        self.check_model()
        GLib.timeout_add_seconds(INTERVAL, self.check_model)

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
        try:
            result = subprocess.run(
                ["dpkg", "-l"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if "lm-studio" in result.stdout:
                return "stopped"
        except (OSError, subprocess.SubprocessError):
            pass

        # Check for AppImage
        script_dir_arg = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
        search_paths = [
            script_dir_arg,
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
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
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
        subprocess.run(
            ["pkill", "-x", "llmster"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        subprocess.run(
            ["pkill", "-f", "llmster"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        for _ in range(8):
            if not is_llmster_running():
                break
            time.sleep(0.25)

    def _stop_llmster_best_effort(self):
        """Stop llmster with graceful attempts and force-stop fallback.

        Returns:
            tuple[bool, CompletedProcess | None]:
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
                subprocess.run(
                    [
                        "notify-send",
                        "Error",
                        "Failed to stop desktop app. Please stop it first.",
                    ],
                    check=False,
                )
                self.build_menu()
                return

            logging.info("Desktop app stopped before daemon start")
            self.build_menu()

        start_attempts = self._build_daemon_attempts("start")
        if not start_attempts:
            logging.error("llmster not found")
            subprocess.run(
                [
                    "notify-send",
                    "Error",
                    "llmster/lms not found. Please install LM Studio CLI.",
                ],
                check=False,
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
                subprocess.run(
                    [
                        "notify-send", "LLMster", "llmster daemon is running",
                    ],
                    check=False,
                )
            else:
                err = "Unknown error"
                if result is not None:
                    err = result.stderr.strip() or result.stdout.strip() or err
                logging.error("Failed to start llmster daemon: %s", err)
                subprocess.run(
                    ["notify-send", "Error", f"Daemon start failed: {err}"],
                    check=False,
                )
            self.build_menu()
            GLib.timeout_add_seconds(
                2, lambda: (self.build_menu(), False)[1]
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            logging.error("Error starting llmster daemon: %s", e)
            subprocess.run(
                ["notify-send", "Error", f"Error: {e}"],
                check=False,
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
            subprocess.run(
                [
                    "notify-send",
                    "Error",
                    "llmster/lms not found. Nothing to stop.",
                ],
                check=False,
            )
            return
        try:
            stopped, result = self._stop_llmster_best_effort()

            if stopped:
                logging.info("llmster daemon stopped")
                subprocess.run(
                    [
                        "notify-send",
                        "LLMster",
                        "Daemon stopped. You can now start the desktop app.",
                    ],
                    check=False,
                )
            else:
                err = "llmster process is still running"
                if result is not None:
                    detail = result.stderr.strip() or result.stdout.strip()
                    if detail:
                        err = f"{err}: {detail}"
                logging.error("Failed to stop llmster daemon: %s", err)
                subprocess.run(
                    ["notify-send", "Error", f"Daemon stop failed: {err}"],
                    check=False,
                )

            self.build_menu()
            GLib.timeout_add_seconds(
                2, lambda: (self.build_menu(), False)[1]
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            logging.error("Error stopping llmster daemon: %s", e)
            subprocess.run(
                ["notify-send", "Error", f"Error: {e}"],
                check=False,
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
            subprocess.run(
                [
                    "notify-send",
                    "Error",
                    "lms CLI not found. Cannot launch app.",
                ],
                check=False,
            )
            return

        # Stop headless daemon first to avoid LM Studio conflict dialog
        if is_llmster_running():
            stopped, _result = self._stop_llmster_best_effort()

            if not stopped:
                logging.error(
                    "Cannot start desktop app: llmster still running"
                )
                subprocess.run(
                    [
                        "notify-send",
                        "Error",
                        "Failed to stop daemon. Please stop it first.",
                    ],
                    check=False,
                )
                self.build_menu()
                return

            logging.info("llmster daemon stopped before GUI launch")
            self.build_menu()

        # Step 1: Look for desktop app - prefer .deb, then AppImage
        app_found = False
        app_path = None

        # Check for .deb package
        try:
            result = subprocess.run(
                ["dpkg", "-l"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if "lm-studio" in result.stdout:
                # Start via installed .deb package
                app_path = "lm-studio"
                app_found = True
                logging.info("Found LM Studio .deb package")
        except (OSError, subprocess.SubprocessError) as e:
            logging.warning("Error checking for .deb package: %s", e)

        # If .deb not found, search for AppImage
        if not app_found:
            script_dir_arg = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
            search_paths = [
                script_dir_arg,
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
                subprocess.Popen(
                    [app_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logging.info("Started LM Studio desktop app: %s", app_path)
                subprocess.run(
                    [
                        "notify-send",
                        "LM Studio",
                        "LM Studio GUI is starting...",
                    ],
                    check=False,
                )
                self.build_menu()
                GLib.timeout_add_seconds(
                    2, lambda: (self.build_menu(), False)[1]
                )
            except (OSError, subprocess.SubprocessError) as e:
                logging.error("Failed to start desktop app: %s", e)
                subprocess.run(
                    ["notify-send", "Error", f"Failed to start app: {e}"],
                    check=False,
                )
        else:
            logging.warning(
                "No LM Studio desktop app found (.deb or AppImage)"
            )
            subprocess.run(
                [
                    "notify-send",
                    "Error",
                    "No LM Studio desktop app found.\n"
                    "Please install from https://lmstudio.ai/download",
                ],
                check=False,
            )

    def stop_desktop_app(self, _widget):
        """Stop the LM Studio desktop app process.

        Useful when the window closes to tray but the process remains active.

        Args:
            _widget: Widget that triggered the action (unused).
        """
        if not self.begin_action_cooldown("stop_desktop_app"):
            return

        try:
            result = subprocess.run(
                ["pkill", "-f", "/opt/LM Studio/lm-studio"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                logging.info("LM Studio desktop app stopped")
                subprocess.run(
                    [
                        "notify-send",
                        "LM Studio",
                        "Desktop app stopped",
                    ],
                    check=False,
                )
            else:
                logging.info("No LM Studio desktop app process found to stop")
                subprocess.run(
                    [
                        "notify-send",
                        "LM Studio",
                        "No running desktop app found",
                    ],
                    check=False,
                )
            self.build_menu()
            GLib.timeout_add_seconds(
                2, lambda: (self.build_menu(), False)[1]
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            logging.error("Failed to stop desktop app: %s", e)
            subprocess.run(
                [
                    "notify-send",
                    "Error",
                    f"Desktop app stop failed: {e}",
                ],
                check=False,
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
            result = subprocess.run(
                [lms_cmd, "ps"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
                check=False
            )
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
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="LM Studio Status"
        )
        dialog.format_secondary_text(text)
        dialog.run()
        dialog.destroy()

    def show_about_dialog(self, _widget):
        """Show application information in a GTK dialog."""
        model_context = (
            MODEL if MODEL and MODEL != "no-model-passed" else "none"
        )
        dialog = Gtk.MessageDialog(
            parent=None,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=APP_NAME
        )
        dialog.format_secondary_text(
            f"Version: {APP_VERSION}\n"
            f"Maintainer: {APP_MAINTAINER}\n"
            "Purpose: Monitors and controls LM Studio daemon"
            " and desktop app.\n"
            f"Model context: {model_context}\n"
            f"Repository: {APP_REPOSITORY}"
        )
        dialog.run()
        dialog.destroy()

    def check_model(self):
        """
        Check LM Studio runtime/model status and update the tray icon.

        Updates the tray icon using this schema:
        - FAIL: neither daemon nor desktop app is installed
        - WARN: neither daemon nor desktop app is running
        - INFO: daemon or desktop app is running, but no model is loaded
        - OK: a model is loaded

        Sends desktop notifications when status changes from a previous
        non-None state, and logs status changes and errors.

        Returns:
            bool: True to indicate the check completed (used for scheduled
            callbacks).
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
                    result = subprocess.run(
                        [lms_cmd, "ps"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=0.5,  # Reduced from 5s to prevent UI blocking
                        check=False
                    )
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
                if current_status == "OK":
                    msg = "✅ A model is loaded"
                    subprocess.run(
                        ["notify-send", "LM Studio", msg],
                        check=False
                    )
                elif current_status == "INFO":
                    subprocess.run(
                        [
                            "notify-send",
                            "LM Studio",
                            "ℹ️ Daemon or desktop app is running, "
                            "but no model is loaded",
                        ],
                        check=False
                    )
                elif current_status == "WARN":
                    subprocess.run(
                        [
                            "notify-send",
                            "LM Studio",
                            "⚠️ Neither daemon nor desktop app is running",
                        ],
                        check=False
                    )
                elif current_status == "FAIL":
                    subprocess.run(
                        [
                            "notify-send",
                            "LM Studio",
                            "❌ Daemon and desktop app are not installed",
                        ],
                        check=False
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


TrayIcon()
Gtk.main()
