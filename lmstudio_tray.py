#!/usr/bin/env python3
import gi
import subprocess
import sys
import os
import signal

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

# === Modellname aus Argument oder Default ===
MODEL = sys.argv[1] if len(sys.argv) > 1 else "kein-modell-übergeben"

# === GTK-Iconnamen aus dem Icon Browser ===
ICON_OK = "emblem-default"         # ✅ Modell aktiv
ICON_FAIL = "emblem-unreadable"    # ❌ Modell nicht geladen
ICON_WARN = "dialog-warning"  # ⚠️ Fehlerstatus

# === Pfad zur lms-CLI ===
LMS_CLI = "/home/robby/.lmstudio/bin/lms"

# === Beende andere Instanzen dieses Skripts ===
def kill_existing_instances():
    result = subprocess.run(["pgrep", "-f", "lmstudio_tray.py"], stdout=subprocess.PIPE, text=True)
    pids = [int(pid) for pid in result.stdout.strip().split("\n") if pid.isdigit()]
    current_pid = os.getpid()
    for pid in pids:
        if pid != current_pid:
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"🧹 Beende alte Instanz: PID {pid}")
            except Exception as e:
                print(f"⚠️ Fehler beim Beenden von PID {pid}: {e}")

kill_existing_instances()

class TrayIcon:
    def __init__(self):
        self.status_icon = Gtk.StatusIcon()
        self.status_icon.set_visible(True)
        self.status_icon.set_tooltip_text("LM Studio Monitor")
        self.status_icon.connect("activate", self.on_click)

        self.check_model()
        GLib.timeout_add_seconds(10, self.check_model)

    def on_click(self, icon):
        subprocess.run(["notify-send", "LM Studio", f"Modellstatus: {MODEL} wird überwacht"])

    def check_model(self):
        try:
            result = subprocess.run([LMS_CLI, "ps"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if MODEL in result.stdout:
                self.status_icon.set_from_icon_name(ICON_OK)
                self.status_icon.set_tooltip_text(f"✅ Modell aktiv: {MODEL}")
            elif result.stderr:
                self.status_icon.set_from_icon_name(ICON_WARN)
                self.status_icon.set_tooltip_text(f"⚠️ Fehler: {result.stderr.strip()}")
            else:
                self.status_icon.set_from_icon_name(ICON_FAIL)
                self.status_icon.set_tooltip_text(f"❌ Modell nicht aktiv: {MODEL}")
        except Exception as e:
            self.status_icon.set_from_icon_name(ICON_WARN)
            self.status_icon.set_tooltip_text(f"⚠️ Ausnahmefehler: {str(e)}")
        return True

TrayIcon()
Gtk.main()

