"""
Test suite for :class:`WindowsTrayIcon` and the Windows entry point.

The tray class is driven entirely through the stubs in
``windows_stubs.py``: ``pystray`` is replaced by recording doubles and
tkinter dialogs are patched out, so menu construction, status
transitions, daemon control and dialog wiring can all be asserted without
a notification area or a window station.

The companion file ``test_lmstudio_tray_windows.py`` covers the platform
primitives (paths, tasklist/taskkill, single-instance handling).
"""

import subprocess  # nosec B404
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from windows_stubs import (
    DummyIcon,
    DummyMenu,
    DummyTimer,
    completed as _completed,
    make_tray as _make_tray,
    menu_item as _menu_item,
    menu_labels as _menu_labels,
    stub_statuses as _stub_statuses,
)


@pytest.fixture(autouse=True)
def _inline_threads(windows_sync_threads):
    """Apply the inline-thread policy to every test in this module."""
    _ = windows_sync_threads


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------


def test_main_dispatches_to_windows(windows_module, monkeypatch):
    """main() hands off to the Windows entry point before the GTK code."""
    called = []
    monkeypatch.setattr(
        windows_module, "_run_windows", lambda args: called.append(args)
    )
    monkeypatch.setattr(sys, "argv", ["lmstudio_tray.py"])

    windows_module.main()

    assert len(called) == 1  # nosec B101


def test_run_windows_exits_without_pystray(
    windows_module, monkeypatch, capsys
):
    """A missing pystray reports the install command and exits 1."""
    monkeypatch.setattr(windows_module, "_pystray_lib", None)

    with pytest.raises(SystemExit) as exc:
        windows_module._run_windows(None)

    assert exc.value.code == 1  # nosec B101
    err = capsys.readouterr().err
    assert "pystray is not installed" in err  # nosec B101
    assert "requirements-windows.txt" in err  # nosec B101


def test_run_windows_exits_without_pillow(
    windows_module, monkeypatch, capsys
):
    """A missing Pillow is reported by name too."""
    monkeypatch.setattr(windows_module, "_pil_image", None)

    with pytest.raises(SystemExit) as exc:
        windows_module._run_windows(None)

    assert exc.value.code == 1  # nosec B101
    assert "pillow is not installed" in capsys.readouterr().err  # nosec B101


def test_run_windows_names_both_missing_libraries(
    windows_module, monkeypatch, capsys
):
    """Both missing libraries are listed, with plural agreement."""
    monkeypatch.setattr(windows_module, "_pystray_lib", None)
    monkeypatch.setattr(windows_module, "_pil_image", None)

    with pytest.raises(SystemExit):
        windows_module._run_windows(None)

    err = capsys.readouterr().err
    assert "pystray and pillow are not installed" in err  # nosec B101


def test_run_windows_starts_the_tray(windows_module, monkeypatch, tmp_path):
    """The happy path configures logging and runs the tray."""
    monkeypatch.setattr(
        windows_module._AppState, "script_dir", str(tmp_path)
    )
    monkeypatch.setattr(
        windows_module, "kill_existing_instances", lambda: None
    )

    started = []

    class FakeTray:
        """Stand-in for WindowsTrayIcon."""

        def run(self):
            """Record that the tray was started."""
            started.append(True)

    monkeypatch.setattr(windows_module, "WindowsTrayIcon", FakeTray)

    windows_module._run_windows(None)

    assert started == [True]  # nosec B101


# ---------------------------------------------------------------------
# Standard streams in a windowed build
# ---------------------------------------------------------------------


def test_ensure_std_streams_leaves_working_streams_alone(
    windows_module, monkeypatch
):
    """With a real console attached there is nothing to repair."""
    def fail():
        """Fail the test if the console is reattached needlessly."""
        pytest.fail("tried to attach a console that already exists")

    monkeypatch.setattr(windows_module, "_attach_parent_console", fail)

    windows_module._ensure_std_streams()


def test_ensure_std_streams_reattaches_parent_console(
    windows_module, monkeypatch
):
    """A windowed build reuses the console it was launched from."""
    monkeypatch.setattr(windows_module.sys, "stdout", None)
    attached = []
    monkeypatch.setattr(
        windows_module,
        "_attach_parent_console",
        lambda: attached.append(True) or True,
    )

    windows_module._ensure_std_streams()

    assert attached == [True]  # nosec B101


def test_ensure_std_streams_falls_back_to_devnull(
    windows_module, monkeypatch
):
    """Launched from Explorer, output is discarded rather than crashing.

    argparse writes to sys.stderr unconditionally, so leaving it as None
    turned --help into an AttributeError traceback.
    """
    monkeypatch.setattr(windows_module.sys, "stdout", None)
    monkeypatch.setattr(windows_module.sys, "stderr", None)
    monkeypatch.setattr(
        windows_module, "_attach_parent_console", lambda: False
    )

    windows_module._ensure_std_streams()

    assert windows_module.sys.stdout is not None  # nosec B101
    assert windows_module.sys.stderr is not None  # nosec B101
    # The point of the fallback: writing must not raise.
    windows_module.sys.stderr.write("discarded\n")


def test_attach_parent_console_reopens_streams(windows_module, monkeypatch):
    """A successful AttachConsole reopens stdout and stderr on it."""
    monkeypatch.setattr(windows_module.sys, "stdout", None)
    monkeypatch.setattr(windows_module.sys, "stderr", None)

    opened = []
    monkeypatch.setattr(
        windows_module.sys.modules["builtins"],
        "open",
        lambda target, *a, **k: opened.append(target) or SimpleNamespace(
            write=lambda _text: None
        ),
    )
    fake_ctypes = ModuleType("ctypes")
    setattr(
        fake_ctypes,
        "windll",
        SimpleNamespace(kernel32=SimpleNamespace(AttachConsole=lambda _p: 1)),
    )
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    assert windows_module._attach_parent_console() is True  # nosec B101
    assert opened == ["CONOUT$", "CONOUT$"]  # nosec B101


def test_attach_parent_console_without_a_parent_console(
    windows_module, monkeypatch
):
    """No console to attach to reports failure so the caller can fall back."""
    monkeypatch.setattr(windows_module.sys, "stdout", None)
    fake_ctypes = ModuleType("ctypes")
    setattr(
        fake_ctypes,
        "windll",
        SimpleNamespace(kernel32=SimpleNamespace(AttachConsole=lambda _p: 0)),
    )
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    assert windows_module._attach_parent_console() is False  # nosec B101


def test_attach_parent_console_survives_missing_kernel32(
    windows_module, monkeypatch
):
    """A ctypes without windll (any non-Windows host) is not fatal."""
    monkeypatch.setattr(windows_module.sys, "stdout", None)
    monkeypatch.setitem(sys.modules, "ctypes", ModuleType("ctypes"))

    assert windows_module._attach_parent_console() is False  # nosec B101


def test_configure_logging_writes_header(
    windows_module, monkeypatch, tmp_path
):
    """The shared logging setup truncates and headers the log file."""
    monkeypatch.setattr(
        windows_module._AppState, "script_dir", str(tmp_path)
    )

    log_file = windows_module._configure_logging()

    assert Path(log_file).name == "lmstudio_tray.log"  # nosec B101
    content = Path(log_file).read_text(encoding="utf-8")
    assert "LM Studio Tray Monitor Log" in content  # nosec B101


# ---------------------------------------------------------------------
# Tray construction
# ---------------------------------------------------------------------


def test_init_builds_icon_and_menu(windows_module, monkeypatch):
    """The constructor creates the icon and populates its menu."""
    _stub_statuses(windows_module, monkeypatch, "stopped", "stopped")

    tray = windows_module.WindowsTrayIcon()

    assert isinstance(tray.icon, DummyIcon)  # nosec B101
    assert isinstance(tray.icon.menu, DummyMenu)  # nosec B101
    assert tray.icon.title == "⚠️ " + windows_module.APP_NAME  # nosec B101


def test_init_without_pystray_raises(windows_module, monkeypatch):
    """Constructing without pystray fails loudly rather than half-working."""
    monkeypatch.setattr(windows_module, "_pystray_lib", None)

    with pytest.raises(RuntimeError, match="pystray is not installed"):
        windows_module.WindowsTrayIcon()


def test_load_icon_image_uses_asset(windows_module, monkeypatch):
    """The bundled PNG is used for the tray icon when present."""
    monkeypatch.setattr(
        windows_module, "get_asset_path", lambda *_p: r"C:\assets\icon.png"
    )

    image = windows_module.WindowsTrayIcon._load_icon_image()

    assert image == r"image:C:\assets\icon.png"  # nosec B101


def test_load_icon_image_falls_back_when_asset_missing(
    windows_module, monkeypatch
):
    """A missing asset yields a solid fallback, never an invisible icon."""
    monkeypatch.setattr(windows_module, "get_asset_path", lambda *_p: None)

    assert (  # nosec B101
        windows_module.WindowsTrayIcon._load_icon_image() == "image:fallback"
    )


def test_load_icon_image_falls_back_on_unreadable_asset(
    windows_module, monkeypatch
):
    """A corrupt PNG falls back rather than taking the tray down."""
    monkeypatch.setattr(
        windows_module, "get_asset_path", lambda *_p: r"C:\assets\icon.png"
    )

    def _raise(*_args, **_kwargs):
        """Simulate Pillow rejecting the file."""
        raise OSError("not a PNG")

    monkeypatch.setattr(windows_module._pil_image, "open", _raise)

    assert (  # nosec B101
        windows_module.WindowsTrayIcon._load_icon_image() == "image:fallback"
    )


def test_load_icon_image_without_pillow_raises(windows_module, monkeypatch):
    """Without Pillow there is no way to build an icon at all."""
    monkeypatch.setattr(windows_module, "_pil_image", None)

    with pytest.raises(RuntimeError, match="Pillow is not installed"):
        windows_module.WindowsTrayIcon._load_icon_image()


# ---------------------------------------------------------------------
# Tooltip
# ---------------------------------------------------------------------


def test_title_setter_updates_tooltip(windows_module):
    """Setting the status emoji rewrites the notification-area tooltip."""
    tray = _make_tray(windows_module)

    tray.title = "✅"

    assert tray.title == "✅"  # nosec B101
    assert tray.icon.title == "✅ " + windows_module.APP_NAME  # nosec B101


def test_title_setter_survives_icon_errors(windows_module):
    """A tooltip that cannot be set is logged, not raised."""
    tray = _make_tray(windows_module)

    class ExplodingIcon:
        """Icon stub whose title assignment fails."""

        @property
        def title(self):
            """Return nothing; only the setter matters here."""
            return None

        @title.setter
        def title(self, _value):
            """Reject the assignment the way a dead icon would."""
            raise OSError("icon is gone")

    tray.icon = ExplodingIcon()
    tray.title = "❌"

    assert tray.title == "❌"  # nosec B101


def test_title_setter_before_icon_exists(windows_module):
    """The status can be set before the icon is constructed."""
    cls = windows_module.WindowsTrayIcon
    tray = cls.__new__(cls)

    tray.title = "ℹ️"

    assert tray.title == "ℹ️"  # nosec B101


# ---------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected",
    [("running", "🟢"), ("stopped", "🟡"), ("not_found", "🔴")],
)
def test_status_indicator(windows_module, status, expected):
    """Each status maps to its own indicator."""
    tray = _make_tray(windows_module)

    assert tray.get_status_indicator(status) == expected  # nosec B101


def test_daemon_status_running(windows_module, monkeypatch):
    """An available and running daemon reports 'running'."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "is_daemon_available", lambda: True)
    monkeypatch.setattr(windows_module, "is_llmster_running", lambda: True)

    assert tray.get_daemon_status() == "running"  # nosec B101


def test_daemon_status_stopped(windows_module, monkeypatch):
    """An installed but idle daemon reports 'stopped'."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "is_daemon_available", lambda: True)
    monkeypatch.setattr(windows_module, "is_llmster_running", lambda: False)

    assert tray.get_daemon_status() == "stopped"  # nosec B101


def test_daemon_status_not_installed(windows_module, monkeypatch):
    """An unavailable daemon reports 'not_found'."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "is_daemon_available", lambda: False)

    assert tray.get_daemon_status() == "not_found"  # nosec B101


def test_daemon_status_survives_subprocess_error(windows_module, monkeypatch):
    """A failing probe degrades to 'not_found' rather than raising."""
    tray = _make_tray(windows_module)

    def _raise():
        """Simulate the probe blowing up."""
        raise OSError("boom")

    monkeypatch.setattr(windows_module, "is_daemon_available", _raise)

    assert tray.get_daemon_status() == "not_found"  # nosec B101


def test_desktop_status_running(windows_module, monkeypatch):
    """Any LM Studio PID means the desktop app is running."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module, "get_desktop_app_pids", lambda: [1, 2]
    )

    assert tray.get_desktop_app_status() == "running"  # nosec B101


def test_desktop_status_installed_but_stopped(
    windows_module, monkeypatch, tmp_path
):
    """An installed but idle app reports 'stopped'."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "get_desktop_app_pids", lambda: [])

    exe = tmp_path / "LM Studio.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "_APP_LOCATIONS", [str(exe)]
    )

    assert tray.get_desktop_app_status() == "stopped"  # nosec B101


def test_desktop_status_not_installed(windows_module, monkeypatch, tmp_path):
    """With no executable anywhere the app reports 'not_found'."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "get_desktop_app_pids", lambda: [])
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_APP_LOCATIONS",
        [str(tmp_path / "nope.exe")],
    )

    assert tray.get_desktop_app_status() == "not_found"  # nosec B101


def test_desktop_status_survives_probe_error(windows_module, monkeypatch):
    """A failing PID probe falls through to the install-path check."""
    tray = _make_tray(windows_module)

    def _raise():
        """Simulate tasklist failing."""
        raise OSError("boom")

    monkeypatch.setattr(windows_module, "get_desktop_app_pids", _raise)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "_APP_LOCATIONS", [r"C:\nope.exe"]
    )

    assert tray.get_desktop_app_status() == "not_found"  # nosec B101


def test_desktop_detection_logged_only_on_change(
    windows_module, monkeypatch, caplog
):
    """The every-few-seconds status check does not spam the log."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "get_desktop_app_pids", lambda: [])
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "_APP_LOCATIONS", [r"C:\nope.exe"]
    )

    with caplog.at_level("DEBUG"):
        tray.get_desktop_app_status()
        tray.get_desktop_app_status()
        tray.get_desktop_app_status()

    matches = [
        rec for rec in caplog.records
        if "No LM Studio desktop app found" in rec.getMessage()
    ]
    assert len(matches) == 1  # nosec B101


# ---------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------


def test_notify_sends_balloon(windows_module):
    """Notifications reach pystray with title and body."""
    tray = _make_tray(windows_module)

    tray._notify("LM Studio", "A model is loaded")

    assert tray.icon.notifications == [  # nosec B101
        ("LM Studio", "A model is loaded")
    ]


def test_notify_survives_backend_failure(windows_module):
    """A failing notification backend never propagates to the caller."""
    tray = _make_tray(windows_module)

    def _raise(*_args, **_kwargs):
        """Simulate a shell with no notification area."""
        raise NotImplementedError("no tray")

    tray.icon.notify = _raise

    tray._notify("LM Studio", "ignored")


# ---------------------------------------------------------------------
# Menu building
# ---------------------------------------------------------------------


def test_menu_offers_stop_when_both_running(windows_module, monkeypatch):
    """Running services offer stop actions, not start actions."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "running", "running")

    tray.build_menu()
    labels = [str(x) for x in _menu_labels(tray)]

    assert "  → Stop Daemon" in labels  # nosec B101
    assert "  → Stop Desktop App" in labels  # nosec B101
    assert not any("Start" in x for x in labels)  # nosec B101


def test_menu_offers_start_when_both_stopped(windows_module, monkeypatch):
    """Installed but idle services offer start actions."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "stopped", "stopped")

    tray.build_menu()
    labels = [str(x) for x in _menu_labels(tray)]

    assert any("Start Daemon" in x for x in labels)  # nosec B101
    assert any("Start Desktop App" in x for x in labels)  # nosec B101


def test_menu_marks_missing_services_as_not_installed(
    windows_module, monkeypatch
):
    """Uninstalled services are shown but not clickable."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "not_found", "not_found")

    tray.build_menu()

    daemon_item = _menu_item(tray, "Daemon (Not Installed)")
    app_item = _menu_item(tray, "Desktop App (Not Installed)")

    assert daemon_item.enabled is False  # nosec B101
    assert app_item.enabled is False  # nosec B101


def test_menu_status_labels_are_not_clickable(windows_module, monkeypatch):
    """A 'Running' heading is a label, not an action."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "running", "running")

    tray.build_menu()

    assert _menu_item(tray, "Daemon (Running)").enabled is False  # nosec B101


def test_menu_always_offers_status_options_and_quit(
    windows_module, monkeypatch
):
    """The trailing entries are present regardless of status."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "stopped", "stopped")

    tray.build_menu()
    labels = _menu_labels(tray)

    assert "Show Status" in labels  # nosec B101
    assert "Options" in labels  # nosec B101
    assert "Quit Tray" in labels  # nosec B101
    assert DummyMenu.SEPARATOR in labels  # nosec B101


def test_options_submenu_entries(windows_module, monkeypatch):
    """The Options submenu carries configuration, updates and about."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "stopped", "stopped")

    tray.build_menu()
    options = _menu_item(tray, "Options")

    assert [item.text for item in options.action.items] == [  # nosec B101
        "Configuration", "Check for Updates", "About",
    ]


def test_menu_refreshes_the_live_icon(windows_module, monkeypatch):
    """Rebuilding the menu asks pystray to redraw it."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "stopped", "stopped")

    tray.build_menu()

    assert tray.icon.update_menu_calls == 1  # nosec B101


def test_menu_update_before_icon_is_live(windows_module, monkeypatch):
    """A refresh before icon.run() is skipped rather than raising."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "stopped", "stopped")

    def _raise():
        """Simulate pystray rejecting an update on a hidden icon."""
        raise RuntimeError("icon is not running")

    tray.icon.update_menu = _raise

    tray.build_menu()


def test_menu_without_pystray_raises(windows_module, monkeypatch):
    """Building a menu with no pystray is a programming error."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "_pystray_lib", None)

    with pytest.raises(RuntimeError, match="pystray is not installed"):
        tray.build_menu()


def test_remote_menu_omits_local_controls(windows_module, monkeypatch):
    """A remote endpoint hides start/stop, which act on local processes."""
    tray = _make_tray(windows_module)
    tray.last_status = "OK"
    tray.remote_loaded_models = ["qwen/qwen3-coder-30b"]
    monkeypatch.setattr(windows_module, "is_remote_endpoint", lambda: True)
    monkeypatch.setattr(windows_module._AppState, "API_HOST", "10.0.0.5")
    monkeypatch.setattr(windows_module._AppState, "API_PORT", 1234)

    tray.build_menu()
    labels = [str(x) for x in _menu_labels(tray)]

    assert any("Remote: 10.0.0.5:1234" in x for x in labels)  # nosec B101
    assert not any("Daemon" in x for x in labels)  # nosec B101
    assert not any("Desktop App" in x for x in labels)  # nosec B101


def test_remote_menu_lists_multiple_models(windows_module, monkeypatch):
    """Several loaded models are listed individually."""
    tray = _make_tray(windows_module)
    tray.last_status = "OK"
    tray.remote_loaded_models = ["model-a", "model-b"]
    monkeypatch.setattr(windows_module, "is_remote_endpoint", lambda: True)

    tray.build_menu()
    labels = [str(x) for x in _menu_labels(tray)]

    assert any("2 models loaded" in x for x in labels)  # nosec B101
    assert any("model-a" in x for x in labels)  # nosec B101
    assert any("model-b" in x for x in labels)  # nosec B101


def test_remote_menu_names_single_model(windows_module, monkeypatch):
    """A single loaded model is named rather than counted."""
    tray = _make_tray(windows_module)
    tray.last_status = "OK"
    tray.remote_loaded_models = ["only-model"]
    monkeypatch.setattr(windows_module, "is_remote_endpoint", lambda: True)

    tray.build_menu()
    labels = [str(x) for x in _menu_labels(tray)]

    assert any("only-model loaded" in x for x in labels)  # nosec B101


def test_remote_menu_ok_without_named_models(windows_module, monkeypatch):
    """An OK endpoint that names no model still reports one is loaded."""
    tray = _make_tray(windows_module)
    tray.last_status = "OK"
    tray.remote_loaded_models = []
    monkeypatch.setattr(windows_module, "is_remote_endpoint", lambda: True)

    tray.build_menu()
    labels = [str(x) for x in _menu_labels(tray)]

    assert any("Model loaded" in x for x in labels)  # nosec B101


def test_remote_menu_no_model(windows_module, monkeypatch):
    """A reachable endpoint with nothing loaded says so."""
    tray = _make_tray(windows_module)
    tray.last_status = "INFO"
    monkeypatch.setattr(windows_module, "is_remote_endpoint", lambda: True)

    tray.build_menu()
    labels = [str(x) for x in _menu_labels(tray)]

    assert any("No model loaded" in x for x in labels)  # nosec B101


def test_remote_menu_unreachable(windows_module, monkeypatch):
    """An unreachable remote endpoint is labelled as such."""
    tray = _make_tray(windows_module)
    tray.last_status = "WARN"
    monkeypatch.setattr(windows_module, "is_remote_endpoint", lambda: True)

    tray.build_menu()
    labels = [str(x) for x in _menu_labels(tray)]

    assert any("Unreachable" in x for x in labels)  # nosec B101


# ---------------------------------------------------------------------
# Cooldown and scheduling
# ---------------------------------------------------------------------


def test_action_cooldown_blocks_second_click(windows_module):
    """A second click within the cooldown window is rejected."""
    tray = _make_tray(windows_module)

    assert tray.begin_action_cooldown("start_daemon") is True  # nosec B101
    assert tray.begin_action_cooldown("start_daemon") is False  # nosec B101


def test_action_cooldown_expires(windows_module):
    """Once the window has passed the action is allowed again."""
    tray = _make_tray(windows_module)

    tray.begin_action_cooldown("start_daemon", seconds=0)

    assert tray.begin_action_cooldown("start_daemon") is True  # nosec B101


def test_schedule_menu_refresh_uses_a_timer(windows_module, monkeypatch):
    """The delayed rebuild is scheduled, and rebuilds when it fires."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "stopped", "stopped")

    tray._schedule_menu_refresh(2)

    assert len(DummyTimer.created) == 1  # nosec B101
    timer = DummyTimer.created[0]
    assert timer.interval == 2  # nosec B101

    timer.fire()

    assert tray.icon.update_menu_calls == 1  # nosec B101


# ---------------------------------------------------------------------
# Status check
# ---------------------------------------------------------------------


def test_check_model_reports_fail_when_nothing_installed(
    windows_module, monkeypatch
):
    """Neither component installed is the FAIL state."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "not_found", "not_found")

    tray.check_model()

    assert tray.last_status == "FAIL"  # nosec B101
    assert tray.title == "❌"  # nosec B101


def test_check_model_reports_warn_when_nothing_running(
    windows_module, monkeypatch
):
    """Installed but idle is the WARN state."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "stopped", "stopped")

    tray.check_model()

    assert tray.last_status == "WARN"  # nosec B101
    assert tray.title == "⚠️"  # nosec B101


def test_check_model_reports_ok_when_model_loaded(
    windows_module, monkeypatch
):
    """A loaded model reported by `lms ps` is the OK state."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "running", "stopped")
    monkeypatch.setattr(windows_module, "get_lms_cmd", lambda: r"C:\lms.exe")
    monkeypatch.setattr(
        windows_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=0, stdout="my-model"),
    )
    monkeypatch.setattr(windows_module, "_has_loaded_model", lambda _o: True)

    tray.check_model()

    assert tray.last_status == "OK"  # nosec B101
    assert tray.title == "✅"  # nosec B101


def test_check_model_reports_info_without_model(windows_module, monkeypatch):
    """A running runtime with no model is the INFO state."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "running", "stopped")
    monkeypatch.setattr(windows_module, "get_lms_cmd", lambda: r"C:\lms.exe")
    monkeypatch.setattr(
        windows_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=0, stdout=""),
    )
    monkeypatch.setattr(windows_module, "_has_loaded_model", lambda _o: False)

    tray.check_model()

    assert tray.last_status == "INFO"  # nosec B101
    assert tray.title == "ℹ️"  # nosec B101


def test_check_model_falls_back_to_api(windows_module, monkeypatch):
    """A failing `lms ps` falls back to the HTTP API."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "running", "stopped")
    monkeypatch.setattr(windows_module, "get_lms_cmd", lambda: r"C:\lms.exe")
    monkeypatch.setattr(
        windows_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=1),
    )
    monkeypatch.setattr(windows_module, "check_api_models", lambda: True)

    tray.check_model()

    assert tray.last_status == "OK"  # nosec B101


def test_check_model_api_reports_no_models(windows_module, monkeypatch):
    """A failing `lms ps` and an empty API is the INFO state."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "running", "stopped")
    monkeypatch.setattr(windows_module, "get_lms_cmd", lambda: r"C:\lms.exe")
    monkeypatch.setattr(
        windows_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=1),
    )
    monkeypatch.setattr(windows_module, "check_api_models", lambda: False)

    tray.check_model()

    assert tray.last_status == "INFO"  # nosec B101


def test_check_model_skips_lms_ps_during_app_start(
    windows_module, monkeypatch
):
    """`lms ps` is withheld while the desktop app is still booting.

    It is not a read-only command: with no service up it wakes one, which
    would race the app that is already starting.
    """
    tray = _make_tray(windows_module)
    tray.lms_ps_resume_at = time.monotonic() + 60
    _stub_statuses(windows_module, monkeypatch, "stopped", "running")
    monkeypatch.setattr(windows_module, "get_lms_cmd", lambda: r"C:\lms.exe")

    def fail(_cmd):
        """Fail the test if lms ps is invoked during the grace window."""
        pytest.fail("lms ps called while the desktop app was starting")

    monkeypatch.setattr(windows_module, "_run_safe_command", fail)
    monkeypatch.setattr(windows_module, "check_api_models", lambda: False)

    tray.check_model()

    assert tray.last_status == "INFO"  # nosec B101


def test_check_model_notifies_on_status_change(windows_module, monkeypatch):
    """A transition notifies; the steady state does not."""
    tray = _make_tray(windows_module)
    tray.last_status = "WARN"
    _stub_statuses(windows_module, monkeypatch, "not_found", "not_found")

    tray.check_model()
    assert len(tray.icon.notifications) == 1  # nosec B101

    tray.check_model()
    assert len(tray.icon.notifications) == 1  # nosec B101


def test_check_model_first_run_does_not_notify(windows_module, monkeypatch):
    """Startup is not a transition, so it stays quiet."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "not_found", "not_found")

    tray.check_model()

    assert tray.icon.notifications == []  # nosec B101


@pytest.mark.parametrize(
    "previous,daemon,app,fragment",
    [
        ("FAIL", "stopped", "stopped", "Neither daemon nor desktop app"),
        ("WARN", "not_found", "not_found", "not installed"),
    ],
)
def test_check_model_transition_messages(
    windows_module, monkeypatch, previous, daemon, app, fragment
):
    """Each transition carries a message naming what happened."""
    tray = _make_tray(windows_module)
    tray.last_status = previous
    _stub_statuses(windows_module, monkeypatch, daemon, app)

    tray.check_model()

    assert fragment in tray.icon.notifications[0][1]  # nosec B101


@pytest.mark.parametrize(
    "previous,names,fragment",
    [
        ("INFO", ["m1"], "A model is loaded"),
        ("OK", [], "Runtime active, no model loaded"),
    ],
)
def test_check_model_remote_transition_messages(
    windows_module, monkeypatch, previous, names, fragment
):
    """Remote transitions notify with the matching message."""
    tray = _make_tray(windows_module)
    tray.last_status = previous
    monkeypatch.setattr(windows_module, "is_remote_endpoint", lambda: True)
    monkeypatch.setattr(
        windows_module, "query_api_models", lambda: (True, names)
    )

    tray.check_model()

    assert fragment in tray.icon.notifications[0][1]  # nosec B101


def test_check_model_remote_unreachable_message(windows_module, monkeypatch):
    """An unreachable remote endpoint names the endpoint, not the daemon."""
    tray = _make_tray(windows_module)
    tray.last_status = "OK"
    monkeypatch.setattr(windows_module, "is_remote_endpoint", lambda: True)
    monkeypatch.setattr(
        windows_module, "query_api_models", lambda: (False, [])
    )

    tray.check_model()

    assert (  # nosec B101
        "Remote endpoint is unreachable" in tray.icon.notifications[0][1]
    )


def test_check_model_remote_endpoint(windows_module, monkeypatch):
    """A remote endpoint is judged purely by the API."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "is_remote_endpoint", lambda: True)
    monkeypatch.setattr(
        windows_module, "query_api_models", lambda: (True, ["m1"])
    )

    tray.check_model()

    assert tray.last_status == "OK"  # nosec B101
    assert tray.remote_loaded_models == ["m1"]  # nosec B101


def test_check_model_remote_reachable_without_model(
    windows_module, monkeypatch
):
    """A reachable endpoint with nothing loaded is the INFO state."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "is_remote_endpoint", lambda: True)
    monkeypatch.setattr(
        windows_module, "query_api_models", lambda: (True, [])
    )

    tray.check_model()

    assert tray.last_status == "INFO"  # nosec B101


def test_check_model_remote_unreachable(windows_module, monkeypatch):
    """An unreachable remote endpoint is the WARN state."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "is_remote_endpoint", lambda: True)
    monkeypatch.setattr(
        windows_module, "query_api_models", lambda: (False, [])
    )

    tray.check_model()

    assert tray.last_status == "WARN"  # nosec B101
    assert tray.title == "⚠️"  # nosec B101


def test_check_model_survives_timeout(windows_module, monkeypatch):
    """A timed-out probe keeps the previous status."""
    tray = _make_tray(windows_module)
    tray.last_status = "OK"

    def _timeout():
        """Simulate a probe exceeding its timeout."""
        raise subprocess.TimeoutExpired(cmd="lms", timeout=10)

    monkeypatch.setattr(windows_module, "is_remote_endpoint", _timeout)

    tray.check_model()

    assert tray.last_status == "OK"  # nosec B101


def test_check_model_survives_oserror(windows_module, monkeypatch):
    """An OSError marks the tray failed rather than killing the loop."""
    tray = _make_tray(windows_module)

    def _raise():
        """Simulate the probe failing outright."""
        raise OSError("boom")

    monkeypatch.setattr(windows_module, "is_remote_endpoint", _raise)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "build_menu", lambda _self: None
    )

    assert tray.check_model() is True  # nosec B101
    assert tray.title == "❌"  # nosec B101


# ---------------------------------------------------------------------
# Daemon control
# ---------------------------------------------------------------------


def test_build_daemon_attempts_start_excludes_lms(
    windows_module, monkeypatch
):
    """Only llmster may start a daemon; lms would launch the GUI."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "get_lms_cmd", lambda: r"C:\lms.exe")
    monkeypatch.setattr(
        windows_module, "get_llmster_cmd", lambda: r"C:\llmster.exe"
    )

    attempts = tray._build_daemon_attempts("start")

    assert attempts  # nosec B101
    assert all(a[0] == r"C:\llmster.exe" for a in attempts)  # nosec B101


def test_build_daemon_attempts_stop_uses_both(windows_module, monkeypatch):
    """Stopping tries lms first, then llmster."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "get_lms_cmd", lambda: r"C:\lms.exe")
    monkeypatch.setattr(
        windows_module, "get_llmster_cmd", lambda: r"C:\llmster.exe"
    )

    attempts = tray._build_daemon_attempts("stop")

    assert attempts[0][0] == r"C:\lms.exe"  # nosec B101
    assert attempts[-1][0] == r"C:\llmster.exe"  # nosec B101


def test_build_daemon_attempts_without_any_cli(windows_module, monkeypatch):
    """With no CLI installed there is nothing to try."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "get_lms_cmd", lambda: None)
    monkeypatch.setattr(windows_module, "get_llmster_cmd", lambda: None)

    assert tray._build_daemon_attempts("start") == []  # nosec B101
    assert tray._build_daemon_attempts("stop") == []  # nosec B101


def test_force_stop_llmster_escalates_to_force_flag(
    windows_module, monkeypatch
):
    """A daemon that ignores the graceful stop gets taskkill /F."""
    tray = _make_tray(windows_module)
    calls = []
    monkeypatch.setattr(
        windows_module,
        "_run_taskkill",
        lambda args: calls.append(args) or True,
    )
    monkeypatch.setattr(windows_module, "is_llmster_running", lambda: True)
    monkeypatch.setattr(windows_module.time, "sleep", lambda _s: None)

    tray._force_stop_llmster()

    assert calls[0] == ["/IM", "llmster.exe", "/T"]  # nosec B101
    assert calls[1] == ["/IM", "llmster.exe", "/T", "/F"]  # nosec B101


def test_force_stop_llmster_stops_after_graceful_exit(
    windows_module, monkeypatch
):
    """A daemon that exits gracefully is never force-killed."""
    tray = _make_tray(windows_module)
    calls = []
    monkeypatch.setattr(
        windows_module,
        "_run_taskkill",
        lambda args: calls.append(args) or True,
    )
    monkeypatch.setattr(windows_module, "is_llmster_running", lambda: False)

    tray._force_stop_llmster()

    assert calls == [["/IM", "llmster.exe", "/T"]]  # nosec B101


def test_force_stop_llmster_without_taskkill(windows_module, monkeypatch):
    """A missing taskkill.exe ends the attempt instead of looping."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "_run_taskkill", lambda _args: False)

    def fail():
        """Fail the test if the wait loop is entered."""
        pytest.fail("waited for a stop that was never issued")

    monkeypatch.setattr(windows_module, "is_llmster_running", fail)

    tray._force_stop_llmster()


def test_stop_desktop_app_processes_escalates(windows_module, monkeypatch):
    """A desktop app that ignores the graceful stop gets taskkill /F."""
    tray = _make_tray(windows_module)
    calls = []
    monkeypatch.setattr(
        windows_module,
        "_run_taskkill",
        lambda args: calls.append(args) or True,
    )
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "get_desktop_app_status",
        lambda _self: "running",
    )
    monkeypatch.setattr(windows_module.time, "sleep", lambda _s: None)

    assert tray._stop_desktop_app_processes() is False  # nosec B101
    assert calls[0] == ["/IM", "LM Studio.exe", "/T"]  # nosec B101
    assert calls[1] == ["/IM", "LM Studio.exe", "/T", "/F"]  # nosec B101


def test_stop_desktop_app_processes_graceful(windows_module, monkeypatch):
    """An app that exits on the first request is not force-killed."""
    tray = _make_tray(windows_module)
    calls = []
    monkeypatch.setattr(
        windows_module,
        "_run_taskkill",
        lambda args: calls.append(args) or True,
    )
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "get_desktop_app_status",
        lambda _self: "stopped",
    )

    assert tray._stop_desktop_app_processes() is True  # nosec B101
    assert calls == [["/IM", "LM Studio.exe", "/T"]]  # nosec B101


def test_stop_daemon_notifies_on_success(windows_module, monkeypatch):
    """A successful stop tells the user the daemon is down."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_build_daemon_attempts",
        lambda _self, _action: [[r"C:\lms.exe", "daemon", "down"]],
    )
    monkeypatch.setattr(
        windows_module, "_run_safe_command", lambda _cmd: _completed()
    )
    monkeypatch.setattr(windows_module, "is_llmster_running", lambda: False)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "_force_stop_llmster",
        lambda _self: None,
    )

    stopped, _result = tray._stop_daemon_with_notification()

    assert stopped is True  # nosec B101
    assert tray.icon.notifications[0][0] == "LLMster"  # nosec B101


def test_stop_daemon_reports_failure_with_detail(windows_module, monkeypatch):
    """A daemon that will not die reports the CLI's own error text."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_build_daemon_attempts",
        lambda _self, _action: [[r"C:\lms.exe", "daemon", "down"]],
    )
    monkeypatch.setattr(
        windows_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=1, stderr="permission denied"),
    )
    monkeypatch.setattr(windows_module, "is_llmster_running", lambda: True)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "_force_stop_llmster",
        lambda _self: None,
    )

    stopped, _result = tray._stop_daemon_with_notification()

    assert stopped is False  # nosec B101
    assert "permission denied" in tray.icon.notifications[0][1]  # nosec B101


def test_stop_daemon_reports_missing_cli(windows_module, monkeypatch):
    """With no CLI at all there is nothing to stop, and we say so."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_build_daemon_attempts",
        lambda _self, _action: [],
    )

    stopped, result = tray._stop_daemon_with_notification()

    assert stopped is False  # nosec B101
    assert result is None  # nosec B101
    assert tray.icon.notifications[0][0] == "Error"  # nosec B101


def test_start_daemon_stops_desktop_app_first(windows_module, monkeypatch):
    """The desktop app is stopped first; the two compete for the port."""
    tray = _make_tray(windows_module)
    order = []

    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "get_desktop_app_status",
        lambda _self: "running",
    )
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_stop_desktop_app_processes",
        lambda _self: order.append("stop-app") or True,
    )
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_build_daemon_attempts",
        lambda _self, _a: [[r"C:\llmster.exe", "daemon", "up"]],
    )
    monkeypatch.setattr(
        windows_module,
        "_run_safe_command",
        lambda _cmd: order.append("start-daemon") or _completed(),
    )
    monkeypatch.setattr(windows_module, "is_llmster_running", lambda: True)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "build_menu", lambda _self: None
    )

    tray.start_daemon()

    assert order == ["stop-app", "start-daemon"]  # nosec B101
    assert tray.icon.notifications[0][0] == "LLMster"  # nosec B101


def test_start_daemon_aborts_when_app_will_not_stop(
    windows_module, monkeypatch
):
    """If the desktop app cannot be stopped, no daemon start is attempted."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "get_desktop_app_status",
        lambda _self: "running",
    )
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_stop_desktop_app_processes",
        lambda _self: False,
    )

    def fail(_self, _action):
        """Fail the test if a daemon start is attempted anyway."""
        pytest.fail("attempted to start the daemon with the app still up")

    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "_build_daemon_attempts", fail
    )

    tray.start_daemon()

    assert tray.icon.notifications[0][0] == "Error"  # nosec B101


def test_start_daemon_reports_missing_llmster(windows_module, monkeypatch):
    """Without llmster the user is pointed at the download page."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "get_desktop_app_status",
        lambda _self: "stopped",
    )
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_build_daemon_attempts",
        lambda _self, _a: [],
    )

    tray.start_daemon()

    title, message = tray.icon.notifications[0]
    assert title == "Daemon"  # nosec B101
    assert "lmstudio.ai/download" in message  # nosec B101


def test_start_daemon_reports_failure(windows_module, monkeypatch):
    """A daemon that never comes up is reported as a failure."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "get_desktop_app_status",
        lambda _self: "stopped",
    )
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_build_daemon_attempts",
        lambda _self, _a: [[r"C:\llmster.exe", "up"]],
    )
    monkeypatch.setattr(
        windows_module, "_run_safe_command", lambda _cmd: _completed()
    )
    monkeypatch.setattr(windows_module, "is_llmster_running", lambda: False)
    monkeypatch.setattr(windows_module.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "build_menu", lambda _self: None
    )

    tray.start_daemon()

    assert tray.icon.notifications[-1] == (  # nosec B101
        "Error", "Daemon start failed"
    )


def test_start_daemon_respects_cooldown(windows_module, monkeypatch):
    """A double click does not start the daemon twice."""
    tray = _make_tray(windows_module)
    tray.action_lock_until = time.monotonic() + 60

    def fail(_self):
        """Fail the test if the blocked action still ran."""
        pytest.fail("cooldown did not block the action")

    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "_start_daemon_body", fail
    )

    tray.start_daemon()


def test_start_daemon_body_reports_unexpected_errors(
    windows_module, monkeypatch
):
    """An unexpected error in the worker reaches the user."""
    tray = _make_tray(windows_module)

    def _raise(_self):
        """Simulate an unforeseen failure inside the worker."""
        raise ValueError("unexpected")

    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "_start_daemon_body_impl", _raise
    )

    tray._start_daemon_body()

    assert tray.icon.notifications[0][0] == "Error"  # nosec B101


def test_stop_daemon_body_reports_unexpected_errors(
    windows_module, monkeypatch
):
    """An unexpected error while stopping reaches the user."""
    tray = _make_tray(windows_module)

    def _raise(_self):
        """Simulate an unforeseen failure inside the worker."""
        raise ValueError("unexpected")

    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_stop_daemon_with_notification",
        _raise,
    )

    tray._stop_daemon_body()

    assert tray.icon.notifications[0][0] == "Error"  # nosec B101


def test_stop_daemon_respects_cooldown(windows_module, monkeypatch):
    """A double click does not stop the daemon twice."""
    tray = _make_tray(windows_module)
    tray.action_lock_until = time.monotonic() + 60

    def fail(_self):
        """Fail the test if the blocked action still ran."""
        pytest.fail("cooldown did not block the action")

    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "_stop_daemon_body", fail
    )

    tray.stop_daemon()


# ---------------------------------------------------------------------
# Desktop app control
# ---------------------------------------------------------------------


def test_start_desktop_app_launches_installed_exe(
    windows_module, monkeypatch, tmp_path
):
    """The installed executable is launched detached."""
    tray = _make_tray(windows_module)
    exe = tmp_path / "LM Studio.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "_APP_LOCATIONS", [str(exe)]
    )
    monkeypatch.setattr(windows_module, "is_llmster_running", lambda: False)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "build_menu", lambda _self: None
    )

    launched = []
    monkeypatch.setattr(
        windows_module.subprocess,
        "Popen",
        lambda cmd, **kwargs: launched.append((cmd, kwargs)),
    )

    tray.start_desktop_app()

    assert launched[0][0] == [str(exe)]  # nosec B101
    assert tray.lms_ps_resume_at > time.monotonic()  # nosec B101


def test_start_desktop_app_stops_daemon_first(
    windows_module, monkeypatch, tmp_path
):
    """A running daemon is stopped before the app takes the port."""
    tray = _make_tray(windows_module)
    exe = tmp_path / "LM Studio.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "_APP_LOCATIONS", [str(exe)]
    )
    monkeypatch.setattr(windows_module, "is_llmster_running", lambda: True)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "build_menu", lambda _self: None
    )

    order = []
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_stop_daemon_with_notification",
        lambda _self: order.append("stop-daemon") or (True, None),
    )
    monkeypatch.setattr(
        windows_module.subprocess,
        "Popen",
        lambda cmd, **kwargs: order.append("launch"),
    )

    tray.start_desktop_app()

    assert order == ["stop-daemon", "launch"]  # nosec B101


def test_start_desktop_app_reports_missing_install(
    windows_module, monkeypatch, tmp_path
):
    """With nothing installed the user is pointed at the download page."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_APP_LOCATIONS",
        [str(tmp_path / "nope.exe")],
    )
    monkeypatch.setattr(windows_module, "is_llmster_running", lambda: False)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "build_menu", lambda _self: None
    )

    tray.start_desktop_app()

    title, message = tray.icon.notifications[0]
    assert title == "Error"  # nosec B101
    assert "lmstudio.ai/download" in message  # nosec B101


def test_start_desktop_app_reports_launch_failure(
    windows_module, monkeypatch, tmp_path
):
    """A failed launch is reported rather than silently swallowed."""
    tray = _make_tray(windows_module)
    exe = tmp_path / "LM Studio.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "_APP_LOCATIONS", [str(exe)]
    )
    monkeypatch.setattr(windows_module, "is_llmster_running", lambda: False)

    def _raise(*_args, **_kwargs):
        """Simulate the executable failing to start."""
        raise OSError("access denied")

    monkeypatch.setattr(windows_module.subprocess, "Popen", _raise)

    tray.start_desktop_app()

    assert tray.icon.notifications[0][0] == "Error"  # nosec B101


def test_stop_desktop_app_when_not_running(windows_module, monkeypatch):
    """Stopping an app that is not running is a quiet no-op."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "get_desktop_app_pids", lambda: [])
    _stub_statuses(windows_module, monkeypatch, "stopped", "not_found")

    tray.stop_desktop_app()

    assert tray.icon.notifications == []  # nosec B101


def test_stop_desktop_app_notifies_on_success(windows_module, monkeypatch):
    """A successful stop is confirmed to the user."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module, "get_desktop_app_pids", lambda: [100]
    )
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_stop_desktop_app_processes",
        lambda _self: True,
    )
    _stub_statuses(windows_module, monkeypatch, "stopped", "stopped")

    tray.stop_desktop_app()

    assert tray.icon.notifications[0] == (  # nosec B101
        "LM Studio", "Desktop app stopped"
    )


def test_stop_desktop_app_notifies_on_failure(windows_module, monkeypatch):
    """A stop that does not take effect is reported as an error."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module, "get_desktop_app_pids", lambda: [100]
    )
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_stop_desktop_app_processes",
        lambda _self: False,
    )
    _stub_statuses(windows_module, monkeypatch, "stopped", "running")

    tray.stop_desktop_app()

    assert tray.icon.notifications[0][0] == "Error"  # nosec B101


def test_stop_desktop_app_respects_cooldown(windows_module, monkeypatch):
    """A double click does not stop the app twice."""
    tray = _make_tray(windows_module)
    tray.action_lock_until = time.monotonic() + 60

    def fail():
        """Fail the test if the blocked action still ran."""
        pytest.fail("cooldown did not block the action")

    monkeypatch.setattr(windows_module, "get_desktop_app_pids", fail)

    tray.stop_desktop_app()


# ---------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------


def test_status_dialog_shows_collected_text(windows_module, monkeypatch):
    """The status dialog renders whatever the collector produced."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_collect_status_text",
        lambda _self: "my status text",
    )
    shown = []
    monkeypatch.setattr(
        windows_module,
        "_show_tk_message",
        lambda title, message: shown.append((title, message)) or True,
    )

    tray.show_status_dialog()

    assert shown == [("Status", "my status text")]  # nosec B101


def test_collect_status_text_without_anything_running(
    windows_module, monkeypatch
):
    """With nothing up the text explains what to start."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "stopped", "stopped")

    text = tray._collect_status_text()

    assert "Neither the daemon nor the desktop app" in text  # nosec B101


def test_collect_status_text_without_lms_cli(windows_module, monkeypatch):
    """A running runtime with no CLI says the CLI is missing."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "running", "stopped")
    monkeypatch.setattr(windows_module, "get_lms_cmd", lambda: None)

    assert "not found" in tray._collect_status_text()  # nosec B101


def test_collect_status_text_formats_lms_output(windows_module, monkeypatch):
    """`lms ps` output is passed through the shared formatter."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "running", "stopped")
    monkeypatch.setattr(windows_module, "get_lms_cmd", lambda: r"C:\lms.exe")
    monkeypatch.setattr(
        windows_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=0, stdout="raw output"),
    )
    monkeypatch.setattr(
        windows_module, "_format_lms_ps_output", lambda text: f"[{text}]"
    )

    assert tray._collect_status_text() == "[raw output]"  # nosec B101


def test_collect_status_text_remote_lists_models(
    windows_module, monkeypatch
):
    """A remote endpoint lists its loaded models."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "is_remote_endpoint", lambda: True)
    monkeypatch.setattr(
        windows_module, "check_api_reachable", lambda: (True, True)
    )
    monkeypatch.setattr(
        windows_module, "get_api_loaded_models", lambda: ["m1", "m2"]
    )

    text = tray._collect_status_text()

    assert "Loaded models" in text  # nosec B101
    assert "m1" in text and "m2" in text  # nosec B101


def test_collect_status_text_remote_unreachable(windows_module, monkeypatch):
    """An unreachable remote endpoint says so plainly."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "is_remote_endpoint", lambda: True)
    monkeypatch.setattr(
        windows_module, "check_api_reachable", lambda: (False, False)
    )

    assert "not reachable" in tray._collect_status_text()  # nosec B101


def test_collect_status_text_remote_without_model(
    windows_module, monkeypatch
):
    """A reachable endpoint with nothing loaded says so."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "is_remote_endpoint", lambda: True)
    monkeypatch.setattr(
        windows_module, "check_api_reachable", lambda: (True, False)
    )

    assert "No model is loaded" in tray._collect_status_text()  # nosec B101


def test_collect_status_text_remote_unnamed_model(
    windows_module, monkeypatch
):
    """A loaded but unnamed model is still reported as loaded."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module, "is_remote_endpoint", lambda: True)
    monkeypatch.setattr(
        windows_module, "check_api_reachable", lambda: (True, True)
    )
    monkeypatch.setattr(
        windows_module, "get_api_loaded_models", lambda: []
    )

    assert "A model is loaded" in tray._collect_status_text()  # nosec B101


def test_collect_status_text_reports_lms_failure(
    windows_module, monkeypatch
):
    """A crashing `lms ps` is surfaced rather than swallowed."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "running", "stopped")
    monkeypatch.setattr(windows_module, "get_lms_cmd", lambda: r"C:\lms.exe")

    def _raise(_cmd):
        """Simulate lms failing to launch."""
        raise OSError("access denied")

    monkeypatch.setattr(windows_module, "_run_safe_command", _raise)

    assert "Error running lms ps" in tray._collect_status_text()  # nosec B101


def test_collect_status_text_without_lms_output(windows_module, monkeypatch):
    """Empty `lms ps` output reads as no model loaded."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "running", "stopped")
    monkeypatch.setattr(windows_module, "get_lms_cmd", lambda: r"C:\lms.exe")
    monkeypatch.setattr(
        windows_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=0, stdout="   "),
    )

    assert "No model loaded" in tray._collect_status_text()  # nosec B101


def test_about_dialog_names_version_and_repo(windows_module, monkeypatch):
    """About shows the version, maintainer and project links."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module._AppState, "APP_VERSION", "v9.9.9")
    shown = []
    monkeypatch.setattr(
        windows_module,
        "_show_tk_message",
        lambda title, message: shown.append((title, message)) or True,
    )

    tray.show_about_dialog()

    title, message = shown[0]
    assert title == "About"  # nosec B101
    assert "v9.9.9" in message  # nosec B101
    assert windows_module.APP_REPOSITORY in message  # nosec B101


def test_config_dialog_saves_valid_endpoint(windows_module, monkeypatch):
    """A valid host:port is persisted and applied."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module,
        "_prompt_tk_endpoint",
        lambda _current: "10.0.0.7:4321",
    )
    saved = []
    monkeypatch.setattr(
        windows_module,
        "save_config",
        lambda host, port: saved.append((host, port)),
    )
    _stub_statuses(windows_module, monkeypatch, "stopped", "stopped")

    tray.show_config_dialog()

    assert saved == [("10.0.0.7", 4321)]  # nosec B101
    assert windows_module._AppState.API_HOST == "10.0.0.7"  # nosec B101
    assert windows_module._AppState.API_PORT == 4321  # nosec B101


def test_config_dialog_cancelled(windows_module, monkeypatch):
    """Cancelling leaves the configuration untouched."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module, "_prompt_tk_endpoint", lambda _current: None
    )

    def fail(*_args):
        """Fail the test if a cancelled dialog still saved."""
        pytest.fail("cancelled dialog wrote the configuration")

    monkeypatch.setattr(windows_module, "save_config", fail)

    tray.show_config_dialog()


def test_config_dialog_rejects_invalid_input(windows_module, monkeypatch):
    """Malformed input is refused with an explanation."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module,
        "_prompt_tk_endpoint",
        lambda _current: "not an endpoint!",
    )

    def fail(*_args):
        """Fail the test if invalid input reached the config file."""
        pytest.fail("invalid endpoint was saved")

    monkeypatch.setattr(windows_module, "save_config", fail)
    shown = []
    monkeypatch.setattr(
        windows_module,
        "_show_tk_message",
        lambda title, message: shown.append(message) or True,
    )

    tray.show_config_dialog()

    assert "host:port" in shown[0]  # nosec B101


def test_config_dialog_reports_save_failure(windows_module, monkeypatch):
    """A config file that cannot be written is reported."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module,
        "_prompt_tk_endpoint",
        lambda _current: "127.0.0.1:1234",
    )

    def _raise(*_args):
        """Simulate a read-only config directory."""
        raise OSError("read-only")

    monkeypatch.setattr(windows_module, "save_config", _raise)
    shown = []
    monkeypatch.setattr(
        windows_module,
        "_show_tk_message",
        lambda title, message: shown.append(message) or True,
    )

    tray.show_config_dialog()

    assert "Could not save" in shown[0]  # nosec B101


# ---------------------------------------------------------------------
# tkinter helpers
# ---------------------------------------------------------------------


def test_run_tk_dialog_without_tkinter(windows_module, monkeypatch):
    """Without tkinter the dialog reports failure instead of raising."""
    monkeypatch.setattr(windows_module, "_tk_lib", None)

    assert (  # nosec B101
        windows_module._run_tk_dialog(lambda _root: None) is False
    )


def test_run_tk_dialog_builds_and_tears_down(windows_module, monkeypatch):
    """The root is created, handed to the builder, and destroyed."""
    events = []

    class FakeRoot:
        """Minimal Tk root recording its lifecycle."""

        def title(self, _text):
            """Accept the window title."""

        def iconphoto(self, *_args):
            """Accept the window icon."""

        def mainloop(self):
            """Record that the event loop ran."""
            events.append("mainloop")

        def destroy(self):
            """Record teardown."""
            events.append("destroy")

    monkeypatch.setattr(
        windows_module,
        "_tk_lib",
        SimpleNamespace(
            Tk=FakeRoot, PhotoImage=lambda **_kwargs: object()
        ),
    )
    monkeypatch.setattr(windows_module, "get_asset_path", lambda *_p: None)

    shown = windows_module._run_tk_dialog(
        lambda _root: events.append("build")
    )

    assert shown is True  # nosec B101
    assert events == ["build", "mainloop", "destroy"]  # nosec B101


def test_run_tk_dialog_survives_missing_display(windows_module, monkeypatch):
    """A root that cannot be created is reported, not raised."""
    def _raise():
        """Simulate a session with no window station."""
        raise RuntimeError("no display")

    monkeypatch.setattr(
        windows_module, "_tk_lib", SimpleNamespace(Tk=_raise)
    )

    assert (  # nosec B101
        windows_module._run_tk_dialog(lambda _root: None) is False
    )


def test_run_tk_dialog_survives_builder_errors(windows_module, monkeypatch):
    """A builder that raises still tears the window down."""
    destroyed = []

    class FakeRoot:
        """Minimal Tk root recording teardown."""

        def title(self, _text):
            """Accept the window title."""

        def mainloop(self):
            """Never reached in this test."""

        def destroy(self):
            """Record teardown."""
            destroyed.append(True)

    monkeypatch.setattr(
        windows_module, "_tk_lib", SimpleNamespace(Tk=FakeRoot)
    )
    monkeypatch.setattr(windows_module, "get_asset_path", lambda *_p: None)

    def _raise(_root):
        """Simulate a widget failing to build."""
        raise ValueError("bad widget")

    assert windows_module._run_tk_dialog(_raise) is False  # nosec B101
    assert destroyed == [True]  # nosec B101


def test_prompt_tk_endpoint_returns_none_when_unavailable(
    windows_module, monkeypatch
):
    """A dialog that cannot be shown reads as a cancellation."""
    monkeypatch.setattr(windows_module, "_tk_lib", None)

    assert windows_module._prompt_tk_endpoint("host:1") is None  # nosec B101


def test_show_tk_message_without_tkinter(windows_module, monkeypatch):
    """The message dialog reports failure when tkinter is missing."""
    monkeypatch.setattr(windows_module, "_tk_lib", None)

    assert windows_module._show_tk_message("t", "m") is False  # nosec B101


# ---------------------------------------------------------------------
# Update check
# ---------------------------------------------------------------------


def test_check_updates_skipped_for_dev_build(windows_module, monkeypatch):
    """A dev build has no release to compare against."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module._AppState, "APP_VERSION",
        windows_module.DEFAULT_APP_VERSION,
    )

    assert tray.check_updates() is False  # nosec B101
    assert tray.update_status == "Dev build"  # nosec B101


def test_check_updates_notifies_once_per_version(
    windows_module, monkeypatch
):
    """A newer release notifies once, not on every check."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module._AppState, "APP_VERSION", "v1.0.0")
    monkeypatch.setattr(
        windows_module,
        "get_latest_release_version",
        lambda: ("v2.0.0", None),
    )

    assert tray.check_updates() is True  # nosec B101
    assert tray.check_updates() is False  # nosec B101
    assert len(tray.icon.notifications) == 1  # nosec B101


def test_check_updates_up_to_date(windows_module, monkeypatch):
    """A current version reports up to date and stays quiet."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module._AppState, "APP_VERSION", "v2.0.0")
    monkeypatch.setattr(
        windows_module,
        "get_latest_release_version",
        lambda: ("v2.0.0", None),
    )

    assert tray.check_updates() is False  # nosec B101
    assert tray.update_status == "Up to date"  # nosec B101
    assert tray.icon.notifications == []  # nosec B101


def test_check_updates_ahead_of_release(windows_module, monkeypatch):
    """A local build newer than the latest release is flagged as ahead."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module._AppState, "APP_VERSION", "v3.0.0")
    monkeypatch.setattr(
        windows_module,
        "get_latest_release_version",
        lambda: ("v2.0.0", None),
    )

    assert tray.check_updates() is False  # nosec B101
    assert tray.update_status == "Ahead of release"  # nosec B101


def test_check_updates_handles_lookup_failure(windows_module, monkeypatch):
    """A failed lookup records the error without notifying."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module._AppState, "APP_VERSION", "v1.0.0")
    monkeypatch.setattr(
        windows_module,
        "get_latest_release_version",
        lambda: (None, "Network or parse error"),
    )

    assert tray.check_updates() is False  # nosec B101
    assert tray.update_status == "Unknown"  # nosec B101
    assert tray.last_update_error == "Network or parse error"  # nosec B101


@pytest.mark.parametrize(
    "status,fragment",
    [
        ("Up to date", "up to date"),
        ("Dev build", "Dev build"),
        ("Ahead of release", "Ahead of release"),
        ("Unknown", "Unable to check"),
    ],
)
def test_manual_check_updates_messages(
    windows_module, monkeypatch, status, fragment
):
    """An on-demand check reports where the version stands."""
    tray = _make_tray(windows_module)
    tray.update_status = status
    monkeypatch.setattr(windows_module._AppState, "APP_VERSION", "v2.0.0")
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "check_updates", lambda _self: False
    )
    shown = []
    monkeypatch.setattr(
        windows_module,
        "_show_tk_message",
        lambda title, message: shown.append((title, message)) or True,
    )

    tray.manual_check_updates()

    assert shown[0][0] == "Update Check"  # nosec B101
    assert fragment in shown[0][1]  # nosec B101


def test_manual_check_updates_shows_release_url(windows_module, monkeypatch):
    """A pending update that was already notified still shows its link."""
    tray = _make_tray(windows_module)
    tray.update_status = "Update available"
    tray.latest_update_version = "v9.9.9"
    monkeypatch.setattr(windows_module._AppState, "APP_VERSION", "v1.0.0")
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "check_updates", lambda _self: False
    )
    shown = []
    monkeypatch.setattr(
        windows_module,
        "_show_tk_message",
        lambda title, message: shown.append(message) or True,
    )

    tray.manual_check_updates()

    assert "v9.9.9" in shown[0]  # nosec B101
    assert windows_module.get_release_url("v9.9.9") in shown[0]  # nosec B101


def test_manual_check_updates_reports_lookup_error(
    windows_module, monkeypatch
):
    """A failed lookup names the reason it failed."""
    tray = _make_tray(windows_module)
    tray.update_status = "Unknown"
    tray.last_update_error = "TLS certificate error"
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "check_updates", lambda _self: False
    )
    shown = []
    monkeypatch.setattr(
        windows_module,
        "_show_tk_message",
        lambda title, message: shown.append(message) or True,
    )

    tray.manual_check_updates()

    assert "TLS certificate error" in shown[0]  # nosec B101


def test_manual_check_updates_stays_quiet_after_notifying(
    windows_module, monkeypatch
):
    """When the check already notified, no second dialog appears."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "check_updates", lambda _self: True
    )

    def fail(*_args):
        """Fail the test if a redundant dialog is shown."""
        pytest.fail("dialog shown after a notification had been sent")

    monkeypatch.setattr(windows_module, "_show_tk_message", fail)

    tray.manual_check_updates()


# ---------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------


def test_run_starts_icon_and_threads(windows_module, monkeypatch):
    """Running the tray makes the icon visible and starts monitoring."""
    tray = _make_tray(windows_module)
    _stub_statuses(windows_module, monkeypatch, "stopped", "stopped")
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_start_background_threads",
        lambda _self: None,
    )

    tray.run()

    assert tray.icon.ran is True  # nosec B101
    assert tray.icon.visible is True  # nosec B101
    assert tray.last_status == "WARN"  # nosec B101


def test_on_icon_ready_survives_failing_first_check(
    windows_module, monkeypatch
):
    """A failing first status check does not stop the tray coming up."""
    tray = _make_tray(windows_module)

    def _raise(_self):
        """Simulate the first check blowing up."""
        raise ValueError("boom")

    monkeypatch.setattr(windows_module.WindowsTrayIcon, "check_model", _raise)
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_start_background_threads",
        lambda _self: None,
    )

    tray._on_icon_ready()


def test_background_threads_honour_auto_start_flags(
    windows_module, monkeypatch
):
    """--auto-start-daemon and --gui each get their own worker."""
    tray = _make_tray(windows_module)
    monkeypatch.setattr(windows_module._AppState, "AUTO_START_DAEMON", True)
    monkeypatch.setattr(windows_module._AppState, "GUI_MODE", True)

    started = []
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_status_loop",
        lambda _self: started.append("status"),
    )
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_update_loop",
        lambda _self: started.append("updates"),
    )
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_maybe_auto_start_daemon",
        lambda _self: started.append("auto-daemon"),
    )
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_maybe_start_gui",
        lambda _self: started.append("auto-gui"),
    )

    tray._start_background_threads()

    assert started == [  # nosec B101
        "status", "updates", "auto-daemon", "auto-gui",
    ]


def test_quit_stops_icon_and_threads(windows_module):
    """Quitting signals the monitoring loops and stops the icon."""
    tray = _make_tray(windows_module)

    tray.quit_app()

    assert tray.icon.stopped is True  # nosec B101
    assert getattr(tray, "_stop_event").is_set() is True  # nosec B101


def test_quit_survives_icon_errors(windows_module):
    """A tray icon that is already gone does not break quitting."""
    tray = _make_tray(windows_module)

    def _raise():
        """Simulate stopping an icon that no longer exists."""
        raise RuntimeError("already stopped")

    tray.icon.stop = _raise

    tray.quit_app()

    assert getattr(tray, "_stop_event").is_set() is True  # nosec B101


def test_status_loop_exits_on_quit(windows_module, monkeypatch):
    """The monitoring loop ends as soon as the quit event is set."""
    tray = _make_tray(windows_module)
    getattr(tray, "_stop_event").set()

    def fail(_self):
        """Fail the test if the loop ran a check after quitting."""
        pytest.fail("status loop ran after quit")

    monkeypatch.setattr(windows_module.WindowsTrayIcon, "check_model", fail)

    tray._status_loop()


def test_update_loop_exits_on_quit(windows_module, monkeypatch):
    """The update loop ends as soon as the quit event is set."""
    tray = _make_tray(windows_module)
    getattr(tray, "_stop_event").set()

    def fail(_self):
        """Fail the test if the loop ran a check after quitting."""
        pytest.fail("update loop ran after quit")

    monkeypatch.setattr(windows_module.WindowsTrayIcon, "check_updates", fail)

    tray._update_loop()


class _CountdownEvent:
    """Stop event that stays clear for a fixed number of waits.

    Lets a monitoring loop run a known number of iterations and then exit,
    without any real waiting.
    """

    def __init__(self, clear_waits):
        """Allow ``clear_waits`` iterations before reporting quit."""
        self.remaining = clear_waits
        self.intervals = []

    def wait(self, timeout=None):
        """Return False while iterations remain, then True."""
        self.intervals.append(timeout)
        if self.remaining > 0:
            self.remaining -= 1
            return False
        return True

    def set(self):
        """Mark the event as set."""
        self.remaining = 0

    def is_set(self):
        """Report whether the loop should stop."""
        return self.remaining == 0


def test_status_loop_checks_on_each_interval(windows_module, monkeypatch):
    """The loop re-checks status once per interval until quit."""
    tray = _make_tray(windows_module)
    setattr(tray, "_stop_event", _CountdownEvent(2))

    checks = []
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "check_model",
        lambda _self: checks.append(True),
    )

    tray._status_loop()

    assert len(checks) == 2  # nosec B101
    assert getattr(tray, "_stop_event").intervals[0] == (  # nosec B101
        windows_module.INTERVAL
    )


def test_status_loop_survives_a_failing_check(windows_module, monkeypatch):
    """One failing check does not end the monitoring thread."""
    tray = _make_tray(windows_module)
    setattr(tray, "_stop_event", _CountdownEvent(2))

    calls = []

    def _raise(_self):
        """Fail the first check, succeed the second."""
        calls.append(True)
        if len(calls) == 1:
            raise ValueError("boom")

    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "check_model", _raise
    )

    tray._status_loop()

    assert len(calls) == 2  # nosec B101


def test_update_loop_checks_then_waits_a_day(windows_module, monkeypatch):
    """The first check is prompt; the next is a day later."""
    tray = _make_tray(windows_module)
    setattr(tray, "_stop_event", _CountdownEvent(1))

    checks = []
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "check_updates",
        lambda _self: checks.append(True),
    )

    tray._update_loop()

    intervals = getattr(tray, "_stop_event").intervals
    assert len(checks) == 1  # nosec B101
    assert intervals[0] == 5  # nosec B101
    assert intervals[1] == windows_module.UPDATE_CHECK_INTERVAL  # nosec B101


def test_update_loop_survives_a_failing_check(windows_module, monkeypatch):
    """A failing update check does not end the thread."""
    tray = _make_tray(windows_module)
    setattr(tray, "_stop_event", _CountdownEvent(1))

    def _raise(_self):
        """Simulate the update check blowing up."""
        raise ValueError("boom")

    monkeypatch.setattr(
        windows_module.WindowsTrayIcon, "check_updates", _raise
    )

    tray._update_loop()


def test_on_icon_ready_survives_visibility_error(
    windows_module, monkeypatch
):
    """An icon that refuses to become visible does not abort startup."""
    tray = _make_tray(windows_module)

    class StubbornIcon:
        """Icon whose visibility cannot be set."""

        title = ""

        @property
        def visible(self):
            """Report the icon as hidden."""
            return False

        @visible.setter
        def visible(self, _value):
            """Reject the assignment the way a dead icon would."""
            raise OSError("no notification area")

    tray.icon = StubbornIcon()
    checked = []
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "check_model",
        lambda _self: checked.append(True),
    )
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_start_background_threads",
        lambda _self: None,
    )

    tray._on_icon_ready()

    assert checked == [True]  # nosec B101


def test_auto_start_daemon_flag(windows_module, monkeypatch):
    """--auto-start-daemon stops any stale daemon, then starts a fresh one."""
    tray = _make_tray(windows_module)
    order = []
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_stop_daemon_with_notification",
        lambda _self: order.append("stop") or (True, None),
    )
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "start_daemon",
        lambda _self: order.append("start"),
    )

    tray._maybe_auto_start_daemon()

    assert order == ["stop", "start"]  # nosec B101


def test_auto_start_daemon_survives_stop_failure(windows_module, monkeypatch):
    """A failing pre-emptive stop does not prevent the start."""
    tray = _make_tray(windows_module)

    def _raise(_self):
        """Simulate the stop attempt failing."""
        raise OSError("boom")

    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "_stop_daemon_with_notification",
        _raise,
    )
    started = []
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "start_daemon",
        lambda _self: started.append(True),
    )

    tray._maybe_auto_start_daemon()

    assert started == [True]  # nosec B101


def test_gui_flag_starts_desktop_app(windows_module, monkeypatch):
    """--gui launches the desktop app at startup."""
    tray = _make_tray(windows_module)
    started = []
    monkeypatch.setattr(
        windows_module.WindowsTrayIcon,
        "start_desktop_app",
        lambda _self: started.append(True),
    )

    tray._maybe_start_gui()

    assert started == [True]  # nosec B101
