"""
Test suite for lmstudio_tray.py system tray application.

This module contains comprehensive tests for the LM Studio system tray
application, including tests for:
- Daemon management (start/stop)
- Desktop application lifecycle
- Status monitoring and indicators
- Menu building and interaction
- Command resolution and execution
- Error handling and edge cases

The tests use mocked GTK, AppIndicator, and GLib components to avoid requiring
a display server or actual system dependencies during test execution.
"""

import importlib.util
import os
import signal
import subprocess  # nosec B404 - subprocess module is mocked in tests
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


class DummyMenu:
    """Dummy menu used by tests."""

    def __init__(self):
        """Initialize an in-memory list of menu items."""
        self.items = []

    def get_children(self):
        """Return current child items as a copy."""
        return list(self.items)

    def remove(self, item):
        """Remove a menu item from the container."""
        self.items.remove(item)

    def append(self, item):
        """Append a menu item to the container."""
        self.items.append(item)

    def show_all(self):
        """Mimic GTK's show_all call."""
        return None


class DummyMenuItem:
    """Dummy menu item used by tests."""

    def __init__(self, label=""):
        """Create a dummy menu item with label and callbacks."""
        self.label = label
        self.sensitive = True
        self.connected = []

    def set_sensitive(self, value):
        """Set whether the item is interactive."""
        self.sensitive = value

    def connect(self, event, callback):
        """Store a signal connection tuple."""
        self.connected.append((event, callback))


class DummySeparatorMenuItem(DummyMenuItem):
    """A dummy separator menu item for testing purposes.

    It serves as a visual divider between menu items.
    """


class DummyMessageDialog:
    """Dummy message dialog to capture interactions."""
    last_instance = None

    def __init__(
        self,
        parent=None,
        flags=None,
        message_type=None,
        buttons=None,
        text="",
    ):
        """Initialize a lightweight message dialog stub."""
        self.parent = parent
        self.flags = flags
        self.message_type = message_type
        self.buttons = buttons
        self.text = text
        self.secondary = ""
        self.ran = False
        self.destroyed = False
        DummyMessageDialog.last_instance = self

    def format_secondary_text(self, text):
        """Store secondary dialog text."""
        self.secondary = text

    def run(self):
        """Mark the dialog as shown."""
        self.ran = True

    def destroy(self):
        """Mark the dialog as destroyed."""
        self.destroyed = True


class DummyIndicator:
    """Dummy indicator capturing status and menu updates."""

    def __init__(self):
        """Create a dummy indicator object for assertions."""
        self.status = None
        self.title = None
        self.menu = None
        self.icon_calls = []

    def set_status(self, status):
        """Persist indicator status value."""
        self.status = status

    def set_title(self, title):
        """Persist indicator title value."""
        self.title = title

    def set_menu(self, menu):
        """Persist menu reference."""
        self.menu = menu

    def set_icon_full(self, icon, text):
        """Record icon updates for later verification."""
        self.icon_calls.append((icon, text))


class DummyAppIndicatorModule(ModuleType):
    """Mock AppIndicator3 module for testing purposes."""
    class IndicatorCategory:
        """Enumeration-like class for indicator category constants.

        This class provides constant values for different indicator categories
        used in the application status system.

        Attributes:
            APPLICATION_STATUS (int): Application status category constant.
        """
        APPLICATION_STATUS = 1

    class IndicatorStatus:
        """Enumeration class for indicator status values.

        Attributes:
            ACTIVE (int): Status code indicating the indicator is active.
        """
        ACTIVE = 1

    class Indicator:
        """
        Dummy Indicator class for testing purposes.

        This class provides a static factory method to create
        DummyIndicator instances for tests.
        """
        @staticmethod
        def new(_app_id, _icon, _category):
            """Return a dummy indicator instance."""
            return DummyIndicator()


class DummyGtkModule(ModuleType):
    """
    Mock GTK module for testing purposes.

    This class simulates GTK so tests can run without a display server.
    """
    class DialogFlags:
        """
        Enumeration of dialog window flags.

        This class defines constants for dialog window behavior flags,
        specifically for modal dialog configuration.

        Attributes:
            MODAL (int): Flag indicating the dialog should be modal (value: 1).
                It blocks interaction with other windows until closed.
        """
        MODAL = 1

    class MessageType:
        """Enumeration of message types for system tray notifications.

        Attributes:
            INFO: Integer constant for informational message type.
        """
        INFO = 1

    class ButtonsType:
        """
        Enumeration of button types for message dialogs.

        Attributes:
            OK (int): Represents an OK button with value 1.
        """
        OK = 1

    Menu = DummyMenu
    MenuItem = DummyMenuItem
    SeparatorMenuItem = DummySeparatorMenuItem
    MessageDialog = DummyMessageDialog

    @staticmethod
    def main_quit():
        """Stub GTK main_quit."""
        return None

    @staticmethod
    def main():
        """Stub GTK main loop entry."""
        return None


class DummyGLibModule(ModuleType):
    """
    A dummy GLib module for testing purposes.

    This class provides stub implementations of GLib functions to allow
    testing without requiring the actual GLib library. It mimics the behavior
    of the GLib module by providing minimal implementations that return
    successful responses.
    """
    @staticmethod
    def timeout_add_seconds(_seconds, _callback):
        """Stub timer registration and report success."""
        return True


def _completed(returncode=0, stdout="", stderr=""):
    """Create a subprocess-like completed result object."""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(name="tray_module")
def tray_module_fixture(monkeypatch, tmp_path):
    """Import lmstudio_tray with mocked GI/GTK dependencies."""
    gi_mod = ModuleType("gi")
    setattr(gi_mod, "require_version", lambda *_args, **_kwargs: None)

    gtk_mod = DummyGtkModule("gi.repository.Gtk")
    glib_mod = DummyGLibModule("gi.repository.GLib")
    app_mod = DummyAppIndicatorModule("gi.repository.AyatanaAppIndicator3")

    monkeypatch.setitem(sys.modules, "gi", gi_mod)
    monkeypatch.setitem(
        sys.modules,
        "gi.repository",
        ModuleType("gi.repository"),
    )
    monkeypatch.setitem(sys.modules, "gi.repository.Gtk", gtk_mod)
    monkeypatch.setitem(sys.modules, "gi.repository.GLib", glib_mod)
    monkeypatch.setitem(
        sys.modules,
        "gi.repository.AyatanaAppIndicator3",
        app_mod,
    )

    original_import_module = importlib.import_module

    def fake_import_module(name):
        """Resolve mocked GI modules during import."""
        if name == "gi.repository.Gtk":
            return gtk_mod
        if name == "gi.repository.GLib":
            return glib_mod
        if name == "gi.repository.AyatanaAppIndicator3":
            return app_mod
        return original_import_module(name)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    def safe_run(_args, **_kwargs):
        """Return a safe default subprocess result during import."""
        return _completed(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", safe_run)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(os, "getpid", lambda: 99999)

    module_name = "lmstudio_tray"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name,
        str(Path(__file__).resolve().parents[1] / "lmstudio_tray.py"),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to create module spec or loader")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _make_tray_instance(module):
    """Build a partially initialized TrayIcon for unit tests."""
    tray = module.TrayIcon.__new__(module.TrayIcon)
    tray.indicator = DummyIndicator()
    tray.menu = DummyMenu()
    tray.last_status = None
    tray.action_lock_until = 0.0
    tray.build_menu = lambda: None
    return tray


def _call_member(instance, member_name, *args, **kwargs):
    """Call a member by name to avoid direct protected-member access."""
    member = getattr(instance, member_name)
    return member(*args, **kwargs)


def test_get_app_version_reads_file(tray_module, tmp_path, monkeypatch):
    """Read version string from a VERSION file."""
    monkeypatch.setattr(tray_module, "script_dir", str(tmp_path))
    (tmp_path / "VERSION").write_text("v1.2.3\n", encoding="utf-8")
    version = tray_module.get_app_version()
    if version != "v1.2.3":
        pytest.fail(f"Expected version 'v1.2.3' but got '{version}'")


def test_get_app_version_fallback_default(tray_module, tmp_path, monkeypatch):
    """Fall back to default version when file is absent."""
    monkeypatch.setattr(tray_module, "script_dir", str(tmp_path))
    assert (
        tray_module.get_app_version()
        == tray_module.DEFAULT_APP_VERSION
    )  # nosec B101


def test_get_lms_cmd_prefers_lms_cli(tray_module, monkeypatch):
    """Prefer bundled LMS_CLI path when executable."""
    monkeypatch.setattr(tray_module.os.path, "isfile", lambda _p: True)
    monkeypatch.setattr(tray_module.os, "access", lambda _p, _m: True)
    assert tray_module.get_lms_cmd() == tray_module.LMS_CLI  # nosec B101


def test_get_lms_cmd_fallback_to_which(tray_module, monkeypatch):
    """Resolve lms command from PATH when bundled binary is unavailable."""
    monkeypatch.setattr(tray_module.os.path, "isfile", lambda _p: False)
    monkeypatch.setattr(tray_module.shutil, "which", lambda _x: "/usr/bin/lms")
    assert tray_module.get_lms_cmd() == "/usr/bin/lms"  # nosec B101


def test_get_llmster_cmd_from_which(tray_module, monkeypatch):
    """Return llmster executable found on PATH."""
    monkeypatch.setattr(
        tray_module.shutil,
        "which",
        lambda _x: "/usr/bin/llmster",
    )
    assert tray_module.get_llmster_cmd() == "/usr/bin/llmster"  # nosec B101


def test_get_llmster_cmd_from_directory_scan(tray_module, monkeypatch):
    """Pick latest discovered llmster binary from install directories."""
    monkeypatch.setattr(tray_module.shutil, "which", lambda _x: None)
    monkeypatch.setattr(tray_module.os.path, "isdir", lambda _p: True)
    monkeypatch.setattr(tray_module.os, "listdir", lambda _p: ["a", "b"])

    def fake_isfile(path):
        """Match synthetic llmster binary candidates."""
        return path.endswith("/a/llmster") or path.endswith("/b/llmster")

    monkeypatch.setattr(tray_module.os.path, "isfile", fake_isfile)
    monkeypatch.setattr(tray_module.os, "access", lambda _p, _m: True)
    assert tray_module.get_llmster_cmd().endswith("/b/llmster")  # nosec B101


def test_is_llmster_running_true_first_check(tray_module, monkeypatch):
    """Report running when first pgrep call succeeds."""
    calls = []

    def fake_run(args, **_kwargs):
        """Track command usage and emulate successful process probe."""
        calls.append(args)
        return _completed(returncode=0)

    monkeypatch.setattr(tray_module.subprocess, "run", fake_run)
    assert tray_module.is_llmster_running() is True  # nosec B101
    assert calls[0][:2] == ["pgrep", "-x"]  # nosec B101


def test_is_llmster_running_true_second_check(tray_module, monkeypatch):
    """Report running when second fallback pgrep succeeds."""
    sequence = [
        _completed(returncode=1),
        _completed(returncode=0),
    ]

    def fake_run(_args, **_kwargs):
        """Return predetermined probe results."""
        return sequence.pop(0)

    monkeypatch.setattr(tray_module.subprocess, "run", fake_run)
    assert tray_module.is_llmster_running() is True  # nosec B101


def test_get_desktop_app_pids_parsing(tray_module, monkeypatch):
    """Parse desktop app root process IDs from ps output."""
    output = (
        "123 /opt/LM Studio/lm-studio\n"
        "234 lm-studio\n"
        "345 /usr/bin/lm-studio --type=renderer\n"
    )

    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0, stdout=output),
    )
    assert tray_module.get_desktop_app_pids() == [123, 234]  # nosec B101


def test_kill_existing_instances_ignores_current_pid(tray_module, monkeypatch):
    """Terminate only stale tray process IDs."""
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0, stdout="10\n20\n"),
    )
    monkeypatch.setattr(tray_module.os, "getpid", lambda: 20)
    killed = []
    monkeypatch.setattr(
        tray_module.os,
        "kill",
        lambda pid, sig: killed.append((pid, sig)),
    )
    tray_module.kill_existing_instances()
    assert killed == [(10, signal.SIGTERM)]  # nosec B101


def test_begin_action_cooldown(tray_module, monkeypatch):
    """Throttle repeated actions within cooldown window."""
    tray = _make_tray_instance(tray_module)
    times = [100.0, 100.5, 103.0]
    monkeypatch.setattr(tray_module.time, "monotonic", lambda: times.pop(0))
    assert tray.begin_action_cooldown("x", seconds=2.0) is True  # nosec B101
    assert tray.begin_action_cooldown("x", seconds=2.0) is False  # nosec B101
    assert tray.begin_action_cooldown("x", seconds=2.0) is True  # nosec B101


def test_get_status_indicator(tray_module):
    """Map status strings to indicator symbols."""
    tray = _make_tray_instance(tray_module)
    assert tray.get_status_indicator("running") == "🟢"  # nosec B101
    assert tray.get_status_indicator("stopped") == "🟡"  # nosec B101
    assert tray.get_status_indicator("not_found") == "🔴"  # nosec B101


def test_build_daemon_attempts_start_and_stop(tray_module, monkeypatch):
    """Build expected daemon start and stop command variants."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        tray_module,
        "get_llmster_cmd",
        lambda: "/usr/bin/llmster",
    )
    start = _call_member(tray, "_build_daemon_attempts", "start")
    stop = _call_member(tray, "_build_daemon_attempts", "stop")
    assert ["/usr/bin/lms", "daemon", "up"] in start  # nosec B101
    assert ["/usr/bin/llmster", "daemon", "down"] in stop  # nosec B101


def test_run_daemon_attempts_stops_on_condition(tray_module, monkeypatch):
    """Stop command iteration once stop condition is met."""
    tray = _make_tray_instance(tray_module)
    called = []

    def fake_run(args, **_kwargs):
        """Collect called commands and emulate success."""
        called.append(args)
        return _completed(returncode=0)

    monkeypatch.setattr(tray_module.subprocess, "run", fake_run)
    result = _call_member(
        tray,
        "_run_daemon_attempts",
        [["a"], ["b"]],
        lambda _r: True,
    )
    assert result.returncode == 0  # nosec B101
    assert called == [["a"]]  # nosec B101


def test_stop_llmster_best_effort_with_force(tray_module, monkeypatch):
    """Force-stop llmster when graceful stop does not finish."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "_build_daemon_attempts", lambda _x: [["cmd"]])
    monkeypatch.setattr(
        tray,
        "_run_daemon_attempts",
        lambda _a, _c: _completed(returncode=1),
    )
    running = [True, False]
    monkeypatch.setattr(
        tray_module,
        "is_llmster_running",
        lambda: running.pop(0),
    )
    forced = {"called": 0}
    monkeypatch.setattr(
        tray,
        "_force_stop_llmster",
        lambda: forced.__setitem__("called", 1),
    )
    stopped, _result = _call_member(tray, "_stop_llmster_best_effort")
    assert stopped is True  # nosec B101
    assert forced["called"] == 1  # nosec B101


def test_stop_desktop_app_processes_success(tray_module, monkeypatch):
    """Stop desktop app processes using SIGTERM path."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_desktop_app_pids", lambda: [11, 12])
    statuses = ["running", "stopped", "stopped", "stopped"]
    monkeypatch.setattr(
        tray,
        "get_desktop_app_status",
        lambda: statuses.pop(0),
    )
    killed = []
    monkeypatch.setattr(
        tray_module.os,
        "kill",
        lambda pid, sig: killed.append((pid, sig)),
    )
    monkeypatch.setattr(tray_module.time, "sleep", lambda _x: None)
    result = _call_member(tray, "_stop_desktop_app_processes")
    assert result is True  # nosec B101
    assert (11, signal.SIGTERM) in killed  # nosec B101


def test_start_daemon_missing_binaries_notifies(tray_module, monkeypatch):
    """Notify user when daemon binaries are unavailable."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(tray, "_build_daemon_attempts", lambda _x: [])
    calls = []
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(args) or _completed(returncode=0),
    )
    tray.start_daemon(None)
    assert any("notify-send" in c for c in calls)  # nosec B101


def test_stop_daemon_success_path(tray_module, monkeypatch):
    """Notify user when daemon stop succeeds."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray, "_build_daemon_attempts", lambda _x: [["cmd"]])
    monkeypatch.setattr(
        tray,
        "_stop_llmster_best_effort",
        lambda: (True, _completed(returncode=0)),
    )
    monkeypatch.setattr(
        tray_module.GLib,
        "timeout_add_seconds",
        lambda *_a, **_k: True,
    )
    calls = []
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(args) or _completed(returncode=0),
    )
    tray.stop_daemon(None)
    assert any("notify-send" in c for c in calls)  # nosec B101


def test_start_desktop_app_missing_lms(tray_module, monkeypatch):
    """Notify user when lms CLI is missing."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: None)
    calls = []
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(args) or _completed(returncode=0),
    )
    tray.start_desktop_app(None)
    assert any("notify-send" in c for c in calls)  # nosec B101


def test_start_desktop_app_appimage_found_and_started(
    tray_module,
    monkeypatch,
    tmp_path,
):
    """Launch desktop app when AppImage is discovered."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(tray_module, "is_llmster_running", lambda: False)

    app_dir = tmp_path / "Apps"
    app_dir.mkdir()
    app_file = app_dir / "LM-Studio.AppImage"
    app_file.write_text("bin", encoding="utf-8")

    monkeypatch.setattr(tray_module.sys, "argv", ["x", "model", str(app_dir)])

    def fake_run(args, **_kwargs):
        """Return dpkg miss and generic success for other commands."""
        if args[:2] == ["dpkg", "-l"]:
            return _completed(returncode=0, stdout="")
        return _completed(returncode=0)

    monkeypatch.setattr(tray_module.subprocess, "run", fake_run)
    popen_calls = []
    monkeypatch.setattr(
        tray_module.subprocess,
        "Popen",
        lambda args, **_kwargs: popen_calls.append(args) or SimpleNamespace(),
    )
    monkeypatch.setattr(
        tray_module.os.path,
        "isdir",
        lambda p: p == str(app_dir),
    )
    monkeypatch.setattr(
        tray_module.os,
        "listdir",
        lambda _p: ["LM-Studio.AppImage"],
    )
    monkeypatch.setattr(
        tray_module.GLib,
        "timeout_add_seconds",
        lambda *_a, **_k: True,
    )

    tray.start_desktop_app(None)
    assert popen_calls  # nosec B101


def test_stop_desktop_app_no_process_path(tray_module, monkeypatch):
    """Handle desktop stop request when no process is running."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=1),
    )
    monkeypatch.setattr(
        tray_module.GLib,
        "timeout_add_seconds",
        lambda *_a, **_k: True,
    )
    tray.stop_desktop_app(None)


def test_show_status_dialog_success(tray_module, monkeypatch):
    """Render status dialog with lms output."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0, stdout="modelA"),
    )
    tray.show_status_dialog(None)
    dialog = tray_module.Gtk.MessageDialog.last_instance
    assert dialog.text == "LM Studio Status"  # nosec B101
    assert "modelA" in dialog.secondary  # nosec B101
    assert dialog.ran is True  # nosec B101
    assert dialog.destroyed is True  # nosec B101


def test_show_about_dialog_contains_version_and_repo(tray_module, monkeypatch):
    """Show about dialog including version and repository metadata."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "APP_VERSION", "v2.0.0")
    tray.show_about_dialog(None)
    dialog = tray_module.Gtk.MessageDialog.last_instance
    assert "v2.0.0" in dialog.secondary  # nosec B101
    assert "Repository:" in dialog.secondary  # nosec B101


def test_check_model_fail_warn_info_ok(tray_module, monkeypatch):
    """Cover FAIL/WARN/INFO/OK icon and transition handling."""
    tray = _make_tray_instance(tray_module)
    notify_calls = []
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda args, **_kwargs: notify_calls.append(args)
        or _completed(returncode=0, stdout="modelX"),
    )

    # FAIL
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "not_found")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "not_found")
    tray.last_status = None
    assert tray.check_model() is True  # nosec B101

    # WARN transition
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "stopped")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    assert tray.check_model() is True  # nosec B101

    # INFO transition
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: None)
    assert tray.check_model() is True  # nosec B101

    # OK transition
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0, stdout="loaded"),
    )
    assert tray.check_model() is True  # nosec B101


def test_build_menu_running_entries(tray_module, monkeypatch):
    """Build menu entries for running daemon and desktop app."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "running")
    tray_module.TrayIcon.build_menu(tray)
    labels = [getattr(i, "label", "") for i in tray.menu.get_children()]
    assert any("Daemon (Running)" in label for label in labels)  # nosec B101
    assert any(
        "Desktop App (Running)" in label for label in labels
    )  # nosec B101


def test_build_menu_not_found_entries(tray_module, monkeypatch):
    """Build menu entries for missing daemon and desktop app."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "not_found")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "not_found")
    tray_module.TrayIcon.build_menu(tray)
    labels = [getattr(i, "label", "") for i in tray.menu.get_children()]
    assert any(
        "Daemon (Not Installed)" in label for label in labels
    )  # nosec B101
    assert any(
        "Desktop App (Not Installed)" in label for label in labels
    )  # nosec B101


def test_get_daemon_status_variants(tray_module, monkeypatch):
    """Return daemon status for missing, running, and stopped cases."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_llmster_cmd", lambda: None)
    assert tray.get_daemon_status() == "not_found"  # nosec B101

    monkeypatch.setattr(
        tray_module,
        "get_llmster_cmd",
        lambda: "/usr/bin/llmster",
    )
    monkeypatch.setattr(tray_module, "is_llmster_running", lambda: True)
    assert tray.get_daemon_status() == "running"  # nosec B101

    monkeypatch.setattr(tray_module, "is_llmster_running", lambda: False)
    assert tray.get_daemon_status() == "stopped"  # nosec B101


def test_get_desktop_app_status_variants(tray_module, monkeypatch, tmp_path):
    """Return desktop app status for running and installed variants."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_desktop_app_pids", lambda: [1])
    assert tray.get_desktop_app_status() == "running"  # nosec B101

    monkeypatch.setattr(tray_module, "get_desktop_app_pids", lambda: [])
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0, stdout="lm-studio"),
    )
    assert tray.get_desktop_app_status() == "stopped"  # nosec B101

    app_dir = tmp_path / "Apps"
    app_dir.mkdir()
    (app_dir / "LM-Studio.AppImage").write_text("x", encoding="utf-8")
    monkeypatch.setattr(tray_module.sys, "argv", ["x", "m", str(app_dir)])
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0, stdout=""),
    )
    monkeypatch.setattr(
        tray_module.os.path,
        "isdir",
        lambda p: p == str(app_dir),
    )
    monkeypatch.setattr(
        tray_module.os,
        "listdir",
        lambda _p: ["LM-Studio.AppImage"],
    )
    assert tray.get_desktop_app_status() == "stopped"  # nosec B101


def test_force_stop_llmster(tray_module, monkeypatch):
    """Issue force-stop commands for llmster."""
    tray = _make_tray_instance(tray_module)
    calls = []
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(args) or _completed(returncode=0),
    )
    running = [True, False]
    monkeypatch.setattr(
        tray_module,
        "is_llmster_running",
        lambda: running.pop(0),
    )
    monkeypatch.setattr(tray_module.time, "sleep", lambda _x: None)
    _call_member(tray, "_force_stop_llmster")
    assert ["pkill", "-x", "llmster"] in calls  # nosec B101
    assert ["pkill", "-f", "llmster"] in calls  # nosec B101


def test_stop_desktop_app_processes_force_kill_path(tray_module, monkeypatch):
    """Escalate to SIGKILL when desktop app ignores SIGTERM."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_desktop_app_pids", lambda: [10])
    status_seq = ["running"] * 9 + ["stopped", "stopped"]
    monkeypatch.setattr(
        tray,
        "get_desktop_app_status",
        lambda: status_seq.pop(0),
    )
    killed = []
    monkeypatch.setattr(
        tray_module.os,
        "kill",
        lambda pid, sig: killed.append((pid, sig)),
    )
    monkeypatch.setattr(tray_module.time, "sleep", lambda _x: None)
    result = _call_member(tray, "_stop_desktop_app_processes")
    assert result is True  # nosec B101
    assert any(sig == signal.SIGKILL for _pid, sig in killed)  # nosec B101


def test_start_daemon_success_after_stopping_app(tray_module, monkeypatch):
    """Start daemon successfully after stopping desktop app."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    status = ["running", "stopped"]
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: status.pop(0))
    monkeypatch.setattr(tray, "_stop_desktop_app_processes", lambda: True)
    monkeypatch.setattr(tray, "_build_daemon_attempts", lambda _x: [["cmd"]])
    monkeypatch.setattr(
        tray,
        "_run_daemon_attempts",
        lambda _a, _c: _completed(returncode=0),
    )
    monkeypatch.setattr(tray_module, "is_llmster_running", lambda: True)
    monkeypatch.setattr(
        tray_module.GLib,
        "timeout_add_seconds",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0),
    )
    tray.start_daemon(None)


def test_start_daemon_exception_path(tray_module, monkeypatch):
    """Handle unexpected exception while starting daemon."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(tray, "_build_daemon_attempts", lambda _x: [["cmd"]])
    monkeypatch.setattr(
        tray,
        "_run_daemon_attempts",
        lambda _a, _c: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0),
    )
    tray.start_daemon(None)


def test_stop_daemon_failure_detail_path(tray_module, monkeypatch):
    """Include subprocess detail when daemon stop fails."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray, "_build_daemon_attempts", lambda _x: [["cmd"]])
    monkeypatch.setattr(
        tray,
        "_stop_llmster_best_effort",
        lambda: (False, _completed(returncode=1, stderr="still running")),
    )
    monkeypatch.setattr(
        tray_module.GLib,
        "timeout_add_seconds",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0),
    )
    tray.stop_daemon(None)


def test_stop_daemon_exception_path(tray_module, monkeypatch):
    """Handle unexpected exception while stopping daemon."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray, "_build_daemon_attempts", lambda _x: [["cmd"]])
    monkeypatch.setattr(
        tray,
        "_stop_llmster_best_effort",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0),
    )
    tray.stop_daemon(None)


def test_start_desktop_app_daemon_stop_fails(tray_module, monkeypatch):
    """Abort desktop start when daemon cannot be stopped."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(tray_module, "is_llmster_running", lambda: True)
    monkeypatch.setattr(
        tray,
        "_stop_llmster_best_effort",
        lambda: (False, _completed(returncode=1)),
    )
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0),
    )
    tray.start_desktop_app(None)


def test_start_desktop_app_not_found_path(tray_module, monkeypatch):
    """Notify user when no desktop installation is found."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(tray_module, "is_llmster_running", lambda: False)
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda args, **_kwargs: _completed(returncode=0, stdout="")
        if args[:2] == ["dpkg", "-l"]
        else _completed(returncode=0),
    )
    monkeypatch.setattr(tray_module.os.path, "isdir", lambda _p: False)
    tray.start_desktop_app(None)


def test_start_desktop_app_popen_failure(tray_module, monkeypatch):
    """Handle Popen failure when launching desktop app."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(tray_module, "is_llmster_running", lambda: False)
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0, stdout="lm-studio"),
    )
    monkeypatch.setattr(
        tray_module.subprocess,
        "Popen",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("fail")),
    )
    tray.start_desktop_app(None)


def test_stop_desktop_app_exception_path(tray_module, monkeypatch):
    """Handle exception while stopping desktop app."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    calls = {"count": 0}

    def flaky_run(*_args, **_kwargs):
        """Fail once, then succeed to allow notify fallback."""
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("fail")
        return _completed(returncode=0)

    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        flaky_run,
    )
    tray.stop_desktop_app(None)


def test_show_status_dialog_error_path(tray_module, monkeypatch):
    """Render status dialog with an error message when lms is missing."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: None)
    tray.show_status_dialog(None)
    dialog = tray_module.Gtk.MessageDialog.last_instance
    assert "Error retrieving status" in dialog.secondary  # nosec B101


def test_check_model_timeout_and_exception_paths(tray_module, monkeypatch):
    """Keep check_model stable on timeout and subprocess errors."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")

    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: (
            _ for _ in ()
        ).throw(subprocess.TimeoutExpired("cmd", 1)),
    )
    assert tray.check_model() is True  # nosec B101

    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")),
    )
    assert tray.check_model() is True  # nosec B101


def test_start_daemon_fails_when_desktop_cannot_stop(tray_module, monkeypatch):
    """Abort daemon start when desktop app fails to stop."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "running")
    monkeypatch.setattr(tray, "_stop_desktop_app_processes", lambda: False)
    calls = []
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(args) or _completed(returncode=0),
    )
    tray.start_daemon(None)
    assert any(
        "Failed to stop desktop app" in " ".join(cmd) for cmd in calls
    )  # nosec B101


def test_debug_mode_import_enables_warning_capture(monkeypatch, tmp_path):
    """Enable warning capture when module is imported in debug mode."""
    gi_mod = ModuleType("gi")
    setattr(gi_mod, "require_version", lambda *_args, **_kwargs: None)
    gtk_mod = DummyGtkModule("gi.repository.Gtk")
    glib_mod = DummyGLibModule("gi.repository.GLib")
    app_mod = DummyAppIndicatorModule("gi.repository.AyatanaAppIndicator3")

    monkeypatch.setitem(sys.modules, "gi", gi_mod)
    monkeypatch.setitem(
        sys.modules,
        "gi.repository",
        ModuleType("gi.repository"),
    )
    monkeypatch.setitem(sys.modules, "gi.repository.Gtk", gtk_mod)
    monkeypatch.setitem(sys.modules, "gi.repository.GLib", glib_mod)
    monkeypatch.setitem(
        sys.modules,
        "gi.repository.AyatanaAppIndicator3",
        app_mod,
    )

    original_import_module = importlib.import_module

    def fake_import_module(name):
        """Resolve mocked GI modules while importing debug module."""
        if name == "gi.repository.Gtk":
            return gtk_mod
        if name == "gi.repository.GLib":
            return glib_mod
        if name == "gi.repository.AyatanaAppIndicator3":
            return app_mod
        return original_import_module(name)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=1, stdout="", stderr=""),
    )
    monkeypatch.setattr(os, "getpid", lambda: 11111)

    captured = {"enabled": False}
    monkeypatch.setattr(
        "logging.captureWarnings",
        lambda enabled: captured.__setitem__("enabled", enabled),
    )

    module_name = "lmstudio_tray_debug"
    sys.modules.pop(module_name, None)
    old_argv = sys.argv[:]
    try:
        sys.argv = ["lmstudio_tray.py", "m", str(tmp_path), "debug"]
        spec = importlib.util.spec_from_file_location(
            module_name,
            str(Path(__file__).resolve().parents[1] / "lmstudio_tray.py"),
        )
        assert spec is not None and spec.loader is not None  # nosec B101
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        assert captured["enabled"] is True  # nosec B101
    finally:
        sys.argv = old_argv


def test_trayicon_constructor_sets_indicator_and_timer(
    tray_module,
    monkeypatch,
):
    """Initialize tray indicator properties and periodic timer."""
    monkeypatch.setattr(tray_module.TrayIcon, "build_menu", lambda self: None)
    monkeypatch.setattr(tray_module.TrayIcon, "check_model", lambda self: True)
    timer_calls = []
    monkeypatch.setattr(
        tray_module.GLib,
        "timeout_add_seconds",
        lambda seconds, callback: timer_calls.append(
            (seconds, callback)
        ) or True,
    )
    tray = tray_module.TrayIcon()
    assert (
        tray.indicator.status
        == tray_module.AppIndicator3.IndicatorStatus.ACTIVE
    )  # nosec B101
    assert tray.indicator.title == "LM Studio Monitor"  # nosec B101
    if not (timer_calls and timer_calls[0][0] == tray_module.INTERVAL):
        raise AssertionError("Timer not configured with expected interval")


def test_get_llmster_cmd_permission_error_and_no_candidates(
    tray_module,
    monkeypatch,
):
    """Return None when llmster directory scan fails or finds no binaries."""
    monkeypatch.setattr(tray_module.shutil, "which", lambda _x: None)
    monkeypatch.setattr(tray_module.os.path, "isdir", lambda _p: True)
    monkeypatch.setattr(
        tray_module.os,
        "listdir",
        lambda _p: (_ for _ in ()).throw(PermissionError("denied")),
    )
    assert tray_module.get_llmster_cmd() is None  # nosec B101

    monkeypatch.setattr(tray_module.os, "listdir", lambda _p: ["v1"])
    monkeypatch.setattr(tray_module.os.path, "isfile", lambda _p: False)
    monkeypatch.setattr(tray_module.os, "access", lambda _p, _m: False)
    assert tray_module.get_llmster_cmd() is None  # nosec B101


def test_is_llmster_running_first_probe_match(tray_module, monkeypatch):
    """Return running when first process probe succeeds."""
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0),
    )
    assert tray_module.is_llmster_running() is True  # nosec B101


def test_is_llmster_running_second_probe_error(tray_module, monkeypatch):
    """Return not running when fallback probe raises subprocess error."""
    calls = {"count": 0}

    def run_side_effect(*_args, **_kwargs):
        """Fail second probe after first probe miss."""
        calls["count"] += 1
        if calls["count"] == 1:
            return _completed(returncode=1)
        raise subprocess.SubprocessError("fail")

    monkeypatch.setattr(tray_module.subprocess, "run", run_side_effect)
    assert tray_module.is_llmster_running() is False  # nosec B101
