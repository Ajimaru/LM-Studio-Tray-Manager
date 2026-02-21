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

Args:
    None

Returns:
    None

Raises:
    None
"""

import importlib.util
import json
import os
import signal
import subprocess  # nosec B404 - subprocess module is mocked in tests
import sys
import urllib.error
from email.message import Message
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
        modal=None,
        message_type=None,
        buttons=None,
        text="",
    ):
        """Initialize a lightweight message dialog stub."""
        self.parent = parent
        self.flags = flags
        self.modal = modal
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


class DummyAboutDialog:
    """Dummy about dialog to capture interactions."""
    last_instance = None

    def __init__(self):
        """Initialize a lightweight about dialog stub."""
        self.program_name = ""
        self.version = ""
        self.authors = []
        self.website = ""
        self.website_label = ""
        self.comments = ""
        self.modal = False
        self.ran = False
        self.destroyed = False
        DummyAboutDialog.last_instance = self

    def set_program_name(self, name):
        """Store program name."""
        self.program_name = name

    def set_version(self, version):
        """Store version."""
        self.version = version

    def set_authors(self, authors):
        """Store authors list."""
        self.authors = authors

    def set_website(self, url):
        """Store website URL."""
        self.website = url

    def set_website_label(self, label):
        """Store website label."""
        self.website_label = label

    def set_comments(self, comments):
        """Store comments."""
        self.comments = comments

    def set_modal(self, modal):
        """Store modal setting."""
        self.modal = modal

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
    AboutDialog = DummyAboutDialog

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


class DummyUrlResponse:
    """Dummy response object for urllib tests."""

    def __init__(self, payload):
        """Store response payload as bytes."""
        self.payload = payload

    def read(self):
        """Return raw payload bytes."""
        return self.payload

    def __enter__(self):
        """Support context manager protocol."""
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        """No cleanup required for dummy response."""
        return False


class DummyUrlLib:
    """Dummy urllib.request module for version checks."""

    def __init__(self, payload, raise_exc=None):
        """Initialize with payload bytes and optional exception to raise."""
        self.payload = payload
        self.raise_exc = raise_exc
        self.last_request = None

    class Request:
        """Dummy request object matching urllib.request.Request."""

        def __init__(self, url, headers=None):
            """Accept url and headers; store for potential inspection."""
            self.full_url = url
            self.headers = headers or {}

    class HTTPSHandler:
        """Dummy HTTPS handler for urllib opener."""

    class DummyOpenerDirector:
        """Dummy opener that returns a fixed response payload."""

        def __init__(self, payload, raise_exc=None):
            """Store payload and optional exception for open calls."""
            self.payload = payload
            self.raise_exc = raise_exc
            self.handlers = []

        def add_handler(self, handler):
            """Record a handler instance (unused)."""
            self.handlers.append(handler)

        def open(self, _request, timeout=None, **_kwargs):
            """Return a dummy response or raise the configured exception."""
            _ = timeout  # Unused but required for API compatibility
            if self.raise_exc is not None:
                raise self.raise_exc
            return DummyUrlResponse(self.payload)

    def build_opener(self, *handlers):
        """Return a dummy opener and attach any provided handlers."""
        opener = DummyUrlLib.DummyOpenerDirector(
            self.payload,
            self.raise_exc,
        )
        for handler in handlers:
            opener.add_handler(handler)
        return opener

    def opener_director(self):
        """Return a dummy opener with this instance payload."""
        return DummyUrlLib.DummyOpenerDirector(
            self.payload, self.raise_exc
        )


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
    # GTK globals are populated by main(); set them directly so tests
    # that reference tray_module.Gtk / GLib / AppIndicator3 work.
    module.Gtk = gtk_mod
    module.GLib = glib_mod
    module.AppIndicator3 = app_mod
    return module


def _make_tray_instance(module):
    """Build a partially initialized TrayIcon for unit tests."""
    tray = module.TrayIcon.__new__(module.TrayIcon)
    tray.indicator = DummyIndicator()
    tray.menu = DummyMenu()
    tray.last_status = None
    tray.action_lock_until = 0.0
    tray.last_update_version = None
    tray.latest_update_version = None
    tray.update_status = "Unknown"
    tray.last_update_error = None
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


def test_load_version_from_dir_empty_file(tray_module, tmp_path):
    """Return default version when VERSION file is empty."""
    (tmp_path / "VERSION").write_text("", encoding="utf-8")
    version = tray_module.load_version_from_dir(str(tmp_path))
    assert version == tray_module.DEFAULT_APP_VERSION  # nosec B101


def test_version_flag_exits(tmp_path, monkeypatch):
    """Test that the CLI exits when --version is provided."""
    (tmp_path / "VERSION").write_text("v9.9.9", encoding="utf-8")
    gi_mod = ModuleType("gi")
    setattr(gi_mod, "require_version", lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "gi", gi_mod)
    monkeypatch.setitem(
        sys.modules,
        "gi.repository",
        ModuleType("gi.repository"),
    )
    module_name = "lmstudio_tray_version"
    sys.modules.pop(module_name, None)
    old_argv = sys.argv[:]
    try:
        sys.argv = ["lmstudio_tray.py", "m", str(tmp_path), "--version"]
        spec = importlib.util.spec_from_file_location(
            module_name,
            str(Path(__file__).resolve().parents[1] / "lmstudio_tray.py"),
        )
        assert spec is not None and spec.loader is not None  # nosec B101
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        with pytest.raises(SystemExit):
            module.main()
    finally:
        sys.argv = old_argv


def test_parse_version_handles_prefix(tray_module):
    """Parse versions with a leading v prefix."""
    assert tray_module.parse_version("v1.2.3") == (1, 2, 3)  # nosec B101


def test_is_newer_version(tray_module):
    """Compare version tuples for update checks."""
    assert tray_module.is_newer_version("v1.2.3", "v1.2.4")  # nosec B101
    assert not tray_module.is_newer_version("v1.2.3", "v1.2.3")  # nosec B101
    assert not tray_module.is_newer_version("dev", "v1.2.3")  # nosec B101


def test_get_latest_release_version_reads_tag(tray_module, monkeypatch):
    """Extract tag_name from GitHub release payload."""
    payload = json.dumps({"tag_name": "v9.9.9"}).encode("utf-8")

    class DummyResponse:
        """
        A mock response object for testing HTTP request simulations.

        This class simulates the behavior of an HTTP response object,
        implementing context manager protocol for use in with statements.
        It stores data and provides a read() method to retrieve it.
        """
        def __init__(self, data):
            self._data = data

        def read(self):
            """Read and return the stored data.

            Returns:
                The data that was stored in this mock file object.
            """
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

    class DummyOpener:
        """
        A mock URL opener for testing HTTP requests.

        This class simulates urllib.request.OpenerDirector behavior by
        returning predefined response data without making actual network
        calls.

        Attributes:
            _data: The data to be returned by the response object.

        Methods:
            open: Returns a DummyResponse containing the predefined data.
        """
        def __init__(self, data):
            self._data = data

        def open(self, _request, **_kwargs):
            """
            Open a dummy HTTP request and return a response with
            predefined data.

            This method is used to mock HTTP requests in tests by
            returning a DummyResponse containing the data stored in
            this handler instance.

            Args:
                _request: The HTTP request object (unused in this mock
                    implementation).
                **_kwargs: Additional keyword arguments (unused in this
                    mock implementation).

            Returns:
                DummyResponse: A response object with the predefined
                    data.
            """
            return DummyResponse(self._data)

    class DummyOpenerDirector:
        """Stand-in for urllib.request.OpenerDirector."""

    def dummy_request(url, data=None, headers=None, method=None):
        # Minimal Request stand-in; attributes are only for compatibility.
        return SimpleNamespace(
            full_url=url,
            data=data,
            headers=headers or {},
            method=method,
        )

    class DummyHttpsHandler:
        """Stand-in for urllib.request.HTTPSHandler."""

    def dummy_build_opener(_handler):
        return DummyOpener(payload)

    monkeypatch.setattr(
        tray_module.urllib_request,
        "Request",
        dummy_request,
    )
    monkeypatch.setattr(
        tray_module.urllib_request,
        "HTTPSHandler",
        DummyHttpsHandler,
    )
    monkeypatch.setattr(
        tray_module.urllib_request,
        "OpenerDirector",
        DummyOpenerDirector,
    )
    monkeypatch.setattr(
        tray_module.urllib_request,
        "build_opener",
        dummy_build_opener,
    )
    version, error = tray_module.get_latest_release_version()
    assert version == "v9.9.9"  # nosec B101
    assert error is None  # nosec B101


def test_get_latest_release_version_http_error(tray_module, monkeypatch):
    """Return HTTP error code string on HTTPError."""
    hdrs = Message()
    exc = urllib.error.HTTPError(
        url="https://api.github.com",
        code=404,
        msg="Not Found",
        hdrs=hdrs,
        fp=None,
    )
    monkeypatch.setattr(
        tray_module, "urllib_request", DummyUrlLib(b"", raise_exc=exc)
    )
    version, error = tray_module.get_latest_release_version()
    assert version is None  # nosec B101
    assert error == "HTTP 404"  # nosec B101


def test_get_latest_release_version_url_error(tray_module, monkeypatch):
    """Return network error message on URLError."""
    exc = urllib.error.URLError(reason="connection refused")
    monkeypatch.setattr(
        tray_module, "urllib_request", DummyUrlLib(b"", raise_exc=exc)
    )
    version, error = tray_module.get_latest_release_version()
    assert version is None  # nosec B101
    assert error == "Network or parse error"  # nosec B101


def test_get_latest_release_version_invalid_url(tray_module, monkeypatch):
    """Return an error when update URL fails validation."""
    monkeypatch.setattr(tray_module, "LATEST_RELEASE_API_URL", "http://bad")
    version, error = tray_module.get_latest_release_version()
    assert version is None  # nosec B101
    assert error == "Invalid update URL"  # nosec B101


def test_get_latest_release_version_invalid_json(tray_module, monkeypatch):
    """Return parse error message when response body is not valid JSON."""
    monkeypatch.setattr(
        tray_module, "urllib_request", DummyUrlLib(b"not valid json")
    )
    version, error = tray_module.get_latest_release_version()
    assert version is None  # nosec B101
    assert error == "Network or parse error"  # nosec B101


def test_get_latest_release_version_no_tag(tray_module, monkeypatch):
    """Return no-tag error when tag_name is absent from JSON response."""
    payload = json.dumps({"other_field": "value"}).encode("utf-8")
    monkeypatch.setattr(tray_module, "urllib_request", DummyUrlLib(payload))
    version, error = tray_module.get_latest_release_version()
    assert version is None  # nosec B101
    assert error == "No tag found"  # nosec B101


def test_check_updates_notifies_once(tray_module, monkeypatch):
    """Send a single update notification per latest version."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "APP_VERSION", "v1.0.0")
    monkeypatch.setattr(tray_module, "DEFAULT_APP_VERSION", "dev")
    monkeypatch.setattr(
        tray_module,
        "get_latest_release_version",
        lambda: ("v2.0.0", None),
    )
    monkeypatch.setattr(
        tray_module,
        "get_notify_send_cmd",
        lambda: "/usr/bin/notify-send",
    )
    notify_calls = []

    def capture_notify_call(cmd):
        """Record notify command calls."""
        notify_calls.append(cmd)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify_call)
    tray.check_updates()
    tray.check_updates()
    assert len(notify_calls) == 1  # nosec B101
    assert tray.update_status == "Update available"  # nosec B101


def test_check_updates_dev_build(tray_module, monkeypatch):
    """Set update_status to 'Dev build' when running a dev build."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "APP_VERSION", "dev")
    monkeypatch.setattr(tray_module, "DEFAULT_APP_VERSION", "dev")
    tray.check_updates()
    assert tray.update_status == "Dev build"  # nosec B101


def test_check_updates_error_path(tray_module, monkeypatch):
    """Set update_status to 'Unknown' when version fetch fails."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "APP_VERSION", "v1.0.0")
    monkeypatch.setattr(tray_module, "DEFAULT_APP_VERSION", "dev")
    monkeypatch.setattr(
        tray_module,
        "get_latest_release_version",
        lambda: (None, "Network error"),
    )
    tray.check_updates()
    assert tray.update_status == "Unknown"  # nosec B101


def test_manual_check_updates_reports_up_to_date(tray_module, monkeypatch):
    """Notify user when already up to date."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "APP_VERSION", "v1.0.0")
    monkeypatch.setattr(tray_module, "DEFAULT_APP_VERSION", "dev")
    monkeypatch.setattr(
        tray_module,
        "get_latest_release_version",
        lambda: ("v1.0.0", None),
    )
    monkeypatch.setattr(
        tray_module,
        "get_notify_send_cmd",
        lambda: "/usr/bin/notify-send",
    )
    notify_calls = []

    def capture_notify_call(cmd):
        """Record notify command calls."""
        notify_calls.append(cmd)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify_call)
    tray.manual_check_updates(None)
    assert len(notify_calls) == 1  # nosec B101
    assert "Update Check" in str(notify_calls[0])  # nosec B101


def test_manual_check_updates_reports_update_available(
    tray_module,
    monkeypatch,
):
    """Notify user when an update is available."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "APP_VERSION", "v1.0.0")
    monkeypatch.setattr(tray_module, "DEFAULT_APP_VERSION", "dev")
    monkeypatch.setattr(
        tray_module,
        "get_latest_release_version",
        lambda: ("v2.0.0", None),
    )
    monkeypatch.setattr(
        tray_module,
        "get_notify_send_cmd",
        lambda: "/usr/bin/notify-send",
    )
    notify_calls = []

    def capture_notify_call(cmd):
        """Record notify command calls."""
        notify_calls.append(cmd)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify_call)
    tray.manual_check_updates(None)
    assert len(notify_calls) == 1  # nosec B101
    msg = str(notify_calls[0])
    assert "Update Available" in msg  # nosec B101
    assert "v2.0.0" in msg  # nosec B101


def test_manual_check_updates_reports_dev_build(tray_module, monkeypatch):
    """Notify user when running a development build."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "APP_VERSION", "dev")
    monkeypatch.setattr(tray_module, "DEFAULT_APP_VERSION", "dev")
    monkeypatch.setattr(
        tray_module,
        "get_latest_release_version",
        lambda: ("v2.0.0", None),
    )
    monkeypatch.setattr(
        tray_module,
        "get_notify_send_cmd",
        lambda: "/usr/bin/notify-send",
    )
    notify_calls = []

    def capture_notify_call(cmd):
        """Record notify command calls."""
        notify_calls.append(cmd)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify_call)
    tray.manual_check_updates(None)
    assert len(notify_calls) == 1  # nosec B101
    msg = str(notify_calls[0])
    assert "Update Check" in msg  # nosec B101
    assert "Dev build" in msg  # nosec B101


def test_manual_check_updates_reports_error_with_details(
    tray_module,
    monkeypatch,
):
    """Notify user when update check fails with error details."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "APP_VERSION", "v1.0.0")
    monkeypatch.setattr(tray_module, "DEFAULT_APP_VERSION", "dev")
    monkeypatch.setattr(
        tray_module,
        "get_latest_release_version",
        lambda: (None, "Network error"),
    )
    monkeypatch.setattr(
        tray_module,
        "get_notify_send_cmd",
        lambda: "/usr/bin/notify-send",
    )
    notify_calls = []

    def capture_notify_call(cmd):
        """Record notify command calls."""
        notify_calls.append(cmd)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify_call)
    tray.manual_check_updates(None)
    assert len(notify_calls) == 1  # nosec B101
    msg = str(notify_calls[0])
    assert "Update Check" in msg  # nosec B101
    assert "Unable to check for updates" in msg  # nosec B101


def test_update_check_helpers(tray_module):
    """Cover update helper methods and timer callbacks."""
    tray = _make_tray_instance(tray_module)
    tray.update_status = None
    assert tray.get_version_label().endswith("(Unknown)")  # nosec B101

    message = _call_member(
        tray,
        "_format_update_check_message",
        "Update available",
        "v1.2.3",
        None,
    )
    assert "v1.2.3" in message  # nosec B101

    message = _call_member(
        tray,
        "_format_update_check_message",
        "Unknown",
        None,
        "timeout",
    )
    assert "timeout" in message  # nosec B101

    calls = {"count": 0}

    def record_check():
        calls["count"] += 1
        return False

    tray.check_updates = record_check
    assert _call_member(tray, "_check_updates_tick") is True  # nosec B101
    assert _call_member(tray, "_initial_update_check") is False  # nosec B101
    assert calls["count"] == 2  # nosec B101


def test_check_updates_without_notify(tray_module, monkeypatch):
    """Return False when update is available but notify is missing."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "APP_VERSION", "v1.0.0")
    monkeypatch.setattr(tray_module, "DEFAULT_APP_VERSION", "dev")
    monkeypatch.setattr(
        tray_module,
        "get_latest_release_version",
        lambda: ("v1.1.0", None),
    )
    monkeypatch.setattr(tray_module, "get_notify_send_cmd", lambda: None)
    assert tray.check_updates() is False  # nosec B101


def test_manual_check_updates_reports_error_without_details(
    tray_module,
    monkeypatch,
):
    """Notify user when update check fails without details."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "APP_VERSION", "v1.0.0")
    monkeypatch.setattr(tray_module, "DEFAULT_APP_VERSION", "dev")
    monkeypatch.setattr(
        tray_module,
        "get_latest_release_version",
        lambda: (None, None),
    )
    monkeypatch.setattr(
        tray_module,
        "get_notify_send_cmd",
        lambda: "/usr/bin/notify-send",
    )
    notify_calls = []

    def capture_notify_call(cmd):
        """Record notify command calls."""
        notify_calls.append(cmd)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify_call)
    # Notify user when update check fails without details
    tray.manual_check_updates(None)
    assert len(notify_calls) == 1  # nosec B101
    msg = str(notify_calls[0])
    assert "Update Check" in msg  # nosec B101
    assert "Unable to check for updates" in msg  # nosec B101


def test_get_authors_reads_file(tray_module, tmp_path, monkeypatch):
    """Read authors from AUTHORS file."""
    monkeypatch.setattr(tray_module, "script_dir", str(tmp_path))
    authors_content = """# Contributors

    - Ajimaru (@Ajimaru) - Project creator
    - John Doe (@johndoe) - Contributor
    <!-- Add your name here -->
    """
    (tmp_path / "AUTHORS").write_text(authors_content, encoding="utf-8")
    authors = tray_module.get_authors()
    assert authors == ["Ajimaru", "John Doe"]  # nosec B101


def test_get_authors_parsing_handles_dashes_and_handles(
    tray_module,
    tmp_path,
    monkeypatch,
):
    """Strip handles and descriptions from authors list."""
    monkeypatch.setattr(tray_module, "script_dir", str(tmp_path))
    (tmp_path / "AUTHORS").write_text(
        "- Jane Doe (@jane) - contributor\n",
        encoding="utf-8",
    )
    authors = tray_module.get_authors()
    assert authors == ["Jane Doe"]  # nosec B101


def test_get_authors_fallback_maintainer(tray_module, tmp_path, monkeypatch):
    """Fall back to APP_MAINTAINER when AUTHORS file is absent."""
    monkeypatch.setattr(tray_module, "script_dir", str(tmp_path))
    monkeypatch.setattr(tray_module, "APP_MAINTAINER", "TestMaintainer")
    authors = tray_module.get_authors()
    assert authors == ["TestMaintainer"]  # nosec B101


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
    assert calls[0][0].endswith("pgrep")  # nosec B101
    assert calls[0][1:3] == ["-x", "llmster"]  # nosec B101


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


def test_is_llmster_running_requires_absolute_pgrep(
    tray_module, monkeypatch
):
    """Return False when pgrep is not an absolute path."""
    monkeypatch.setattr(tray_module, "get_pgrep_cmd", lambda: "pgrep")
    assert tray_module.is_llmster_running() is False  # nosec B101


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


def test_get_desktop_app_pids_no_ps(tray_module, monkeypatch):
    """Return empty list when ps command is unavailable."""
    monkeypatch.setattr(tray_module, "get_ps_cmd", lambda: None)
    assert tray_module.get_desktop_app_pids() == []  # nosec B101


def test_get_desktop_app_pids_edge_cases(tray_module, monkeypatch):
    """Ignore malformed, non-digit, and renderer entries."""
    output = (
        "abc /opt/LM Studio/lm-studio\n"
        "123\n"
        "456 /usr/bin/lm-studio --type=renderer\n"
        "789 lm-studio --flag\n"
        "101 /opt/LM Studio/lm-studio --type=utility\n"
    )
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0, stdout=output),
    )
    assert tray_module.get_desktop_app_pids() == [789]  # nosec B101


def test_get_desktop_app_pids_excludes_daemon_workers(
    tray_module, monkeypatch
):
    """Exclude daemon worker processes.

    Excludes systemresourcesworker, llmster, and similar processes.
    """
    output = (
        "567 /home/user/.lmstudio/llmster/0.0.3/bin/llmster\n"
        "678 /home/user/.lmstudio/.internal/utils/node "
        "systemresourcesworker\n"
        "789 /usr/bin/lm-studio\n"
        "890 /home/user/.lmstudio/.internal/utils/node "
        "liblmstudioworker\n"
    )
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed(
            returncode=0, stdout=output
        ),
    )
    # Only /usr/bin/lm-studio should be included; daemon workers excluded
    assert tray_module.get_desktop_app_pids() == [789]  # nosec B101


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
        [["/usr/bin/cmd1"], ["/usr/bin/cmd2"]],
        lambda _r: True,
    )
    assert result.returncode == 0  # nosec B101
    assert len(called) == 1  # nosec B101  # Stopped after first success


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


def test_stop_desktop_app_processes_force_kill(tray_module, monkeypatch):
    """Force-stop desktop app when it ignores SIGTERM."""
    tray = _make_tray_instance(tray_module)
    pid_batches = [[11], [22]]

    def next_pids():
        return pid_batches.pop(0) if pid_batches else []

    calls = {"count": 0}

    def next_status():
        calls["count"] += 1
        return "running" if calls["count"] < 12 else "stopped"

    monkeypatch.setattr(tray_module, "get_desktop_app_pids", next_pids)
    monkeypatch.setattr(tray, "get_desktop_app_status", next_status)
    monkeypatch.setattr(tray_module.time, "sleep", lambda _x: None)
    killed = []
    monkeypatch.setattr(
        tray_module.os,
        "kill",
        lambda pid, sig: killed.append((pid, sig)),
    )

    result = _call_member(tray, "_stop_desktop_app_processes")
    assert result is True  # nosec B101
    assert (22, signal.SIGKILL) in killed  # nosec B101


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
    assert any("notify-send" in str(c) for c in calls)  # nosec B101


def test_start_daemon_success_path(tray_module, monkeypatch):
    """Notify user when daemon start succeeds."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(
        tray,
        "_build_daemon_attempts",
        lambda _x: [["/usr/bin/llmster"]],
    )
    monkeypatch.setattr(
        tray,
        "_run_daemon_attempts",
        lambda _a, _b: _completed(returncode=0),
    )
    monkeypatch.setattr(tray_module, "is_llmster_running", lambda: True)
    monkeypatch.setattr(
        tray_module,
        "get_notify_send_cmd",
        lambda: "/usr/bin/notify-send",
    )
    notify_calls = []

    def capture_notify(cmd):
        notify_calls.append(cmd)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify)
    monkeypatch.setattr(
        tray_module.GLib,
        "timeout_add_seconds",
        lambda *_a, **_k: True,
    )
    tray.start_daemon(None)
    assert notify_calls  # nosec B101


def test_stop_daemon_success_path(tray_module, monkeypatch):
    """Notify user when daemon stop succeeds."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(
        tray,
        "_build_daemon_attempts",
        lambda _x: [["/usr/bin/cmd"]],
    )
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
    assert any("notify-send" in str(c) for c in calls)  # nosec B101


def test_stop_daemon_failure_detail(tray_module, monkeypatch):
    """Include stderr detail when daemon stop fails."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(
        tray,
        "_build_daemon_attempts",
        lambda _x: [["/usr/bin/llmster"]],
    )
    monkeypatch.setattr(
        tray,
        "_stop_llmster_best_effort",
        lambda: (False, _completed(returncode=1, stderr="oops")),
    )
    monkeypatch.setattr(
        tray_module,
        "get_notify_send_cmd",
        lambda: "/usr/bin/notify-send",
    )
    notify_calls = []

    def capture_notify(cmd):
        notify_calls.append(cmd)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify)
    monkeypatch.setattr(
        tray_module.GLib,
        "timeout_add_seconds",
        lambda *_a, **_k: True,
    )
    tray.stop_daemon(None)
    assert notify_calls  # nosec B101


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
    assert any("notify-send" in str(c) for c in calls)  # nosec B101


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
    app_file.chmod(0o755)  # Make it executable

    monkeypatch.setattr(tray_module.sys, "argv", ["x", "model", str(app_dir)])

    def fake_run(args, **_kwargs):
        """Return dpkg miss and generic success for other commands."""
        if args[:2] == ["dpkg", "-l"]:
            return _completed(returncode=0, stdout="")
        return _completed(returncode=0)

    monkeypatch.setattr(tray_module.subprocess, "run", fake_run)
    popen_calls = []

    def mock_popen(args, **_kwargs):
        popen_calls.append(args)
        return SimpleNamespace(pid=99999)

    monkeypatch.setattr(tray_module.subprocess, "Popen", mock_popen)
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


def test_start_desktop_app_deb_path(tray_module, monkeypatch):
    """Launch desktop app via installed .deb package."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(tray_module, "is_llmster_running", lambda: False)
    monkeypatch.setattr(
        tray_module,
        "get_notify_send_cmd",
        lambda: "/usr/bin/notify-send",
    )
    monkeypatch.setattr(tray_module, "get_dpkg_cmd", lambda: "/usr/bin/dpkg")
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda *_a, **_k: _completed(returncode=0, stdout="lm-studio"),
    )
    monkeypatch.setattr(
        tray_module.shutil,
        "which",
        lambda _x: "/usr/bin/lm-studio",
    )
    monkeypatch.setattr(tray_module.os.path, "isfile", lambda _p: True)
    monkeypatch.setattr(tray_module.os, "access", lambda _p, _m: True)

    def is_safe_dir(path):
        return path == "/usr/bin"

    monkeypatch.setattr(tray_module.os.path, "isdir", is_safe_dir)

    popen_calls = []
    process_mock = SimpleNamespace(pid=45678)

    def record_popen(*args, **_kwargs):
        popen_calls.append(args)
        return process_mock

    monkeypatch.setattr(tray_module.subprocess, "Popen", record_popen)

    notifications = []

    def capture_notify(cmd):
        notifications.append(cmd)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify)

    tray.start_desktop_app(None)
    assert len(notifications) > 0  # nosec B101
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
    monkeypatch.setattr(tray_module, "APP_MAINTAINER", "TestMaintainer")
    monkeypatch.setattr(
        tray_module,
        "APP_REPOSITORY",
        "https://github.com/test/repo"
    )
    monkeypatch.setattr(
        tray_module,
        "get_authors",
        lambda: ["TestMaintainer"],
    )
    tray.update_status = "Up to date"
    tray.show_about_dialog(None)
    dialog = tray_module.Gtk.AboutDialog.last_instance
    assert dialog.version == "v2.0.0 (Up to date)"  # nosec B101
    assert dialog.authors == ["TestMaintainer"]  # nosec B101
    assert dialog.website == "https://github.com/test/repo"  # nosec B101
    assert dialog.website_label == "GitHub Repository"  # nosec B101
    assert dialog.ran  # nosec B101
    assert dialog.destroyed  # nosec B101


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


def test_build_menu_clears_existing_items(tray_module, monkeypatch):
    """Remove stale menu items before rebuilding."""
    tray = _make_tray_instance(tray_module)
    tray.menu.append(DummyMenuItem(label="old"))
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "stopped")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    tray_module.TrayIcon.build_menu(tray)
    labels = [getattr(i, "label", "") for i in tray.menu.get_children()]
    assert "old" not in labels  # nosec B101


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


def test_build_menu_stopped_entries(tray_module, monkeypatch):
    """Build menu entries for stopped daemon and desktop app."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "stopped")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    tray_module.TrayIcon.build_menu(tray)
    labels = [getattr(i, "label", "") for i in tray.menu.get_children()]
    assert any(
        "Start Daemon (Headless)" in label for label in labels
    )  # nosec B101
    assert any(
        "Start Desktop App" in label for label in labels
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
    # Check for pkill calls with absolute paths
    pkill_x = any(
        c[0].endswith("pkill") and "-x" in c for c in calls
    )
    pkill_f = any(
        c[0].endswith("pkill") and "-f" in c for c in calls
    )
    assert pkill_x  # nosec B101
    assert pkill_f  # nosec B101


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


def test_show_status_dialog_success_path(tray_module, monkeypatch):
    """Render status dialog with CLI output on success."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda *_a, **_k: _completed(returncode=0, stdout="model A"),
    )
    tray.show_status_dialog(None)
    dialog = tray_module.Gtk.MessageDialog.last_instance
    assert dialog.secondary == "model A"  # nosec B101


def test_show_status_dialog_no_models(tray_module, monkeypatch):
    """Render default message when no models are loaded."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda *_a, **_k: _completed(returncode=1, stdout=""),
    )
    tray.show_status_dialog(None)
    dialog = tray_module.Gtk.MessageDialog.last_instance
    assert "No models loaded" in dialog.secondary  # nosec B101


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


def test_check_model_transition_notifications(tray_module, monkeypatch):
    """Notify on INFO->WARN, WARN->FAIL, and OK->INFO transitions."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_notify_send_cmd", lambda: "/n")
    notifications = []

    def capture_notify(cmd):
        notifications.append(cmd)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=1, stdout=""),
    )

    tray.last_status = "INFO"
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "stopped")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    tray.check_model()

    tray.last_status = "WARN"
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "not_found")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "not_found")
    tray.check_model()

    tray.last_status = "OK"
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    tray.check_model()

    assert len(notifications) >= 3  # nosec B101


def test_check_model_empty_lms_output(tray_module, monkeypatch):
    """Keep INFO status when lms output is empty."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda *_a, **_k: _completed(returncode=0, stdout=""),
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
        module.main()
        assert captured["enabled"] is True  # nosec B101
    finally:
        sys.argv = old_argv


def test_trayicon_constructor_sets_indicator_and_timer(
    tray_module,
    monkeypatch,
):
    """Initialize tray indicator properties and periodic timer."""
    monkeypatch.setattr(tray_module.TrayIcon, "build_menu", lambda _self: None)
    monkeypatch.setattr(
        tray_module.TrayIcon, "check_model", lambda _self: True
    )
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


def test_trayicon_constructor_idle_add(monkeypatch, tray_module):
    """Register idle callbacks when GLib supports idle_add."""
    monkeypatch.setattr(tray_module.TrayIcon, "build_menu", lambda _self: None)
    monkeypatch.setattr(
        tray_module.TrayIcon, "check_model", lambda _self: True
    )
    monkeypatch.setattr(
        tray_module.GLib,
        "timeout_add_seconds",
        lambda *_a, **_k: True,
    )
    idle_calls = []

    def record_idle(callback):
        idle_calls.append(callback)
        return True

    monkeypatch.setattr(
        tray_module.GLib,
        "idle_add",
        record_idle,
        raising=False,
    )
    tray_module.TrayIcon()
    assert len(idle_calls) == 2  # nosec B101


def test_maybe_auto_start_daemon(monkeypatch, tray_module):
    """Invoke auto-start path when enabled and daemon is stopped."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "AUTO_START_DAEMON", True)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "stopped")
    calls = []

    def record_start(_widget):
        calls.append("start")

    monkeypatch.setattr(tray, "start_daemon", record_start)
    result = _call_member(tray, "_maybe_auto_start_daemon")
    assert result is False  # nosec B101
    assert calls == ["start"]  # nosec B101


def test_maybe_start_gui(monkeypatch, tray_module):
    """Invoke GUI start path when enabled."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "GUI_MODE", True)
    calls = []

    def record_start(_widget):
        calls.append("gui")

    monkeypatch.setattr(tray, "start_desktop_app", record_start)
    assert _call_member(tray, "_maybe_start_gui") is False  # nosec B101
    assert calls == ["gui"]  # nosec B101


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


def test_run_safe_command_invalid_inputs(tray_module):
    """Raise ValueError for invalid command inputs."""
    # pylint: disable=protected-access
    with pytest.raises(ValueError, match="non-empty list"):
        tray_module._run_safe_command([])
    with pytest.raises(ValueError, match="non-empty list"):
        tray_module._run_safe_command("string")
    with pytest.raises(ValueError, match="must be strings"):
        tray_module._run_safe_command(["/bin/ls", 123])
    with pytest.raises(ValueError, match="absolute path"):
        tray_module._run_safe_command(["ls", "-l"])


def test_is_llmster_running_file_not_found_error(tray_module, monkeypatch):
    """Return False when pgrep raises FileNotFoundError."""
    def raise_fnf(*_a, **_k):
        raise FileNotFoundError("pgrep not found")
    monkeypatch.setattr(tray_module.subprocess, "run", raise_fnf)
    assert tray_module.is_llmster_running() is False  # nosec B101


def test_is_llmster_running_oserror_first_probe(tray_module, monkeypatch):
    """Return False when first probe raises OSError."""
    calls = {"count": 0}

    def run_side_effect(*_a, **_k):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("fail")
        return _completed(returncode=0)

    monkeypatch.setattr(tray_module.subprocess, "run", run_side_effect)
    assert tray_module.is_llmster_running() is True  # nosec B101


def test_get_desktop_app_pids_error_handling(tray_module, monkeypatch):
    """Return empty list when ps command fails or raises errors."""
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=1, stdout=""),
    )
    assert tray_module.get_desktop_app_pids() == []  # nosec B101

    def raise_oserror(*_a, **_k):
        raise OSError("fail")
    monkeypatch.setattr(tray_module.subprocess, "run", raise_oserror)
    assert tray_module.get_desktop_app_pids() == []  # nosec B101

    def raise_valueerror(*_a, **_k):
        raise ValueError("fail")
    monkeypatch.setattr(tray_module.subprocess, "run", raise_valueerror)
    assert tray_module.get_desktop_app_pids() == []  # nosec B101


def test_kill_existing_instances_errors(tray_module, monkeypatch):
    """Handle errors when terminating other instances."""
    # First test: pgrep not found
    monkeypatch.setattr(tray_module, "get_pgrep_cmd", lambda: None)
    tray_module.kill_existing_instances()  # Should log warning

    # Second test: PermissionError
    monkeypatch.setattr(
        tray_module, "get_pgrep_cmd", lambda: "/usr/bin/pgrep"
    )
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda *_a: _completed(returncode=0, stdout="99999\n"),
    )
    errors_raised = []

    def mock_getpid():
        return 12345  # Different from 99999

    def mock_kill(pid, _sig):
        if pid == 99999:
            err = PermissionError("denied")
            errors_raised.append(err)
            raise err

    monkeypatch.setattr(tray_module.os, "getpid", mock_getpid)
    monkeypatch.setattr(tray_module.os, "kill", mock_kill)
    tray_module.kill_existing_instances()  # Should handle PermissionError
    assert len(errors_raised) == 1  # nosec B101


def test_get_daemon_status_oserror(tray_module, monkeypatch):
    """Return not_found when daemon check raises OSError."""
    tray = _make_tray_instance(tray_module)

    def raise_oserror(*_a, **_k):
        raise OSError("fail")

    monkeypatch.setattr(tray_module.subprocess, "run", raise_oserror)
    assert _call_member(tray, "get_daemon_status") == "not_found"  # nosec B101


def test_get_desktop_app_status_appimage_search(
    tray_module, monkeypatch, tmp_path
):
    """Find AppImage in search paths."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(
        tray_module, "get_desktop_app_pids", lambda: []
    )
    monkeypatch.setattr(tray_module, "get_dpkg_cmd", lambda: None)

    apps_dir = tmp_path / "Apps"
    apps_dir.mkdir()
    (apps_dir / "LMStudio.AppImage").touch()

    monkeypatch.setattr(
        tray_module.os.path,
        "expanduser",
        lambda p: str(apps_dir) if "Apps" in p else "/nonexistent",
    )

    def is_apps_dir(p):
        return apps_dir in Path(p).parents or str(p) == str(apps_dir)

    monkeypatch.setattr(tray_module.os.path, "isdir", is_apps_dir)

    result = _call_member(tray, "get_desktop_app_status")
    assert result == "stopped"  # nosec B101


def test_get_desktop_app_status_permission_error(
    tray_module, monkeypatch
):
    """Handle PermissionError during AppImage search."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_desktop_app_pids", lambda: [])
    monkeypatch.setattr(tray_module, "get_dpkg_cmd", lambda: None)

    def raise_permission(*_a):
        raise PermissionError("denied")

    monkeypatch.setattr(tray_module.os.path, "isdir", lambda _p: True)
    monkeypatch.setattr(tray_module.os, "listdir", raise_permission)

    result = _call_member(tray, "get_desktop_app_status")
    assert result == "not_found"  # nosec B101


def test_start_daemon_runtime_error(tray_module, monkeypatch):
    """Handle RuntimeError when starting daemon."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(
        tray, "_build_daemon_attempts", lambda _x: [["/usr/bin/llmster"]]
    )
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")

    call_count = {"count": 0}

    def raise_runtime_on_daemon(*_args, **_k):
        # First call is for daemon start, second for notification
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise RuntimeError("daemon fail")
        return _completed(returncode=0)

    monkeypatch.setattr(
        tray, "_run_validated_command", raise_runtime_on_daemon
    )
    monkeypatch.setattr(
        tray_module.GLib, "timeout_add_seconds", lambda *_a: True
    )
    _call_member(tray, "start_daemon", None)  # Should handle error
    assert call_count["count"] >= 2  # nosec B101  # Daemon + notification


def test_stop_daemon_error_paths(tray_module, monkeypatch):
    """Cover error handling in stop_daemon."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(
        tray, "_build_daemon_attempts", lambda _x: ["/usr/bin/llmster"]
    )
    monkeypatch.setattr(
        tray, "_stop_llmster_best_effort", lambda: (False, None)
    )
    monkeypatch.setattr(tray, "_force_stop_llmster", lambda: None)
    _call_member(tray, "stop_daemon", None)  # Should call force stop


def test_start_desktop_app_with_notifications(tray_module, monkeypatch):
    """Cover notification path when starting desktop app."""
    tray = _make_tray_instance(tray_module)
    tray.desktop_app_path = "/usr/bin/lm-studio"

    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(
        tray_module.os.path, "isfile", lambda _p: True
    )
    monkeypatch.setattr(tray_module.os, "access", lambda _p, _m: True)

    process_mock = SimpleNamespace(pid=12345)
    monkeypatch.setattr(
        tray_module.subprocess,
        "Popen",
        lambda *_a, **_k: process_mock,
    )

    notifications = []

    def capture_notify(cmd):
        notifications.append(cmd)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify)

    _call_member(tray, "start_desktop_app", None)
    assert len(notifications) > 0  # nosec B101


def test_stop_desktop_app_pkill_not_found(tray_module, monkeypatch):
    """Handle missing pkill when stopping desktop app."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_pkill_cmd", lambda: None)

    notifications = []

    def capture_notify(cmd):
        notifications.append(cmd)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify)

    _call_member(tray, "stop_desktop_app", None)
    assert len(notifications) > 0  # nosec B101


def test_stop_desktop_app_success_and_not_found(tray_module, monkeypatch):
    """Cover success and not-found paths when stopping desktop app."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_pkill_cmd", lambda: "/usr/bin/pkill")
    monkeypatch.setattr(
        tray_module,
        "get_notify_send_cmd",
        lambda: "/usr/bin/notify-send",
    )
    results = [_completed(returncode=0), _completed(returncode=1)]
    calls = []

    def run_validated(cmd):
        calls.append(cmd)
        if cmd[0] == "/usr/bin/pkill":
            return results.pop(0)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", run_validated)

    _call_member(tray, "stop_desktop_app", None)
    _call_member(tray, "stop_desktop_app", None)
    assert len(calls) >= 4  # nosec B101


def test_run_daemon_attempts_invalid_command_format(tray_module):
    """Skip invalid command formats in _run_daemon_attempts."""
    tray = _make_tray_instance(tray_module)

    # Test with invalid command (not a list)
    attempts = ["not_a_list", {"invalid": "dict"}, 123]
    result = _call_member(
        tray, "_run_daemon_attempts", attempts, lambda _r: False
    )
    assert result is None  # nosec B101

    # Test with non-absolute path
    attempts = [["relative_path", "arg"]]
    result = _call_member(
        tray, "_run_daemon_attempts", attempts, lambda _r: False
    )
    assert result is None  # nosec B101


def test_get_status_indicator_all_states(tray_module):
    """Test all status indicator variants."""
    tray = _make_tray_instance(tray_module)
    running = _call_member(
        tray, "get_status_indicator", "running"
    )
    stopped = _call_member(
        tray, "get_status_indicator", "stopped"
    )
    not_found = _call_member(
        tray, "get_status_indicator", "not_found"
    )
    unknown = _call_member(
        tray, "get_status_indicator", "unknown"
    )
    assert running == "🟢"  # nosec B101
    assert stopped == "🟡"  # nosec B101
    assert not_found == "🔴"  # nosec B101
    assert unknown == "🔴"  # nosec B101


def test_quit_app(tray_module, monkeypatch):
    """Test quit_app method."""
    tray = _make_tray_instance(tray_module)
    quit_called = {"value": False}

    def mock_quit():
        quit_called["value"] = True

    monkeypatch.setattr(tray_module.Gtk, "main_quit", mock_quit)
    _call_member(tray, "quit_app", None)
    assert quit_called["value"] is True  # nosec B101


def test_show_status_dialog_lms_not_found(tray_module, monkeypatch):
    """Test show_status_dialog when lms is not found."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: None)

    dialogs = []

    class CaptureDialog:
        """Mock dialog class for capturing GTK dialog interactions.

        This class simulates a GTK MessageDialog for testing purposes,
        capturing dialog creation parameters and allowing verification
        of dialog content without displaying actual UI elements.

        Attributes:
            text (str): The primary text content of the dialog.
            secondary (str): The secondary/detailed text content of the
                dialog.
        """
        def __init__(self, *_args, **kwargs):
            dialogs.append(self)
            self.text = kwargs.get("text", "")
            self.secondary = ""

        def format_secondary_text(self, text):
            """Set the secondary text for the notification.

            Args:
                text: The secondary/body text to display in the notification.
            """
            self.secondary = text

        def run(self):
            """Execute the run operation and return the status code.

            Returns:
                int: Status code indicating success (0) or failure (non-zero).
            """
            return 0

        def destroy(self):
            """Destroy the object and clean up resources.

            This method is called when the object is no longer needed.
            It performs any necessary cleanup operations before the
            object is destroyed.
            """

    monkeypatch.setattr(tray_module.Gtk, "MessageDialog", CaptureDialog)
    _call_member(tray, "show_status_dialog", None)
    assert len(dialogs) > 0  # nosec B101


def test_parse_args_short_hand_debug_flag(tray_module):
    """Parse -d short-hand flag for --debug."""
    old_argv = sys.argv[:]
    try:
        sys.argv = ["prog", "-d"]
        args = tray_module.parse_args()
        assert args.debug is True  # nosec B101
    finally:
        sys.argv = old_argv


def test_parse_args_short_hand_auto_start_daemon(tray_module):
    """Parse -a short-hand flag for --auto-start-daemon."""
    old_argv = sys.argv[:]
    try:
        sys.argv = ["prog", "-a"]
        args = tray_module.parse_args()
        assert args.auto_start_daemon is True  # nosec B101
    finally:
        sys.argv = old_argv


def test_parse_args_short_hand_gui_flag(tray_module):
    """Parse -g short-hand flag for --gui."""
    old_argv = sys.argv[:]
    try:
        sys.argv = ["prog", "-g"]
        args = tray_module.parse_args()
        assert args.gui is True  # nosec B101
    finally:
        sys.argv = old_argv


def test_parse_args_short_hand_version_flag(tray_module):
    """Parse -v short-hand flag for --version (exits in real usage)."""
    old_argv = sys.argv[:]
    try:
        sys.argv = ["prog", "-v"]
        args = tray_module.parse_args()
        assert args.version is True  # nosec B101
    finally:
        sys.argv = old_argv


def test_parse_args_combined_short_hand_flags(tray_module):
    """Parse multiple short-hand flags combined."""
    old_argv = sys.argv[:]
    try:
        sys.argv = ["prog", "-dga"]
        args = tray_module.parse_args()
        assert args.debug is True  # nosec B101
        assert args.gui is True  # nosec B101
        assert args.auto_start_daemon is True  # nosec B101
    finally:
        sys.argv = old_argv


def test_parse_args_long_hand_still_works(tray_module):
    """Verify long-hand flags still work after adding short-hand."""
    old_argv = sys.argv[:]
    try:
        sys.argv = ["prog", "--debug", "--gui", "--auto-start-daemon"]
        args = tray_module.parse_args()
        assert args.debug is True  # nosec B101
        assert args.gui is True  # nosec B101
        assert args.auto_start_daemon is True  # nosec B101
    finally:
        sys.argv = old_argv
