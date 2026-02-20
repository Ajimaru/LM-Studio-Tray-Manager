#!/usr/bin/env python3.10
"""LM Studio Tray Icon Monitor.

A GTK3-based system tray application that monitors the status of the LM Studio
daemon and loaded models. It displays visual indicators and notifications when
model status changes, and supports starting the daemon, reloading models, and
viewing status information through a context menu.

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
ICON_OK = "emblem-default"         # ✅ Model active
ICON_FAIL = "emblem-unreadable"    # ❌ LM-Studio daemon not running
ICON_WARN = "dialog-warning"       # ⚠️ No modell loaded
ICON_INFO = "help-info"            # ℹ️ Loaded model changed

# === Path to lms-CLI ===
LMS_CLI = os.path.expanduser("~/.lmstudio/bin/lms")


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
    """Manages a GTK tray icon for monitoring LM Studio model status.

    This class creates and maintains a system tray icon that displays the
    current status of LM Studio models. It periodically checks if the
    expected model is loaded and provides a context menu for daemon
    management, model reloading, and status viewing. Status changes trigger
    desktop notifications.
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
        self.action_lock_name = None

        # Create persistent menu (AppIndicator requires static menu)
        self.menu = Gtk.Menu()
        self.build_menu()
        self.indicator.set_menu(self.menu)
        self.last_status = None
        self.check_model()
        GLib.timeout_add_seconds(INTERVAL, self.check_model)

    def on_click(self, _icon):
        """Handle tray icon click by sending a model status notification.

        Args:
            _icon: The system tray icon instance that triggered the
                click event.
        """
        subprocess.run(
            [
                "notify-send",
                "LM Studio",
                f"Model status: {MODEL} is being monitored",
            ],
            check=False,
        )

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
        self.action_lock_name = action_name
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
                label=f"{daemon_indicator} Daemon (running)"
            )
            daemon_item.set_sensitive(False)
            self.menu.append(daemon_item)
            stop_daemon_item = Gtk.MenuItem(
                label="  → Stop daemon"
            )
            stop_daemon_item.connect("activate", self.stop_daemon)
            self.menu.append(stop_daemon_item)
        elif daemon_status == "stopped":
            start_daemon_item = Gtk.MenuItem(
                label=f"{daemon_indicator} Start Daemon (headless)"
            )
            start_daemon_item.connect("activate", self.start_daemon)
            self.menu.append(start_daemon_item)
        else:  # not_found
            not_found_item = Gtk.MenuItem(
                label=f"{daemon_indicator} Daemon (not installed)"
            )
            not_found_item.set_sensitive(False)
            self.menu.append(not_found_item)

        # === DESKTOP APP CONTROL ===
        if app_status == "running":
            app_item = Gtk.MenuItem(
                label=f"{app_indicator} Desktop App (running)"
            )
            app_item.set_sensitive(False)
            self.menu.append(app_item)
            stop_app_item = Gtk.MenuItem(label="  → Stop Desktop App")
            stop_app_item.connect("activate", self.stop_desktop_app)
            self.menu.append(stop_app_item)
        elif app_status == "stopped":
            start_app_item = Gtk.MenuItem(
                label=f"{app_indicator} Start Desktop App (with GUI)"
            )
            start_app_item.connect("activate", self.start_desktop_app)
            self.menu.append(start_app_item)
        elif app_status == "not_found":
            not_found_item = Gtk.MenuItem(
                label=f"{app_indicator} Desktop App (not installed)"
            )
            not_found_item.set_sensitive(False)
            self.menu.append(not_found_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        reload_item = Gtk.MenuItem(label="Reload model")
        reload_item.connect("activate", self.reload_model)
        self.menu.append(reload_item)

        status_item = Gtk.MenuItem(label="Show status")
        status_item.connect("activate", self.show_status_dialog)
        self.menu.append(status_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit tray")
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
        """Check if LM Studio desktop app (GUI) is running.

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
            result = subprocess.run(
                ["ps", "-eo", "args="],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            if result.returncode == 0:
                for args in result.stdout.splitlines():
                    if "--type=" in args:
                        continue
                    if (
                        "/opt/LM Studio/lm-studio" in args
                        or args.startswith("/usr/bin/lm-studio")
                        or args.startswith("lm-studio ")
                        or args == "lm-studio"
                    ):
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

    def start_daemon(self, _widget):
        """Start or ensure the llmster daemon is running.

        Tries common llmster start command variants and notifies the user
        about success or failure.

        Args:
            _widget: UI widget that triggered the action (unused).
        """
        if not self.begin_action_cooldown("start_daemon"):
            return

        llmster_cmd = get_llmster_cmd()
        lms_cmd = get_lms_cmd()
        if not llmster_cmd and not lms_cmd:
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
            result = None
            start_attempts = []
            if lms_cmd:
                start_attempts.extend(
                    [
                        [lms_cmd, "daemon", "up"],
                        [lms_cmd, "daemon", "start"],
                        [lms_cmd, "up"],
                        [lms_cmd, "start"],
                    ]
                )
            if llmster_cmd:
                start_attempts.extend(
                    [
                        [llmster_cmd, "daemon", "up"],
                        [llmster_cmd, "daemon", "start"],
                        [llmster_cmd, "up"],
                        [llmster_cmd, "start"],
                    ]
                )

            for command in start_attempts:
                result = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                if result.returncode == 0 and is_llmster_running():
                    break

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
        """Stop the llmster daemon.

        Tries common llmster stop command variants.

        Args:
            _widget: UI widget that triggered the action (unused).
        """
        if not self.begin_action_cooldown("stop_daemon"):
            return

        llmster_cmd = get_llmster_cmd()
        lms_cmd = get_lms_cmd()
        if not llmster_cmd and not lms_cmd:
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
            result = None
            stop_attempts = []
            if lms_cmd:
                stop_attempts.extend(
                    [
                        [lms_cmd, "daemon", "down"],
                        [lms_cmd, "daemon", "stop"],
                        [lms_cmd, "down"],
                        [lms_cmd, "stop"],
                    ]
                )
            if llmster_cmd:
                stop_attempts.extend(
                    [
                        [llmster_cmd, "daemon", "down"],
                        [llmster_cmd, "daemon", "stop"],
                        [llmster_cmd, "down"],
                        [llmster_cmd, "stop"],
                    ]
                )

            for command in stop_attempts:
                result = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                if not is_llmster_running():
                    break

            if is_llmster_running():
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

                for _ in range(6):
                    if not is_llmster_running():
                        break
                    time.sleep(0.3)

            if not is_llmster_running():
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
        """Start the LM Studio desktop application.

        Searches for the desktop app in order of preference:
        1. .deb package installation
        2. AppImage in common locations and script directory

        Note: If the headless daemon is running, LM Studio GUI will show a
        dialog asking to quit the daemon first. This is handled by the
        GUI itself.

        If no desktop app is found, displays an error notification.

        Args:
            _widget: The widget that triggered this callback (unused).
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
        """Stop LM Studio desktop app/background process completely.

        This is useful when closing the window only minimizes to tray and the
        process keeps running in the background.

        Args:
            _widget: The widget that triggered this callback (unused).
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

    def reload_model(self, _widget):
        """
        Reload the currently loaded model in LM Studio.

        Args:
            _widget: The widget that triggered this callback (unused).

        Raises:
            Logs errors and displays notifications if model reloading fails.
        """
        if MODEL != "no-model-passed":
            try:
                lms_cmd = get_lms_cmd()
                if not lms_cmd:
                    subprocess.run(
                        ["notify-send", "Error", "lms CLI not found"],
                        check=False,
                    )
                    return
                subprocess.run([lms_cmd, "load", MODEL], check=False)
                logging.info("Model reloaded: %s", MODEL)
                subprocess.run(
                    [
                        "notify-send",
                        "LM Studio",
                        f"Model {MODEL} is being reloaded",
                    ],
                    check=False,
                )
            except (OSError, RuntimeError, subprocess.SubprocessError) as e:
                logging.error("Error reloading model: %s", e)
                err_msg = f"Model could not be reloaded: {e}"
                subprocess.run(
                    ["notify-send", "Error", err_msg],
                    check=False,
                )
        else:
            subprocess.run(
                ["notify-send", "Info", "No model specified for reloading"],
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

    def check_model(self):
        """
        Check the status of the LM Studio model and update the tray icon.

        Queries the LM Studio CLI to determine if the expected model is
        loaded and active. Updates the status icon and tooltip based on the
        current state (OK, INFO, WARN, FAIL). Sends desktop notifications when
        status changes from a previous non-None state, and logs status changes
        and errors.

        Returns:
            bool: True to indicate the check completed (used for scheduled
            callbacks).
        """
        try:
            if not get_llmster_cmd():
                self.indicator.set_icon_full(
                    ICON_WARN,
                    "Monitoring only (llmster not installed)"
                )
                self.last_status = "MONITOR_ONLY"
                self.build_menu()
                return True

            lms_cmd = get_lms_cmd()
            if not lms_cmd:
                self.indicator.set_icon_full(ICON_FAIL, "LM Studio not found")
                return True
            current_status = None
            if self.get_daemon_status() != "running":
                current_status = "FAIL"
                self.indicator.set_icon_full(ICON_FAIL, "Daemon not running")
            else:
                result = subprocess.run(
                    [lms_cmd, "ps"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=0.5,  # Reduced from 5s to prevent UI blocking
                    check=False
                )
                if result.returncode == 0:
                    if MODEL in result.stdout:
                        current_status = "OK"
                        self.indicator.set_icon_full(ICON_OK, "Model active")
                    elif result.stdout.strip():
                        current_status = "INFO"
                        self.indicator.set_icon_full(
                            ICON_INFO, "Model changed"
                        )
                    else:
                        current_status = "WARN"
                        self.indicator.set_icon_full(
                            ICON_WARN,
                            "No model loaded"
                        )
                else:
                    current_status = "FAIL"
                    self.indicator.set_icon_full(
                        ICON_FAIL,
                        "Daemon not running"
                    )

            if (
                self.last_status != current_status
                and self.last_status is not None
            ):
                if current_status == "OK":
                    msg = f"✅ Model {MODEL} is now active"
                    subprocess.run(
                        ["notify-send", "LM Studio", msg],
                        check=False
                    )
                elif current_status == "INFO":
                    subprocess.run(
                        [
                            "notify-send",
                            "LM Studio",
                            "ℹ️ Model changed to another one",
                        ],
                        check=False
                    )
                elif current_status == "WARN":
                    subprocess.run(
                        [
                            "notify-send",
                            "LM Studio",
                            f"⚠️ No model loaded (expected: {MODEL})",
                        ],
                        check=False
                    )
                elif current_status == "FAIL":
                    subprocess.run(
                        [
                            "notify-send",
                            "LM Studio",
                            "❌ LM Studio has stopped",
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
            # Timeout usually means lms ps is slow, not that daemon is down
            # Keep previous status to avoid flashing tooltips
            logging.debug("Timeout in lms ps check (keeping previous status)")
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            self.indicator.set_icon_full(ICON_FAIL, "Error checking status")
            logging.error("Error in status check: %s", e)
            self.build_menu()
        return True


TrayIcon()
Gtk.main()
