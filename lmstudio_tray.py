#!/usr/bin/env python3
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
import signal
import logging
import shutil
import importlib
import gi

gi.require_version("Gtk", "3.0")
Gtk = importlib.import_module("gi.repository.Gtk")
GLib = importlib.import_module("gi.repository.GLib")


# === Model name from argument or default ===
MODEL = sys.argv[1] if len(sys.argv) > 1 else "no-model-passed"
script_dir = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
logs_dir = os.path.join(script_dir, ".logs")

# === Create logs directory if not exists ===
os.makedirs(logs_dir, exist_ok=True)

# === Set up logging ===
logging.basicConfig(
    filename=os.path.join(logs_dir, "lmstudio_tray.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filemode='w'
)
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
        self.status_icon = Gtk.StatusIcon()
        self.status_icon.set_visible(True)
        self.status_icon.set_tooltip_text("LM Studio Monitor")
        self.status_icon.connect("activate", self.on_click)
        self.status_icon.connect("popup-menu", self.on_right_click)
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

    def on_right_click(self, _icon, button, time):
        """
        Handle right-click event on the system tray icon.

        Args:
            _icon: The tray icon object (unused).
            button: The mouse button that was clicked.
            time: The timestamp of the click event.

        Returns:
            None
        """
        menu = Gtk.Menu()

        open_item = Gtk.MenuItem(label="Start LM Studio Daemon")
        open_item.connect("activate", self.start_daemon)
        menu.append(open_item)

        reload_item = Gtk.MenuItem(label="Reload model")
        reload_item.connect("activate", self.reload_model)
        menu.append(reload_item)

        status_item = Gtk.MenuItem(label="Show status")
        status_item.connect("activate", self.show_status_dialog)
        menu.append(status_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit tray")
        quit_item.connect("activate", self.quit_app)
        menu.append(quit_item)

        menu.show_all()
        menu.popup(None, None, None, None, button, time)

    def start_daemon(self, _widget):
        """Start or ensure the LM Studio daemon is running.

        Looks up the `lms` CLI path, invokes `lms daemon up`, logs success
        or failure, and sends desktop notifications about the outcome.

        Args:
            _widget: UI widget that triggered the action (unused).
        """
        lms_cmd = get_lms_cmd()
        if not lms_cmd:
            logging.error("lms CLI not found")
            subprocess.run(
                [
                    "notify-send",
                    "Error",
                    "lms CLI not found. Run: lms daemon up",
                ],
                check=False,
            )
            return
        try:
            result = subprocess.run(
                [lms_cmd, "daemon", "up"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                logging.info("LM Studio daemon started/ensured")
                subprocess.run(
                    [
                        "notify-send",
                        "LM Studio",
                        "LM Studio daemon is running",
                    ],
                    check=False,
                )
            else:
                err = result.stderr.strip() or "Unknown error"
                logging.error("Failed to start daemon: %s", err)
                subprocess.run(
                    ["notify-send", "Error", f"Daemon start failed: {err}"],
                    check=False,
                )
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            logging.error("Error starting daemon: %s", e)
            subprocess.run(
                ["notify-send", "Error", f"Error: {e}"],
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
            flags=0,
            type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            message_format="LM Studio Status"
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
            lms_cmd = get_lms_cmd()
            if not lms_cmd:
                self.status_icon.set_from_icon_name(ICON_FAIL)
                self.status_icon.set_tooltip_text("❌ lms CLI not found")
                return True
            result = subprocess.run(
                [lms_cmd, "ps"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
                check=False
            )
            current_status = None
            if result.returncode == 0:
                if MODEL in result.stdout:
                    current_status = "OK"
                    self.status_icon.set_from_icon_name(ICON_OK)
                    self.status_icon.set_tooltip_text(
                        f"✅ Model active: {MODEL}"
                    )
                elif result.stdout.strip():
                    current_status = "INFO"
                    lines = result.stdout.strip().split('\n')
                    loaded_models = [
                        line.split()[1] if len(line.split()) > 1 else 'Unknown'
                        for line in lines[1:]
                    ]
                    tooltip = (
                        f"ℹ️ Loaded model changed (expected: {MODEL})\n"
                        f"Loaded: {', '.join(loaded_models[:3])}"
                    )
                    self.status_icon.set_from_icon_name(ICON_INFO)
                    self.status_icon.set_tooltip_text(tooltip)
                else:
                    current_status = "WARN"
                    self.status_icon.set_from_icon_name(ICON_WARN)
                    self.status_icon.set_tooltip_text(
                        f"⚠️ No modell loaded (expected: {MODEL})"
                    )
            else:
                current_status = "FAIL"
                self.status_icon.set_from_icon_name(ICON_FAIL)
                self.status_icon.set_tooltip_text("❌ LM Studio is not running")

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

            self.last_status = current_status

        except subprocess.TimeoutExpired:
            self.status_icon.set_from_icon_name(ICON_WARN)
            self.status_icon.set_tooltip_text("⚠️ Timeout during status check")
            logging.warning("Timeout in lms ps")
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            self.status_icon.set_from_icon_name(ICON_FAIL)
            self.status_icon.set_tooltip_text(f"❌ Error checking: {str(e)}")
            logging.error("Error in status check: %s", e)
        return True


TrayIcon()
Gtk.main()
