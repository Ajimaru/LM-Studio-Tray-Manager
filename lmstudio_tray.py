#!/usr/bin/env python3
import gi
import subprocess
import sys
import os
import signal
import logging
import json

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

# === Set up logging ===
logging.basicConfig(
    filename=os.path.join(os.getcwd(), "lmstudio_tray.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filemode='w'
)

# === Model name from argument or default ===
MODEL = sys.argv[1] if len(sys.argv) > 1 else "no-model-passed"
script_dir = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
INTERVAL = 10

config_path = os.path.join(script_dir, "config.json")

try:
    with open(config_path, 'r') as f:
        config = json.load(f)
        appdir = config['appdir']
except:
    logging.error("Configuration config.json not found or invalid. Terminating script.")
    sys.exit(1)

# === GTK icon names from the icon browser ===
ICON_OK = "emblem-default"         # ✅ Model active
ICON_FAIL = "emblem-unreadable"    # ❌ Model not loaded
ICON_WARN = "dialog-warning"       # ⚠️ Error status

# === Path to lms-CLI ===
LMS_CLI = os.path.expanduser("~/.lmstudio/bin/lms")

# === Terminate other instances of this script ===
def kill_existing_instances():
    result = subprocess.run(["pgrep", "-f", "lmstudio_tray.py"], stdout=subprocess.PIPE, text=True)
    pids = [int(pid) for pid in result.stdout.strip().split("\n") if pid.isdigit()]
    current_pid = os.getpid()
    for pid in pids:
        if pid != current_pid:
            try:
                os.kill(pid, signal.SIGTERM)
                logging.info(f"Terminating old instance: PID {pid}")
            except Exception as e:
                logging.warning(f"Error terminating PID {pid}: {e}")

kill_existing_instances()

logging.info("Tray script started")

class TrayIcon:
    def __init__(self):
        self.appdir = appdir
        self.status_icon = Gtk.StatusIcon()
        self.status_icon.set_visible(True)
        self.status_icon.set_tooltip_text("LM Studio Monitor")
        self.status_icon.connect("activate", self.on_click)
        self.status_icon.connect("popup-menu", self.on_right_click)
        self.last_status = None
        self.check_model()
        GLib.timeout_add_seconds(INTERVAL, self.check_model)

    def on_click(self, icon):
        subprocess.run(["notify-send", "LM Studio", f"Model status: {MODEL} is being monitored"])

    def on_right_click(self, icon, button, time):
        menu = Gtk.Menu()

        open_item = Gtk.MenuItem(label="Open LM Studio")
        open_item.connect("activate", self.open_lm_studio)
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

    def start_lm_studio(self):
        appdir = self.appdir
        result = subprocess.run(["find", appdir, "-name", "LM-Studio*.AppImage", "-type", "f"], stdout=subprocess.PIPE, text=True)
        if result.returncode == 0 and result.stdout.strip():
            appimage_path = result.stdout.strip().split('\n')[0]
            logging.info(f"Starting LM Studio AppImage: {appimage_path}")
            proc = subprocess.Popen([appimage_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logging.info("LM Studio AppImage started")
            import time
            time.sleep(3)
            subprocess.run(["notify-send", "LM Studio", "LM Studio started"])
        else:
            logging.warning("No AppImage found")
            subprocess.run(["notify-send", "Error", "LM Studio AppImage not found"])

    def open_lm_studio(self, widget):
        try:
            pgrep_result = subprocess.run(["pgrep", "-f", "LM Studio"], stdout=subprocess.PIPE, text=True)
            if pgrep_result.returncode == 0:
                logging.info("LM Studio is already running")
                subprocess.run(["notify-send", "LM Studio", "LM Studio is already running"])
            else:
                self.start_lm_studio()
        except Exception as e:
            logging.error(f"Error opening LM Studio: {e}")
            subprocess.run(["notify-send", "Error", f"Error: {e}"])

    def reload_model(self, widget):
        if MODEL != "no-model-passed":
            try:
                subprocess.run([LMS_CLI, "load", MODEL], check=False)
                logging.info(f"Model reloaded: {MODEL}")
                subprocess.run(["notify-send", "LM Studio", f"Model {MODEL} is being reloaded"])
            except Exception as e:
                logging.error(f"Error reloading model: {e}")
                subprocess.run(["notify-send", "Error", f"Model could not be reloaded: {e}"])
        else:
            subprocess.run(["notify-send", "Info", "No model specified for reloading"])

    def quit_app(self, widget):
        logging.info("Tray icon terminated")
        Gtk.main_quit()

    def show_status_dialog(self, widget):
        try:
            result = subprocess.run([LMS_CLI, "ps"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                text = result.stdout.strip()
            else:
                text = "No models loaded or error."
        except Exception as e:
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
        try:
            result = subprocess.run([LMS_CLI, "ps"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            current_status = None
            if result.returncode == 0:
                if MODEL in result.stdout:
                    current_status = "OK"
                    self.status_icon.set_from_icon_name(ICON_OK)
                    self.status_icon.set_tooltip_text(f"✅ Model active: {MODEL}")
                else:
                    current_status = "WARN"
                    lines = result.stdout.strip().split('\n')
                    if len(lines) > 1:
                        loaded_models = [line.split()[1] if len(line.split()) > 1 else 'Unknown' for line in lines[1:]]
                        tooltip = f"⚠️ Different/no model loaded (expected: {MODEL})\nLoaded: {', '.join(loaded_models[:3])}"
                    else:
                        tooltip = f"⚠️ Different/no model loaded (expected: {MODEL})"
                    self.status_icon.set_from_icon_name(ICON_WARN)
                    self.status_icon.set_tooltip_text(tooltip)
            else:
                current_status = "FAIL"
                self.status_icon.set_from_icon_name(ICON_FAIL)
                self.status_icon.set_tooltip_text("❌ LM Studio is not running")

            if self.last_status != current_status and self.last_status is not None:
                if current_status == "OK":
                    subprocess.run(["notify-send", "LM Studio", f"✅ Model {MODEL} is now active"])
                elif current_status == "WARN":
                    subprocess.run(["notify-send", "LM Studio", f"⚠️ Model {MODEL} no longer active"])
                elif current_status == "FAIL":
                    subprocess.run(["notify-send", "LM Studio", "❌ LM Studio has stopped"])
                logging.info(f"Status change: {self.last_status} -> {current_status}")

            self.last_status = current_status

        except subprocess.TimeoutExpired:
            self.status_icon.set_from_icon_name(ICON_WARN)
            self.status_icon.set_tooltip_text("⚠️ Timeout during status check")
            logging.warning("Timeout in lms ps")
        except Exception as e:
            self.status_icon.set_from_icon_name(ICON_FAIL)
            self.status_icon.set_tooltip_text(f"❌ Error checking: {str(e)}")
            logging.error(f"Error in status check: {e}")
        return True

TrayIcon()
Gtk.main()

