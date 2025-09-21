#!/usr/bin/env python3
import gi
import subprocess
import sys
import os
import signal
import logging
import json
from datetime import datetime

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

# === Logging einrichten ===
logging.basicConfig(
    filename=os.path.join(os.getcwd(), "lmstudio_tray.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filemode='w'
)

# === Modellname aus Argument oder Default ===
MODEL = sys.argv[1] if len(sys.argv) > 1 else "kein-modell-übergeben"
script_dir = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
INTERVAL = 10

config_path = os.path.join(script_dir, "config.json")

try:
    with open(config_path, 'r') as f:
        config = json.load(f)
        appdir = config['appdir']
except:
    logging.error("Konfiguration config.json nicht gefunden oder ungültig. Skript beenden.")
    sys.exit(1)

# === GTK-Iconnamen aus dem Icon Browser ===
ICON_OK = "emblem-default"         # ✅ Modell aktiv
ICON_FAIL = "emblem-unreadable"    # ❌ Modell nicht geladen
ICON_WARN = "dialog-warning"       # ⚠️ Fehlerstatus

# === Pfad zur lms-CLI ===
LMS_CLI = os.path.expanduser("~/.lmstudio/bin/lms")

# === Beende andere Instanzen dieses Skripts ===
def kill_existing_instances():
    result = subprocess.run(["pgrep", "-f", "lmstudio_tray.py"], stdout=subprocess.PIPE, text=True)
    pids = [int(pid) for pid in result.stdout.strip().split("\n") if pid.isdigit()]
    current_pid = os.getpid()
    for pid in pids:
        if pid != current_pid:
            try:
                os.kill(pid, signal.SIGTERM)
                logging.info(f"Beende alte Instanz: PID {pid}")
            except Exception as e:
                logging.warning(f"Fehler beim Beenden von PID {pid}: {e}")

kill_existing_instances()

logging.info("Tray-Skript gestartet")

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
        subprocess.run(["notify-send", "LM Studio", f"Modellstatus: {MODEL} wird überwacht"])

    def on_right_click(self, icon, button, time):
        menu = Gtk.Menu()

        open_item = Gtk.MenuItem(label="LM Studio öffnen")
        open_item.connect("activate", self.open_lm_studio)
        menu.append(open_item)

        reload_item = Gtk.MenuItem(label="Modell neu laden")
        reload_item.connect("activate", self.reload_model)
        menu.append(reload_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Tray beenden")
        quit_item.connect("activate", self.quit_app)
        menu.append(quit_item)

        menu.show_all()
        menu.popup(None, None, None, None, button, time)

    def start_lm_studio(self):
        appdir = self.appdir
        result = subprocess.run(["find", appdir, "-name", "LM-Studio*.AppImage", "-type", "f"], stdout=subprocess.PIPE, text=True)
        if result.returncode == 0 and result.stdout.strip():
            appimage_path = result.stdout.strip().split('\n')[0]
            logging.info(f"Starte LM Studio AppImage: {appimage_path}")
            proc = subprocess.Popen([appimage_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logging.info("LM Studio AppImage gestartet")
            import time
            time.sleep(3)
            subprocess.run(["notify-send", "LM Studio", "LM Studio gestartet"])
        else:
            logging.warning("Keine AppImage gefunden")
            subprocess.run(["notify-send", "Fehler", "LM Studio AppImage nicht gefunden"])

    def open_lm_studio(self, widget):
        try:
            pgrep_result = subprocess.run(["pgrep", "-f", "LM Studio"], stdout=subprocess.PIPE, text=True)
            if pgrep_result.returncode == 0:
                logging.info("LM Studio läuft bereits")
                subprocess.run(["notify-send", "LM Studio", "LM Studio läuft schon"])
            else:
                self.start_lm_studio()
        except Exception as e:
            logging.error(f"Fehler beim Öffnen von LM Studio: {e}")
            subprocess.run(["notify-send", "Fehler", f"Fehler: {e}"])

    def reload_model(self, widget):
        if MODEL != "kein-modell-übergeben":
            try:
                subprocess.run([LMS_CLI, "load", MODEL], check=False)
                logging.info(f"Modell neu geladen: {MODEL}")
                subprocess.run(["notify-send", "LM Studio", f"Modell {MODEL} wird neu geladen"])
            except Exception as e:
                logging.error(f"Fehler beim Neuladen des Modells: {e}")
                subprocess.run(["notify-send", "Fehler", f"Modell konnte nicht neu geladen werden: {e}"])
        else:
            subprocess.run(["notify-send", "Info", "Kein Modell zum Neuladen angegeben"])

    def quit_app(self, widget):
        logging.info("Tray-Icon beendet")
        Gtk.main_quit()

    def check_model(self):
        try:
            result = subprocess.run([LMS_CLI, "ps"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            current_status = None
            if result.returncode == 0:
                if MODEL in result.stdout:
                    current_status = "OK"
                    self.status_icon.set_from_icon_name(ICON_OK)
                    self.status_icon.set_tooltip_text(f"✅ Modell aktiv: {MODEL}")
                else:
                    current_status = "WARN"
                    lines = result.stdout.strip().split('\n')
                    if len(lines) > 1:
                        loaded_models = [line.split()[1] if len(line.split()) > 1 else 'Unbekannt' for line in lines[1:]]
                        tooltip = f"⚠️ Anderes/kein Modell geladen (erwartet: {MODEL})\nGeladen: {', '.join(loaded_models[:3])}"
                    else:
                        tooltip = f"⚠️ Anderes/kein Modell geladen (erwartet: {MODEL})"
                    self.status_icon.set_from_icon_name(ICON_WARN)
                    self.status_icon.set_tooltip_text(tooltip)
            else:
                current_status = "FAIL"
                self.status_icon.set_from_icon_name(ICON_FAIL)
                self.status_icon.set_tooltip_text("❌ LM Studio läuft nicht")

            if self.last_status != current_status and self.last_status is not None:
                if current_status == "OK":
                    subprocess.run(["notify-send", "LM Studio", f"✅ Modell {MODEL} ist jetzt aktiv"])
                elif current_status == "WARN":
                    subprocess.run(["notify-send", "LM Studio", f"⚠️ Modell {MODEL} nicht mehr aktiv"])
                elif current_status == "FAIL":
                    subprocess.run(["notify-send", "LM Studio", "❌ LM Studio ist gestoppt"])
                logging.info(f"Statusänderung: {self.last_status} -> {current_status}")

            self.last_status = current_status

        except subprocess.TimeoutExpired:
            self.status_icon.set_from_icon_name(ICON_WARN)
            self.status_icon.set_tooltip_text("⚠️ Timeout bei Statusprüfung")
            logging.warning("Timeout bei lms ps")
        except Exception as e:
            self.status_icon.set_from_icon_name(ICON_FAIL)
            self.status_icon.set_tooltip_text(f"❌ Fehler beim Prüfen: {str(e)}")
            logging.error(f"Fehler bei Statusprüfung: {e}")
        return True

TrayIcon()
Gtk.main()

