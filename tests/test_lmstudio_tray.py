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
import json
import logging
import os
import signal
import threading
import subprocess  # nosec B404
import sys
import urllib.error
from email.message import Message
from pathlib import Path
from types import ModuleType, SimpleNamespace, MethodType
import pytest


@pytest.fixture(autouse=True)
def sync_threads(monkeypatch):
    """Run background threads inline during testing.

    The tray app uses ``threading.Thread`` for async operations.  During
    unit tests we replace the class with a dummy that immediately invokes the
    target so that tests remain deterministic and do not need to wait.
    """
    class DummyThread:
        """Initialize the MockThread.

        Args:
            target: The callable object to be invoked by
                the run() method.
            args: The argument tuple for the target
                invocation. Defaults to ().
            kwargs: A dictionary of keyword arguments for
                the target invocation. Defaults to None.
            **_ignored: Extra keyword arguments (e.g. daemon,
                name) accepted for compatibility and ignored.
        """
        def __init__(self, target, args=(), kwargs=None, **_ignored):
            self.target = target
            self.args = args
            self.kwargs = kwargs or {}
            self.daemon = True

        def start(self):
            """Execute the target function.

            Invokes the target with provided arguments and keyword arguments.
            """
            self.target(*self.args, **self.kwargs)
    monkeypatch.setattr(threading, "Thread", DummyThread)


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
        self.submenu = None

    def set_sensitive(self, value):
        """Set whether the item is interactive."""
        self.sensitive = value

    def connect(self, event, callback):
        """Store a signal connection tuple."""
        self.connected.append((event, callback))

    def set_submenu(self, submenu):
        """Store submenu reference."""
        self.submenu = submenu


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
        self.logo = None
        self.modal = False
        self.copyright = ""
        self.license = ""
        self.ran = False
        self.destroyed = False
        self.signals = {}
        self.added_labels = []
        DummyAboutDialog.last_instance = self

    def get_content_area(self):
        """Return self so pack_start can be called on the dialog."""
        return self

    def pack_start(self, widget, *_args, **_kwargs):
        """Simulate packing a widget; capture markup if present."""
        if hasattr(widget, 'markup') and widget.markup is not None:
            if widget.markup not in self.added_labels:
                self.added_labels.append(widget.markup)

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

    def set_logo(self, logo):
        """Store logo pixbuf reference."""
        self.logo = logo

    def set_copyright(self, text):
        """Store copyright string."""
        self.copyright = text

    def set_license(self, text):
        """Store license text."""
        self.license = text

    def set_modal(self, modal):
        """Store modal setting."""
        self.modal = modal

    def connect(self, sig_name, callback):
        """Register a fake signal handler for testing."""
        self.signals[sig_name] = callback

    def add_link_label(self, markup):
        """Simulate adding a clickable label to the content area."""
        self.added_labels.append(markup)

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

    class ResponseType:
        """Dialog response constants."""
        OK = 1
        CANCEL = 0

    class Align:
        """Alignment constants for GTK widgets."""
        START = 0

    class Dialog:
        """Dummy dialog for configuration UI."""
        def __init__(self, title="", flags=None, modal=None, **_kwargs):
            self.title = title
            self.flags = flags
            self.modal = modal
            self._content = DummyGtkModule.Grid()
            self._response = DummyGtkModule.ResponseType.CANCEL

        def add_buttons(self, *_args):
            """Add buttons to the interface.

            Args:
                *_args: Variable length argument list (unused).

            Returns:
                None
            """
            return None

        def get_content_area(self):
            """
            Get the content area of the widget.

            Returns:
                DummyGtkModule.Grid: The content area widget.
            """
            return self._content

        def show_all(self):
            """Show all items in the tray menu.

            This is a mock method that simulates showing all tray menu items.
            Used for testing purposes to verify tray menu behavior.

            Returns:
                None: This method always returns None as it's a mock
                    implementation.
            """
            return None

        def run(self):
            """
            Execute and return the prepared response.

            Returns:
                The pre-configured response object for this test instance.
            """
            return self._response

        def destroy(self):
            """
            Mock destroy method that simulates window destruction.

            Returns:
                None: Always returns None to simulate successful destruction.
            """
            return None

    class Grid:
        """Dummy grid container."""
        def __init__(self):
            self.rows = []

        def set_column_spacing(self, _value):
            """Set the column spacing for the tray manager.

            Args:
                _value: The column spacing value to set.

            Returns:
                None
            """
            return None

        def set_row_spacing(self, _value):
            """Mock implementation of set_row_spacing.

            Args:
                _value: The row spacing value (unused in mock).

            Returns:
                None
            """
            return None

        def attach(self, widget, *_args):
            """
            Attach a widget to the list box.

            This is a mock implementation that appends widgets to an
            internal list instead of performing actual GTK widget
            attachment.

            Args:
                widget: The widget to attach to the list box.
                *_args: Additional positional arguments (ignored for
                    mock purposes).
            """
            self.rows.append(widget)

        def add(self, widget):
            """
            Add a widget to the collection of rows.

            Args:
                widget: The widget to be added to the rows list.
            """
            self.rows.append(widget)

    class Label:
        """Dummy label widget."""
        def __init__(self, label=""):
            self.label = label
            self.markup = None
            self.signals = {}
            self._halign = None
            self._xalign = None
            self.centered = False

        def set_halign(self, value):
            """
            Sets the horizontal alignment value and updates the 'centered'
            attribute accordingly.

            If the provided value has a 'name' attribute equal to 'CENTER'
            or is equal to 0.5, the 'centered' attribute is set to True.

            Args:
                value: The horizontal alignment value. Can be an object with a
                    'name' attribute or a numeric value.
            """
            self._halign = value
            if hasattr(value, "name") and value.name == "CENTER":
                self.centered = True
            elif value == 0.5:
                self.centered = True
            return None

        def set_xalign(self, value):
            """
            Set the horizontal alignment value and update the centered state.

            Args:
                value (float): The horizontal alignment value.
                    If set to 0.5, the object is considered
                    centered.

            Returns:
                None
            """
            self._xalign = value
            if value == 0.5:
                self.centered = True
            return None

        def set_markup(self, markup):
            """Store markup for later inspection."""
            self.markup = markup

        def connect(self, sig_name, callback):
            """Record signal handlers for later invocation."""
            self.signals[sig_name] = callback

        def show(self):
            """No-op for showing the widget."""
            return None

    class Entry:
        """Dummy entry widget."""
        def __init__(self):
            self._text = ""

        def set_text(self, text):
            """Set the text value for this object.

            Args:
                text: The text string to be set.
            """
            self._text = text

        def get_text(self):
            """
            Retrieve the text content.

            Returns:
                str: The stored text value.
            """
            return self._text

    Menu = DummyMenu
    MenuItem = DummyMenuItem
    SeparatorMenuItem = DummySeparatorMenuItem
    MessageDialog = DummyMessageDialog
    AboutDialog = DummyAboutDialog
    Dialog = Dialog
    Grid = Grid
    Label = Label
    Entry = Entry

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
    Error = Exception

    @staticmethod
    def timeout_add_seconds(_seconds, _callback):
        """Stub timer registration and report success."""
        return True

    @staticmethod
    def idle_add(_callback):
        """Stub idle callback registration and report success."""
        return True


class DummyGdkPixbufModule(ModuleType):
    """Mock GdkPixbuf module for testing purposes."""
    class Pixbuf:
        """Stub Pixbuf class used by the About dialog logo loader."""
        @staticmethod
        def new_from_file_at_scale(_path, _width, _height, _preserve):
            """Return a dummy pixbuf object."""
            return object()


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

        def open(self, _request, _timeout=None, **_kwargs):
            """Return a dummy response or raise the configured exception."""
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


class DummyProcess:
    """Dummy subprocess.Popen object supporting context manager protocol.

    Used in mock_popen functions to simulate subprocess.Popen behavior
    while supporting the context manager protocol (with statement).
    """

    def __init__(self, pid=1):
        """Initialize with a process ID."""
        self.pid = pid

    def __enter__(self):
        """Support context manager entry."""
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        """Support context manager exit with no cleanup."""
        return False


def _completed(returncode=0, stdout="", stderr=""):
    """Create a subprocess-like completed result object."""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(name="tray_module")
def tray_module_fixture(monkeypatch, tmp_path):
    """Import lmstudio_tray with mocked GI/GTK dependencies."""
    gi_mod = ModuleType("gi")

    def require_version(*args, **kwargs):
        _ = (args, kwargs)
        return None

    monkeypatch.setattr(
        gi_mod,
        "require_version",
        require_version,
        raising=False,
    )

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
        _ = (_args, _kwargs)
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
    setattr(module, "Gtk", gtk_mod)
    setattr(module, "GLib", glib_mod)
    setattr(module, "AppIndicator3", app_mod)
    module.sync_app_state_for_tests(
        gtk_mod=gtk_mod,
        glib_mod=glib_mod,
        app_mod=app_mod,
    )

    def _set_state(name, value):
        """Set module-level state while keeping _AppState synchronized."""
        if name == "script_dir":
            module.sync_app_state_for_tests(script_dir_val=value)
            setattr(module, name, value)
            return
        if name == "APP_VERSION":
            module.sync_app_state_for_tests(app_version_val=value)
            setattr(module, name, value)
            return
        if name == "AUTO_START_DAEMON":
            module.sync_app_state_for_tests(auto_start_val=value)
            setattr(module, name, value)
            return
        if name == "GUI_MODE":
            module.sync_app_state_for_tests(gui_mode_val=value)
            setattr(module, name, value)
            return
        setattr(module, name, value)

    setattr(module, "_set_state_for_tests", _set_state)

    yield module


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
    _call_member(tray, "__setattr__", "_seen_desktop_call", False)
    _call_member(tray, "__setattr__", "_last_desktop_detection", None)
    _call_member(tray, "__setattr__", "_seen_dpkg_missing", False)
    tray.build_menu = lambda: None
    return tray


def _call_member(instance, member_name, *args, **kwargs):
    """Call a member by name to avoid direct protected-member access."""
    member = getattr(instance, member_name)
    return member(*args, **kwargs)


def test_get_app_version_reads_file(tray_module, tmp_path):
    """Read version string from a VERSION file."""
    tray_module.sync_app_state_for_tests(script_dir_val=str(tmp_path))
    (tmp_path / "VERSION").write_text("v1.2.3\n", encoding="utf-8")
    version = tray_module.get_app_version()
    if version != "v1.2.3":
        pytest.fail(f"Expected version 'v1.2.3' but got '{version}'")


def test_get_app_version_fallback_default(tray_module, tmp_path):
    """Fall back to default version when file is absent."""
    tray_module.sync_app_state_for_tests(script_dir_val=str(tmp_path))
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

    def require_version(*args, **kwargs):
        _ = (args, kwargs)
        return None

    monkeypatch.setattr(
        gi_mod,
        "require_version",
        require_version,
        raising=False,
    )
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


def test_namespace_fallback_to_appindicator3(monkeypatch, tmp_path):
    """If Ayatana namespace is missing, we fall back to ``AppIndicator3``.

    The module should still import successfully and the selected namespace
    should be recorded in :class:`_AppState`.

    A temporary directory is supplied for ``script_dir`` so that logging
    and other filesystem operations do not attempt to write under
    ``/usr/bin`` during the test.
    """
    gi_mod = ModuleType("gi")

    def require_version(name, _version):
        if name == "AyatanaAppIndicator3":
            raise ValueError("Namespace not available")
        return None

    monkeypatch.setattr(
        gi_mod,
        "require_version",
        require_version,
        raising=False,
    )
    gtk_mod = DummyGtkModule("gi.repository.Gtk")
    glib_mod = DummyGLibModule("gi.repository.GLib")
    gdkpixbuf_mod = DummyGdkPixbufModule("gi.repository.GdkPixbuf")
    app_mod = DummyAppIndicatorModule("gi.repository.AppIndicator3")

    monkeypatch.setitem(sys.modules, "gi", gi_mod)
    monkeypatch.setitem(
        sys.modules,
        "gi.repository",
        ModuleType("gi.repository"),
    )
    monkeypatch.setitem(sys.modules, "gi.repository.Gtk", gtk_mod)
    monkeypatch.setitem(sys.modules, "gi.repository.GLib", glib_mod)
    monkeypatch.setitem(sys.modules, "gi.repository.GdkPixbuf", gdkpixbuf_mod)
    monkeypatch.setitem(
        sys.modules,
        "gi.repository.AppIndicator3",
        app_mod,
    )

    original_import = importlib.import_module

    def fake_import(name):
        if name == "gi.repository.Gtk":
            return gtk_mod
        if name == "gi.repository.GLib":
            return glib_mod
        if name == "gi.repository.GdkPixbuf":
            return gdkpixbuf_mod
        if name == "gi.repository.AppIndicator3":
            return app_mod
        return original_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    module_name = "lmstudio_tray_fallback"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name,
        str(Path(__file__).resolve().parents[1] / "lmstudio_tray.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    module.sync_app_state_for_tests(script_dir_val=str(tmp_path))

    monkeypatch.setattr(module, "TrayIcon", lambda *_args, **_kwargs: None)
    old_argv = sys.argv[:]
    try:
        sys.argv = [sys.argv[0], "dummy-model", str(tmp_path)]
        module.main()
    finally:
        sys.argv = old_argv

    assert getattr(module, "_AppState").AppIndicator3 is app_mod  # nosec B101


def test_namespace_missing_exits(monkeypatch, capsys):
    """Fail with a clear error when no AppIndicator namespace exists."""
    gi_mod = ModuleType("gi")

    def require_version(name, _version):
        if name in ("AyatanaAppIndicator3", "AppIndicator3"):
            raise ValueError("Namespace not available")
        return None

    monkeypatch.setattr(
        gi_mod,
        "require_version",
        require_version,
        raising=False,
    )
    monkeypatch.setitem(sys.modules, "gi", gi_mod)
    monkeypatch.setitem(
        sys.modules,
        "gi.repository",
        ModuleType("gi.repository"),
    )

    module_name = "lmstudio_tray_no_ns"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name,
        str(Path(__file__).resolve().parents[1] / "lmstudio_tray.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "TrayIcon", lambda *_a, **_k: None)
    with pytest.raises(SystemExit) as exc:
        old_argv = sys.argv[:]
        try:
            sys.argv = [sys.argv[0]]
            module.main()
        finally:
            sys.argv = old_argv
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "AppIndicator3" in err


def test_parse_version_handles_prefix(tray_module):
    """Parse versions with a leading v prefix."""
    assert tray_module.parse_version("v1.2.3") == (1, 2, 3)  # nosec B101


def test_parse_version_empty_string(tray_module):
    """Test parse_version returns empty tuple for empty string."""
    assert tray_module.parse_version("") == ()  # nosec B101
    assert tray_module.parse_version(None) == ()  # nosec B101
    assert tray_module.parse_version("v1.2.3-beta") == (1, 2, 3)  # nosec B101
    assert tray_module.parse_version("beta") == ()  # nosec B101


def test_is_newer_version(tray_module):
    """Compare version tuples for update checks."""
    assert tray_module.is_newer_version("v1.2.3", "v1.2.4")  # nosec B101
    assert not tray_module.is_newer_version("v1.2.3", "v1.2.3")  # nosec B101
    assert not tray_module.is_newer_version("dev", "v1.2.3")  # nosec B101
    assert not tray_module.is_newer_version("", "")  # nosec B101
    assert not tray_module.is_newer_version("invalid", "")  # nosec B101
    assert not tray_module.is_newer_version("", "v1.0.0")  # nosec B101


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
    tray_module.sync_app_state_for_tests(app_version_val="v1.0.0")
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
    tray_module.sync_app_state_for_tests(app_version_val="dev")
    monkeypatch.setattr(tray_module, "DEFAULT_APP_VERSION", "dev")
    tray.check_updates()
    assert tray.update_status == "Dev build"  # nosec B101


def test_check_updates_error_path(tray_module, monkeypatch):
    """Set update_status to 'Unknown' when version fetch fails."""
    tray = _make_tray_instance(tray_module)
    tray_module.sync_app_state_for_tests(app_version_val="v1.0.0")
    monkeypatch.setattr(tray_module, "DEFAULT_APP_VERSION", "dev")
    monkeypatch.setattr(
        tray_module,
        "get_latest_release_version",
        lambda: (None, "Network error"),
    )
    tray.check_updates()
    assert tray.update_status == "Unknown"  # nosec B101


def test_check_updates_ahead_of_release(tray_module, monkeypatch):
    """Set update_status to 'Ahead of release' when current > latest."""
    tray = _make_tray_instance(tray_module)
    tray_module.sync_app_state_for_tests(app_version_val="v0.4.2")
    monkeypatch.setattr(tray_module, "DEFAULT_APP_VERSION", "dev")
    monkeypatch.setattr(
        tray_module,
        "get_latest_release_version",
        lambda: ("v0.4.1", None),
    )
    result = tray.check_updates()
    assert tray.update_status == "Ahead of release"  # nosec B101
    assert result is False  # nosec B101


def test_check_updates_up_to_date(tray_module, monkeypatch):
    """Set update_status to 'Up to date' when versions match."""
    tray = _make_tray_instance(tray_module)
    tray_module.sync_app_state_for_tests(app_version_val="v1.0.0")
    monkeypatch.setattr(tray_module, "DEFAULT_APP_VERSION", "dev")
    monkeypatch.setattr(
        tray_module,
        "get_latest_release_version",
        lambda: ("v1.0.0", None),
    )
    result = tray.check_updates()
    assert tray.update_status == "Up to date"  # nosec B101
    assert result is False  # nosec B101


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
    tray_module.sync_app_state_for_tests(app_version_val="v1.0.0")
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
    assert "/releases" in msg  # nosec B101


def test_manual_check_updates_reports_dev_build(tray_module, monkeypatch):
    """Notify user when running a development build."""
    tray = _make_tray_instance(tray_module)
    tray_module.sync_app_state_for_tests(app_version_val="dev")
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
    tray_module.sync_app_state_for_tests(app_version_val="v1.0.0")
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


def test_manual_check_updates_reports_ahead_of_release(
    tray_module,
    monkeypatch,
):
    """Notify user when running ahead of latest release."""
    tray = _make_tray_instance(tray_module)
    tray_module.sync_app_state_for_tests(app_version_val="v0.4.2")
    monkeypatch.setattr(tray_module, "DEFAULT_APP_VERSION", "dev")
    monkeypatch.setattr(
        tray_module,
        "get_latest_release_version",
        lambda: ("v0.4.1", None),
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
    assert "Ahead of release" in msg  # nosec B101


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
    assert "/releases" in message  # nosec B101
    tray.update_status = "Update available"
    tray.latest_update_version = "v9.9.9"
    label = tray.get_version_label()
    assert "v9.9.9" in label  # nosec B101
    assert "/releases" not in label  # nosec B101

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
    tray_module.sync_app_state_for_tests(app_version_val="v1.0.0")
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
    tray.manual_check_updates(None)
    assert len(notify_calls) == 1  # nosec B101
    msg = str(notify_calls[0])
    assert "Update Check" in msg  # nosec B101
    assert "Unable to check for updates" in msg  # nosec B101


def test_get_authors_reads_file(tray_module, tmp_path):
    """Read authors from AUTHORS file."""
    tray_module.sync_app_state_for_tests(script_dir_val=str(tmp_path))
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
):
    """Strip handles and descriptions from authors list."""
    tray_module.sync_app_state_for_tests(script_dir_val=str(tmp_path))
    (tmp_path / "AUTHORS").write_text(
        "- Jane Doe (@jane) - contributor\n",
        encoding="utf-8",
    )
    authors = tray_module.get_authors()
    assert authors == ["Jane Doe"]  # nosec B101


def test_get_authors_fallback_maintainer(tray_module, tmp_path, monkeypatch):
    """Fall back to APP_MAINTAINER when AUTHORS file is absent."""
    tray_module.sync_app_state_for_tests(script_dir_val=str(tmp_path))
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


def test_get_llmster_cmd_debug_logs(tray_module, monkeypatch, caplog):
    """Debug mode emits helpful information about llmster lookup."""
    monkeypatch.setattr(tray_module.shutil, "which", lambda _x: None)
    monkeypatch.setattr(tray_module.os.path, "isdir", lambda _p: False)
    caplog.set_level(logging.DEBUG)
    result = tray_module.get_llmster_cmd()
    assert result is None
    assert "No ~/.lmstudio/llmster directory present" in caplog.text


def test_get_llmster_cmd_debug_no_repeat(tray_module, monkeypatch, caplog):
    """Repeated calls do not log the same message again."""
    monkeypatch.setattr(tray_module.shutil, "which", lambda _x: None)
    monkeypatch.setattr(tray_module.os.path, "isdir", lambda _p: False)
    caplog.set_level(logging.DEBUG)
    tray_module.get_llmster_cmd()
    caplog.clear()
    tray_module.get_llmster_cmd()
    assert caplog.text == ""


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


def test_get_desktop_app_pids_appimage(tray_module, monkeypatch):
    """Also detect LM Studio AppImage processes."""
    output = (
        "777 /home/user/Apps/LM-Studio-0.4.6.AppImage --no-sandbox\n"
        "888 /home/user/Apps/Other.AppImage\n"
    )
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0, stdout=output),
    )
    assert tray_module.get_desktop_app_pids() == [777]  # nosec B101


def test_get_desktop_app_pids_excludes_bench_appimage(
    tray_module, monkeypatch
):
    """Do not treat LM-Studio-Bench AppImage as desktop app."""
    output = (
        "777 /home/user/Apps/LM-Studio-Bench-x86_64.AppImage -w\n"
        "888 /home/user/Apps/LM-Studio-0.4.6.AppImage --no-sandbox\n"
    )
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0, stdout=output),
    )
    assert tray_module.get_desktop_app_pids() == [888]  # nosec B101


def test_get_desktop_app_pids_extracted_appimage(tray_module, monkeypatch):
    """Detect extracted AppImage mount processes."""
    output = (
        "999 /tmp/.mount_LM-StuvLaKuX/lm-studio --no-sandbox\n"
        "1000 /tmp/.mount_Other/other-app\n"
        "1001 /tmp/.mount_LM-Studio/lm-studio\n"
    )
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0, stdout=output),
    )
    assert tray_module.get_desktop_app_pids() == [999, 1001]  # nosec B101


def test_get_desktop_app_pids_excludes_bench_mount(tray_module, monkeypatch):
    """Do not treat mounted LM-Studio-Bench processes as desktop app."""
    output = (
        "1030190 /tmp/.mount_LM-StuhafobM/usr/venv/bin/python "
        "/tmp/.mount_LM-StuhafobM/usr/share/lm-studio-bench/"
        "run.py -w\n"
        "1030201 /tmp/.mount_LM-StuhafobM/usr/venv/bin/python "
        "/tmp/.mount_LM-StuhafobM/usr/share/lm-studio-bench/"
        "src/tray.py\n"
        "999 /tmp/.mount_LM-Studio/lm-studio --no-sandbox\n"
    )
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0, stdout=output),
    )
    # Only the real LM Studio mount should be detected, not Bench
    assert tray_module.get_desktop_app_pids() == [999]  # nosec B101


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
    assert len(called) == 1  # nosec B101


def test_stop_llmster_best_effort_with_force(tray_module, monkeypatch):
    """Force-stop llmster when graceful stop does not finish."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "_build_daemon_attempts", lambda _x: [["cmd"]])
    monkeypatch.setattr(
        tray,
        "_run_daemon_attempts",
        lambda _a, _c: _completed(returncode=1),
    )
    force_stop_called = []

    def mock_force_stop():
        force_stop_called.append(True)

    monkeypatch.setattr(tray, "_force_stop_llmster", mock_force_stop)
    monkeypatch.setattr(
        tray_module, "is_llmster_running", lambda: False
    )
    stopped, _result = _call_member(tray, "_stop_llmster_best_effort")
    assert stopped is True  # nosec B101
    assert len(force_stop_called) == 1


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
    assert (22, 9) in killed  # nosec B101


def test_start_daemon_missing_binaries_notifies(tray_module, monkeypatch):
    """Notify user when daemon binaries are unavailable."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(tray, "_build_daemon_attempts", lambda _x: [])
    monkeypatch.setattr(
        tray_module, "get_notify_send_cmd", lambda: "/usr/bin/notify-send"
    )
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
    monkeypatch.setattr(
        tray_module, "get_notify_send_cmd", lambda: "/usr/bin/notify-send"
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


def test_ensure_gsettings_schema(_tmp_path, monkeypatch, tray_module):
    """_ensure_gsettings_schema sets the env var when directory exists."""
    monkeypatch.delenv("GSETTINGS_SCHEMA_DIR", raising=False)
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    _call_member(tray_module, "_ensure_gsettings_schema")
    assert "GSETTINGS_SCHEMA_DIR" in os.environ
    assert os.environ["GSETTINGS_SCHEMA_DIR"].endswith("glib-2.0/schemas")


def test_start_desktop_app_missing_lms(tray_module, monkeypatch):
    """Notify user when lms CLI is missing."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: None)
    monkeypatch.setattr(
        tray_module, "get_notify_send_cmd", lambda: "/usr/bin/notify-send"
    )
    calls = []
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(args) or _completed(returncode=0),
    )
    tray.start_desktop_app(None)
    assert any("notify-send" in str(c) for c in calls)  # nosec B101


def test_start_desktop_app_force_stops_daemon_before_launch(
    tray_module,
    monkeypatch,
):
    """Force-stop daemon when graceful stop path does not stop it."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")

    daemon_state = {"running": True}

    def daemon_running():
        return daemon_state["running"]

    monkeypatch.setattr(tray_module, "is_llmster_running", daemon_running)
    monkeypatch.setattr(
        tray,
        "_stop_daemon_with_notification",
        lambda: (False, None),
    )

    force_calls = []

    def force_stop():
        force_calls.append(True)
        daemon_state["running"] = False

    monkeypatch.setattr(tray, "_force_stop_llmster", force_stop)

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
    monkeypatch.setattr(
        tray_module.os.path,
        "isdir",
        lambda p: p == "/usr/bin",
    )

    popen_calls = []

    def mock_popen(*_a, **_k):
        popen_calls.append(True)
        return DummyProcess(pid=12345)

    monkeypatch.setattr(tray_module.subprocess, "Popen", mock_popen)
    monkeypatch.setattr(
        tray_module,
        "get_notify_send_cmd",
        lambda: "/usr/bin/notify-send",
    )
    monkeypatch.setattr(
        tray,
        "_run_validated_command",
        lambda _cmd: _completed(returncode=0),
    )
    monkeypatch.setattr(tray_module.time, "sleep", lambda _t: None)

    tray.start_desktop_app(None)

    assert force_calls  # nosec B101
    assert popen_calls  # nosec B101
    assert daemon_state["running"] is False  # nosec B101


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
    app_file.chmod(0o755)

    monkeypatch.setattr(tray_module.sys, "argv", ["x", "model", str(app_dir)])

    def fake_run(args, **_kwargs):
        """Return dpkg miss and generic success for other commands."""
        if args[:2] == ["dpkg", "-l"]:
            return _completed(returncode=0, stdout="")
        return _completed(returncode=0)

    monkeypatch.setattr(tray_module.subprocess, "run", fake_run)

    popen_args = []

    def mock_popen(args, **_k):
        popen_args.append(args)
        return DummyProcess(pid=123)
    monkeypatch.setattr(tray_module.subprocess, "Popen", mock_popen)

    tray.start_desktop_app(None)
    assert popen_args, "expected Popen to be invoked"
    assert any("--no-sandbox" in arg for call in popen_args for arg in call)


def test_start_desktop_app_prefers_lmstudio_appimage(
    tray_module,
    monkeypatch,
    tmp_path,
):
    """When multiple AppImages exist, the one named LM-Studio is started."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(tray_module, "is_llmster_running", lambda: False)

    app_dir = tmp_path / "Apps"
    app_dir.mkdir()
    (app_dir / "Other.AppImage").write_text("x")
    (app_dir / "LM-Studio-1.0.AppImage").write_text("x")
    for f in app_dir.iterdir():
        f.chmod(0o755)

    monkeypatch.setattr(tray_module.sys, "argv", ["x", "model", str(app_dir)])

    def fake_run(args, **_kwargs):
        if args[:2] == ["dpkg", "-l"]:
            return _completed(returncode=0, stdout="")
        return _completed(returncode=0)

    monkeypatch.setattr(tray_module.subprocess, "run", fake_run)

    popen_calls = []

    def mock_popen(args, **_k):
        popen_calls.append(args)
        return DummyProcess(pid=123)

    monkeypatch.setattr(tray_module.subprocess, "Popen", mock_popen)
    monkeypatch.setattr(
        tray_module.os.path,
        "isdir",
        lambda p: p == str(app_dir),
    )
    monkeypatch.setattr(
        tray_module.os,
        "listdir",
        lambda _p: ["Other.AppImage", "LM-Studio-1.0.AppImage"],
    )
    monkeypatch.setattr(
        tray_module.GLib,
        "timeout_add_seconds",
        lambda *_a, **_k: True,
    )

    tray.start_desktop_app(None)
    assert any(
        "lm-studio" in arg.lower()
        for call in popen_calls
        for arg in call
    )
    assert not any(
        "other" in arg.lower()
        for call in popen_calls
        for arg in call
    )
    assert any("--no-sandbox" in call for call in popen_calls)


def test_start_desktop_app_deb_path_appimage(
    tmp_path, tray_module, monkeypatch
):
    """Test launching desktop app via AppImage in deb path scenario."""
    tray = _make_tray_instance(tray_module)
    app_dir = tmp_path / "Apps"
    app_dir.mkdir()
    popen_calls = []

    def mock_popen(args, **_kwargs):
        popen_calls.append(args)
        return DummyProcess(pid=12345)

    monkeypatch.setattr(tray_module.subprocess, "Popen", mock_popen)
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
        lambda *_a, **_k: _completed(returncode=1, stdout=""),
    )

    monkeypatch.setattr(
        tray_module.os.path,
        "isdir",
        lambda _unused_p: _unused_p == str(app_dir),
    )
    monkeypatch.setattr(
        tray_module.os,
        "listdir",
        lambda _unused_p: ["LM-Studio.AppImage"],
    )
    monkeypatch.setattr(
        tray_module.GLib,
        "timeout_add_seconds",
        lambda *args, **_kwargs: True,
    )

    dummy_app = app_dir / "LM-Studio.AppImage"
    dummy_app.write_text("", encoding="utf-8")
    dummy_app.chmod(0o755)

    tray.start_desktop_app(None)
    assert popen_calls  # nosec B101
    assert any("--no-sandbox" in arg for call in popen_calls for arg in call)


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

    def mock_popen(*_a, **_k):
        popen_calls.append(True)
        return DummyProcess(pid=12345)

    monkeypatch.setattr(tray_module.subprocess, "Popen", mock_popen)

    notifications = []

    def capture_notify(cmd):
        notifications.append(cmd)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify)

    tray.start_desktop_app(None)
    assert len(notifications) > 0  # nosec B101
    assert popen_calls  # nosec B101


def test_start_desktop_app_popen_kwargs(tray_module, monkeypatch):
    """Test Popen is called with start_new_session and DEVNULL streams."""
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
    captured_kwargs = {}

    def mock_popen(_args, **kwargs):
        captured_kwargs.update(kwargs)
        return DummyProcess(pid=12345)

    monkeypatch.setattr(tray_module.subprocess, "Popen", mock_popen)

    notifications = []

    def capture_notify(cmd):
        notifications.append(cmd)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify)

    tray.start_desktop_app(None)
    assert captured_kwargs.get("start_new_session") is True  # nosec B101
    assert (  # nosec B101
        captured_kwargs.get("stdin") == subprocess.DEVNULL
    )
    assert (  # nosec B101
        captured_kwargs.get("stdout") == subprocess.DEVNULL
    )
    assert (  # nosec B101
        captured_kwargs.get("stderr") == subprocess.DEVNULL
    )


def test_start_desktop_app_popen_oserror(tray_module, monkeypatch):
    """Test OSError handling when Popen fails to launch the app."""
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

    def mock_popen(*_a, **_k):
        raise OSError("Permission denied")
    monkeypatch.setattr(tray_module.subprocess, "Popen", mock_popen)
    notifications = []

    def capture_notify(cmd):
        notifications.append(cmd)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify)
    tray.start_desktop_app(None)
    assert any(  # nosec B101
        "Error" in str(n) for n in notifications
    )


def test_start_desktop_app_unsafe_path_error(
    tray_module, monkeypatch, tmp_path
):
    """Test that an AppImage in an unsafe location triggers an error."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(tray_module, "is_llmster_running", lambda: False)
    monkeypatch.setattr(
        tray_module,
        "get_notify_send_cmd",
        lambda: "/usr/bin/notify-send",
    )
    monkeypatch.setattr(tray_module, "get_dpkg_cmd", lambda: None)
    unsafe_dir = str(tmp_path / "lmstudio-test-unsafe")
    tray_module.sync_app_state_for_tests(script_dir_val=unsafe_dir)
    monkeypatch.setattr(
        tray_module.os.path, "isdir", lambda p: p == unsafe_dir
    )
    monkeypatch.setattr(
        tray_module.os, "listdir", lambda _p: ["LM-Studio.AppImage"]
    )
    monkeypatch.setattr(tray_module.os.path, "isfile", lambda _p: True)
    monkeypatch.setattr(tray_module.os, "access", lambda _p, _m: True)
    monkeypatch.setattr(
        tray_module.shutil, "which", lambda _x: None
    )

    notifications = []

    def capture_notify(cmd):
        notifications.append(cmd)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify)
    tray.start_desktop_app(None)
    assert any(  # nosec B101
        "Error" in str(n) for n in notifications
    )


def test_stop_desktop_app_no_process_path(tray_module, monkeypatch):
    """Handle desktop stop request when no process is running."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_desktop_app_pids", lambda: [])
    monkeypatch.setattr(
        tray_module.GLib,
        "timeout_add_seconds",
        lambda *_a, **_k: True,
    )
    tray.stop_desktop_app(None)


def test_show_status_dialog_success(tray_module, monkeypatch):
    """Render status dialog with lms output."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
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
    """
    Show about dialog includes version, repo link, documentation link,
    and version info.
    """
    tray = _make_tray_instance(tray_module)
    tray_module.sync_app_state_for_tests(app_version_val="v2.0.0")
    monkeypatch.setattr(tray_module, "APP_MAINTAINER", "TestMaintainer")
    monkeypatch.setattr(
        tray_module,
        "APP_REPOSITORY",
        "https://github.com/test/repo"
    )
    monkeypatch.setattr(
        tray_module,
        "APP_DOCUMENTATION",
        "https://docs.example.com/foo"
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
    expected_comments = (
        "Monitors and controls LM Studio daemon and desktop app."
    )
    assert dialog.comments == expected_comments  # nosec B101
    assert (
        '<a href="https://docs.example.com/foo">Documentation</a>'
        in dialog.added_labels
    )  # nosec B101
    assert dialog.ran  # nosec B101
    assert dialog.destroyed  # nosec B101


def test_show_about_dialog_release_link(tray_module, monkeypatch):
    """Website button should point to release when update pending."""
    tray = _make_tray_instance(tray_module)
    tray_module.sync_app_state_for_tests(app_version_val="v1.0.0")
    repo_url = "https://github.com/foo/bar"
    docs_url = "https://docs.foo/bar"
    monkeypatch.setattr(tray_module, "APP_REPOSITORY", repo_url)
    monkeypatch.setattr(tray_module, "APP_DOCUMENTATION", docs_url)
    monkeypatch.setattr(tray_module, "get_authors", lambda: ["Me"])
    tray.update_status = "Update available"
    tray.latest_update_version = "v1.2.3"

    tray.show_about_dialog(None)
    dialog = tray_module.Gtk.AboutDialog.last_instance
    expected_url = f"{repo_url}/releases/tag/v1.2.3"
    assert dialog.website == expected_url  # nosec B101
    assert dialog.website_label == "Release"  # nosec B101
    expected_comments = (
        "Monitors and controls "
        "LM Studio daemon "
        "and desktop app."
    )
    assert dialog.comments == expected_comments  # nosec B101
    assert (
        '<a href="https://docs.foo/bar">Documentation</a>'
        in dialog.added_labels
    )  # nosec B101
    assert dialog.ran  # nosec B101
    assert dialog.destroyed  # nosec B101


def test_show_about_dialog_includes_copyright(tray_module, monkeypatch):
    """About dialog should display 2025–2026 copyright."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "APP_MAINTAINER", "FooCorp")
    tray.show_about_dialog(None)
    dialog = tray_module.Gtk.AboutDialog.last_instance
    assert "2025-2026" in dialog.copyright  # nosec B101


def test_show_about_dialog_sets_logo(tray_module, monkeypatch, tmp_path):
    """Load the SVG logo when GdkPixbuf is available."""
    tray = _make_tray_instance(tray_module)
    gdk_mod = DummyGdkPixbufModule("gi.repository.GdkPixbuf")
    tray_module.sync_app_state_for_tests(gdk_pixbuf_mod=gdk_mod)

    fake_logo = object()
    monkeypatch.setattr(
        gdk_mod.Pixbuf,
        "new_from_file_at_scale",
        lambda *_a, **_k: fake_logo,
    )
    logo_file = tmp_path / "logo.svg"
    monkeypatch.setattr(
        tray_module,
        "get_asset_path",
        lambda *_a, **_k: str(logo_file),
    )

    tray.show_about_dialog(None)
    dialog = tray_module.Gtk.AboutDialog.last_instance
    assert dialog.logo is fake_logo  # nosec B101


def test_show_about_dialog_logo_error(tray_module, monkeypatch, tmp_path):
    """Ignore logo loading errors and still show dialog."""
    tray = _make_tray_instance(tray_module)
    gdk_mod = DummyGdkPixbufModule("gi.repository.GdkPixbuf")
    tray_module.sync_app_state_for_tests(gdk_pixbuf_mod=gdk_mod)

    def _raise_error(*_a, **_k):
        raise tray_module.GLib.Error("boom")

    monkeypatch.setattr(
        gdk_mod.Pixbuf,
        "new_from_file_at_scale",
        _raise_error,
    )
    logo_file = tmp_path / "logo.svg"
    monkeypatch.setattr(
        tray_module,
        "get_asset_path",
        lambda *_a, **_k: str(logo_file),
    )

    tray.show_about_dialog(None)
    dialog = tray_module.Gtk.AboutDialog.last_instance
    assert dialog.ran is True  # nosec B101
    assert dialog.destroyed is True  # nosec B101


def test_show_about_dialog_png_fallback(tray_module, monkeypatch, tmp_path):
    """Fallback to PNG when SVG is unavailable."""
    tray = _make_tray_instance(tray_module)
    gdk_mod = DummyGdkPixbufModule("gi.repository.GdkPixbuf")
    tray_module.sync_app_state_for_tests(gdk_pixbuf_mod=gdk_mod)

    fake_logo = object()
    monkeypatch.setattr(
        gdk_mod.Pixbuf,
        "new_from_file_at_scale",
        lambda *_a, **_k: fake_logo,
    )

    def _asset_path(*_args):
        if _args[-1] == "lm-studio-tray-manager.svg":
            return None
        return str(tmp_path / "logo.png")

    monkeypatch.setattr(tray_module, "get_asset_path", _asset_path)
    tray.show_about_dialog(None)
    dialog = tray_module.Gtk.AboutDialog.last_instance
    assert dialog.logo is fake_logo  # nosec B101


def test_show_about_dialog_frozen_binary_prefers_png(
    tray_module,
    monkeypatch,
    tmp_path,
):
    """Prefer PNG over SVG in frozen PyInstaller binary."""
    tray = _make_tray_instance(tray_module)
    gdk_mod = DummyGdkPixbufModule("gi.repository.GdkPixbuf")
    tray_module.sync_app_state_for_tests(gdk_pixbuf_mod=gdk_mod)

    fake_logo = object()
    load_attempts = []

    def track_load_attempts(path, *_args, **_kwargs):
        """Track which file types are attempted in order."""
        load_attempts.append(path)
        return fake_logo

    monkeypatch.setattr(
        gdk_mod.Pixbuf,
        "new_from_file_at_scale",
        track_load_attempts,
    )

    meipass_dir = tmp_path / "_MEIPASS" / "assets" / "img"
    meipass_dir.mkdir(parents=True)

    def _asset_path(*args):
        ext = args[-1].split(".")[-1]
        return str(meipass_dir / f"logo.{ext}")

    monkeypatch.setattr(tray_module, "get_asset_path", _asset_path)
    monkeypatch.setattr(
        tray_module.sys,
        "_MEIPASS",
        str(tmp_path / "_MEIPASS"),
        raising=False,
    )

    tray.show_about_dialog(None)
    dialog = tray_module.Gtk.AboutDialog.last_instance
    assert dialog.logo is fake_logo  # nosec B101
    assert len(load_attempts) >= 1  # nosec B101
    assert load_attempts[0].endswith(".png")  # nosec B101


def test_show_about_dialog_no_logo_files_found(tray_module, monkeypatch):
    """Handle case when no logo files are found."""
    tray = _make_tray_instance(tray_module)
    gdk_mod = DummyGdkPixbufModule("gi.repository.GdkPixbuf")
    tray_module.sync_app_state_for_tests(gdk_pixbuf_mod=gdk_mod)
    monkeypatch.setattr(tray_module, "get_asset_path", lambda *_a: None)
    tray.show_about_dialog(None)
    dialog = tray_module.Gtk.AboutDialog.last_instance
    assert dialog.ran is True  # nosec B101
    assert dialog.destroyed is True  # nosec B101
    assert dialog.logo is None  # nosec B101


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

    monkeypatch.setattr(tray, "get_daemon_status", lambda: "not_found")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "not_found")
    tray.last_status = None
    assert tray.check_model() is True  # nosec B101
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "stopped")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    assert tray.check_model() is True  # nosec B101
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: None)
    assert tray.check_model() is True  # nosec B101
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda *_a, **_k: _completed(returncode=0, stdout="loaded"),
    )
    assert tray.check_model() is True  # nosec B101


def test_check_model_api_fallback(tray_module, monkeypatch):
    """Use API fallback when lms ps fails but models exist."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "running")
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda *_a, **_k: _completed(returncode=1, stdout=""),
    )
    monkeypatch.setattr(tray_module, "check_api_models", lambda: True)

    assert tray.check_model() is True  # nosec B101
    assert tray.indicator.icon_calls[-1] == (  # nosec B101
        tray_module.ICON_OK,
        "Model loaded",
    )


def test_check_model_skips_lms_ps_when_only_desktop_running(
    tray_module,
    monkeypatch,
):
    """Avoid lms ps call during desktop launch grace window."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "stopped")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "running")
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    tray.lms_ps_resume_at = 999.0
    monkeypatch.setattr(tray_module.time, "monotonic", lambda: 100.0)

    def fail_on_lms_ps(*_a, **_k):
        raise RuntimeError("lms ps must not be called in desktop-only mode")

    monkeypatch.setattr(tray_module, "_run_safe_command", fail_on_lms_ps)
    monkeypatch.setattr(tray_module, "check_api_models", lambda: False)

    assert tray.check_model() is True  # nosec B101
    assert tray.indicator.icon_calls[-1][0] == tray_module.ICON_INFO


def test_check_model_uses_lms_ps_for_desktop_after_grace(
    tray_module,
    monkeypatch,
):
    """Use lms ps in desktop-only mode after grace window elapsed."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "stopped")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "running")
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    tray.lms_ps_resume_at = 100.0
    monkeypatch.setattr(tray_module.time, "monotonic", lambda: 200.0)

    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda *_a, **_k: _completed(
            returncode=0,
            stdout=(
                "IDENTIFIER MODEL STATUS\n"
                "mistral mistral IDLE"
            ),
        ),
    )
    monkeypatch.setattr(
        tray_module,
        "check_api_models",
        lambda: (_ for _ in ()).throw(
            RuntimeError("API fallback should not run in this path")
        ),
    )

    assert tray.check_model() is True  # nosec B101
    assert tray.indicator.icon_calls[-1][0] == tray_module.ICON_OK


def test_check_api_models_success(tray_module, monkeypatch):
    """Return True when API reports loaded models."""
    payload = json.dumps(
        {"data": [{"id": "model", "loaded": True}]}
    ).encode("utf-8")

    monkeypatch.setattr(
        tray_module.urllib_request,
        "urlopen",
        lambda *_a, **_k: DummyUrlResponse(payload),
    )

    assert tray_module.check_api_models() is True  # nosec B101


def test_check_api_models_available_only_returns_false(
    tray_module,
    monkeypatch,
):
    """Return False when API lists only available (not loaded) models."""
    payload = json.dumps(
        {
            "data": [
                {"id": "model-a", "state": "available"},
                {"id": "model-b"},
            ]
        }
    ).encode("utf-8")

    monkeypatch.setattr(
        tray_module.urllib_request,
        "urlopen",
        lambda *_a, **_k: DummyUrlResponse(payload),
    )

    assert tray_module.check_api_models() is False  # nosec B101


def test_check_api_models_error(tray_module, monkeypatch):
    """Return False when API errors or returns invalid JSON."""
    def _raise_error(*_a, **_k):
        raise tray_module.urllib_error.URLError("down")

    monkeypatch.setattr(tray_module.urllib_request, "urlopen", _raise_error)
    assert tray_module.check_api_models() is False  # nosec B101


def test_check_api_models_non_dict_response(tray_module, monkeypatch):
    """Return False when API returns non-dict JSON (e.g. null or list)."""
    for bad_payload in [b"null", b"[]", b'"string"']:
        monkeypatch.setattr(
            tray_module.urllib_request,
            "urlopen",
            lambda *_a, _p=bad_payload, **_k: DummyUrlResponse(_p),
        )
        assert tray_module.check_api_models() is False, (  # nosec B101
            f"Expected False for payload: {bad_payload!r}"
        )


def test_check_api_models_non_list_data_field(tray_module, monkeypatch):
    """Return False when 'data' field is not a list (e.g. null or dict)."""
    for bad_data in [None, {}, "string"]:
        payload = json.dumps({"data": bad_data}).encode("utf-8")
        monkeypatch.setattr(
            tray_module.urllib_request,
            "urlopen",
            lambda *_a, _p=payload, **_k: DummyUrlResponse(_p),
        )
        assert tray_module.check_api_models() is False, (  # nosec B101
            f"Expected False for data value: {bad_data!r}"
        )


def test_get_api_models_url_defaults(tray_module):
    """Build API URL from default host and port."""
    tray_module.sync_app_state_for_tests(
        api_host_val="localhost",
        api_port_val=1234,
    )
    assert tray_module.get_api_models_url() == (
        "http://localhost:1234/v1/models"
    )  # nosec B101


def test_load_config_missing_defaults(tray_module, tmp_path, monkeypatch):
    """Keep defaults when config is missing."""
    tray_module.sync_app_state_for_tests(
        script_dir_val=str(tmp_path),
        api_host_val="localhost",
        api_port_val=1234,
    )
    monkeypatch.setattr(
        tray_module.os.path,
        "expanduser",
        lambda _unused: str(tmp_path / "config.json"),
    )
    tray_module.load_config()
    assert (
        _call_member(tray_module, "_AppState").API_HOST == "localhost"
    )  # nosec B101
    assert (
        _call_member(tray_module, "_AppState").API_PORT == 1234
    )  # nosec B101


def test_load_config_valid_values(tray_module, tmp_path, monkeypatch):
    """Load valid config values into app state."""
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({"api_host": "10.0.0.5", "api_port": 8080}),
        encoding="utf-8",
    )
    tray_module.sync_app_state_for_tests(script_dir_val=str(tmp_path))
    monkeypatch.setattr(
        tray_module.os.path,
        "expanduser",
        lambda _unused: str(config_file),
    )
    tray_module.load_config()
    assert (
        _call_member(tray_module, "_AppState").API_HOST == "10.0.0.5"
    )  # nosec B101
    assert (
        _call_member(tray_module, "_AppState").API_PORT == 8080
    )  # nosec B101


def test_load_config_invalid_port(tray_module, tmp_path, monkeypatch):
    """Ignore invalid port values."""
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({"api_host": "example", "api_port": 99999}),
        encoding="utf-8",
    )
    tray_module.sync_app_state_for_tests(
        script_dir_val=str(tmp_path),
        api_port_val=1234,
    )
    monkeypatch.setattr(
        tray_module.os.path,
        "expanduser",
        lambda _p: str(config_file),
    )
    tray_module.load_config()
    assert (
        _call_member(tray_module, "_AppState").API_HOST == "example"
    )  # nosec B101
    assert (
        _call_member(tray_module, "_AppState").API_PORT == 1234
    )  # nosec B101


def test_normalize_api_port(tray_module):
    """Normalize API port values from strings and invalid inputs."""
    assert (
        _call_member(tray_module, "_normalize_api_port", "8080") == 8080
    )  # nosec B101
    assert (
        _call_member(tray_module, "_normalize_api_port", 65535) == 65535
    )  # nosec B101
    assert (
        _call_member(tray_module, "_normalize_api_port", 0) is None
    )  # nosec B101
    assert (
        _call_member(tray_module, "_normalize_api_port", "bad") is None
    )  # nosec B101


def test_show_config_dialog_cancel(tray_module, monkeypatch):
    """Canceling the config dialog leaves settings unchanged."""
    tray = _make_tray_instance(tray_module)
    tray_module.sync_app_state_for_tests(
        api_host_val="localhost",
        api_port_val=1234,
    )

    original_dialog = tray_module.Gtk.Dialog

    def _dialog_factory(*_args_unused, **_kwargs):
        dialog = original_dialog(**_kwargs)
        setattr(dialog, "_response", tray_module.Gtk.ResponseType.CANCEL)
        return dialog

    monkeypatch.setattr(tray_module.Gtk, "Dialog", _dialog_factory)
    tray.show_config_dialog(None)
    assert (
        _call_member(tray_module, "_AppState").API_HOST == "localhost"
    )  # nosec B101
    assert (
        _call_member(tray_module, "_AppState").API_PORT == 1234
    )  # nosec B101


def test_show_config_dialog_save(tray_module, monkeypatch, tmp_path):
    """Saving the config dialog persists host and port."""
    tray = _make_tray_instance(tray_module)
    tray_module.sync_app_state_for_tests(
        script_dir_val=str(tmp_path),
        api_host_val="localhost",
        api_port_val=1234,
    )
    monkeypatch.setattr(
        tray_module.os.path,
        "expanduser",
        lambda _p: str(tmp_path / "config.json"),
    )

    original_dialog = tray_module.Gtk.Dialog

    def _dialog_factory(**_kwargs):
        dialog = original_dialog(**_kwargs)
        setattr(dialog, "_response", tray_module.Gtk.ResponseType.OK)
        return dialog

    monkeypatch.setattr(tray_module.Gtk, "Dialog", _dialog_factory)
    tray.show_config_dialog(None)
    config_file = tmp_path / "config.json"
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["api_host"] == "localhost"  # nosec B101
    assert data["api_port"] == 1234  # nosec B101


def test_save_config_writes_file(tray_module, tmp_path, monkeypatch):
    """Persist config values to disk."""
    tray_module.sync_app_state_for_tests(script_dir_val=str(tmp_path))
    monkeypatch.setattr(
        tray_module.os.path,
        "expanduser",
        lambda _p: str(tmp_path / "config.json"),
    )
    tray_module.save_config("host", 4321)
    config_file = tmp_path / "config.json"
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["api_host"] == "host"  # nosec B101
    assert data["api_port"] == 4321  # nosec B101


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
    monkeypatch.setattr(
        tray_module.shutil,
        "which",
        lambda x: "/usr/bin/lm-studio",
    )
    assert tray.get_desktop_app_status() == "stopped"  # nosec B101

    app_dir = tmp_path / "Apps"
    app_dir.mkdir()
    (app_dir / "LM-Studio.AppImage").write_text("x", encoding="utf-8")
    tray_module.sync_app_state_for_tests(script_dir_val=str(app_dir))
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


def test_get_desktop_app_status_debug_logs(
    tray_module, monkeypatch, caplog, tmp_path
):
    """When debug logging enabled the lookup emits helpful messages."""
    tray = _make_tray_instance(tray_module)
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(tray_module, "get_desktop_app_pids", lambda: [])
    monkeypatch.setattr(tray_module, "get_dpkg_cmd", lambda: "/usr/bin/dpkg")
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda args: _completed(returncode=0, stdout="lm-studio"),
    )
    monkeypatch.setattr(
        tray_module.shutil,
        "which",
        lambda x: "/usr/bin/lm-studio",
    )
    assert tray.get_desktop_app_status() == "stopped"
    assert "Detected lm-studio installation via dpkg" in caplog.text

    caplog.clear()
    monkeypatch.setattr(tray_module, "get_dpkg_cmd", lambda: None)
    apps_dir = tmp_path / "Apps2"
    apps_dir.mkdir()
    tray_module.sync_app_state_for_tests(script_dir_val=str(apps_dir))
    monkeypatch.setattr(
        tray_module.os.path,
        "isdir",
        lambda p: str(apps_dir) == p,
    )
    monkeypatch.setattr(
        tray_module.os,
        "listdir",
        lambda _unused_p: ["LM-Studio.AppImage"],
    )
    assert tray.get_desktop_app_status() == "stopped"
    assert "Detected AppImage at" in caplog.text


def test_show_status_dialog_ignores_available_only(
    tray_module,
    monkeypatch,
    caplog,
):
    """Ensure show_status_dialog treats `lms ps` output listing only
    available models as no models loaded.
    """
    tray = _make_tray_instance(tray_module)
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(
        tray_module,
        "get_lms_cmd",
        lambda: "/usr/bin/lms",
    )
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda *_unused_a, **_unused_k: _completed(
            returncode=0,
            stdout="foo available\nbar available",
        ),
    )

    class DummyResp:
        """Dummy response for urlopen context manager."""

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc_val, _exc_tb):
            return False

        def read(self):
            """Return empty models list."""
            return b'{"data": []}'

    monkeypatch.setattr(
        tray_module.urllib_request,
        "urlopen",
        lambda *unused_args, **unused_kwargs: DummyResp(),
    )
    tray.show_status_dialog(None)
    dialog = tray_module.Gtk.MessageDialog.last_instance
    assert "No models loaded" in dialog.secondary
    assert "contains only available models" in caplog.text

    caplog.clear()
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda *_unused_a, **_unused_k: _completed(
            returncode=0,
            stdout="No models are currently loaded.",
        ),
    )
    tray.show_status_dialog(None)
    dialog = tray_module.Gtk.MessageDialog.last_instance
    assert "No models loaded" in dialog.secondary
    assert "explicitly reports no models" in caplog.text


def test_check_model_ignores_available_only(tray_module, monkeypatch):
    """check_model must not flip to OK when output only lists
    available models.
    """
    tray = _make_tray_instance(tray_module)
    tray_module.sync_app_state_for_tests()
    monkeypatch.setattr(
        tray,
        "get_daemon_status",
        lambda: "running",
    )
    monkeypatch.setattr(
        tray,
        "get_desktop_app_status",
        lambda: "stopped",
    )
    monkeypatch.setattr(
        tray_module,
        "get_lms_cmd",
        lambda: "/usr/bin/lms",
    )
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda *_unused_a, **_unused_k: _completed(
            returncode=0,
            stdout="foo available\nbar available",
        ),
    )
    monkeypatch.setattr(tray_module, "check_api_models", lambda: False)
    tray.last_status = "INFO"
    tray.check_model()
    assert tray.indicator.icon_calls[-1][0] != tray_module.ICON_OK
    assert "Model loaded" not in tray.indicator.icon_calls[-1][1]

    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda *_unused_a, **_unused_k: _completed(
            returncode=0,
            stdout="No models are currently loaded.",
        ),
    )
    monkeypatch.setattr(tray_module, "check_api_models", lambda: True)
    tray.last_status = "INFO"
    tray.check_model()
    assert tray.indicator.icon_calls[-1][0] != tray_module.ICON_OK
    assert "Model loaded" not in tray.indicator.icon_calls[-1][1]


def test_check_model_cli_no_models_with_api_true_transition(
    tray_module,
    monkeypatch,
):
    """Transition from OK to INFO when CLI says no models but API true."""
    tray = _make_tray_instance(tray_module)
    tray_module.sync_app_state_for_tests()
    monkeypatch.setattr(
        tray_module,
        "get_lms_cmd",
        lambda: "/usr/bin/lms",
    )
    monkeypatch.setattr(
        tray,
        "get_daemon_status",
        lambda: "running",
    )
    monkeypatch.setattr(
        tray,
        "get_desktop_app_status",
        lambda: "running",
    )
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda *_unused_a, **_unused_k: _completed(
            returncode=0,
            stdout="No models are currently loaded.",
        ),
    )
    monkeypatch.setattr(tray_module, "check_api_models", lambda: True)

    tray.last_status = "OK"
    notifications = []
    monkeypatch.setattr(
        tray_module,
        "get_notify_send_cmd",
        lambda: "/n",
    )
    monkeypatch.setattr(
        tray,
        "_run_validated_command",
        lambda cmd: (
            notifications.append(cmd)
            or _completed(returncode=0)
        ),
    )

    tray.check_model()
    assert tray.indicator.icon_calls[-1][0] == tray_module.ICON_INFO
    assert "No model loaded" in tray.indicator.icon_calls[-1][1]
    assert any("no model" in cmd[2].lower() for cmd in notifications)
    assert not any("model loaded" in cmd[2].lower() for cmd in notifications)


def test_home_mask_formatter_masks_home_dir(tray_module):
    """Formatter should replace user's home path with '~'."""
    fmt = tray_module.HomeMaskFormatter("%(message)s")
    home = os.path.expanduser("~")
    rec = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="/some/path",
        lineno=1,
        msg="path is %s",
        args=(home + "/secret",),
        exc_info=None,
    )
    out = fmt.format(rec)
    assert "~" in out
    assert home not in out


def test_logging_handlers_are_replaced(tray_module, tmp_path):
    """
    After calling basicConfig the module loop replaces formatter
    with masking one.
    """
    log_file = str(tmp_path / "log.txt")
    logging.basicConfig(
        filename=log_file,
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s",
        filemode="a",
        force=True,
    )
    root = logging.getLogger()
    for handler in root.handlers:
        handler.setFormatter(
            tray_module.HomeMaskFormatter(
                "%(asctime)s - %(levelname)s - %(message)s"
            )
        )
    assert all(
        isinstance(h.formatter, tray_module.HomeMaskFormatter)
        for h in root.handlers
    )


def test_logging_paths_are_masked(
    tray_module, _tmp_path, _monkeypatch, capsys
):
    """Simulate logging through the module and ensure home is masked."""
    fmt = tray_module.HomeMaskFormatter("%(message)s")
    handler = logging.StreamHandler()
    handler.setFormatter(fmt)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)

    home = os.path.expanduser("~")
    capsys.readouterr()
    logging.debug("starting in %s", home + "/foo")
    captured = capsys.readouterr()
    assert "~/foo" in captured.err
    assert home not in captured.err


def test_dpkg_reports_but_no_executable_fallback_appimage(
    tray_module, monkeypatch, caplog, tmp_path
):
    """
    When dpkg shows package but binary missing, AppImage search
    still runs.
    """
    tray = _make_tray_instance(tray_module)
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(tray_module, "get_dpkg_cmd", lambda: "/usr/bin/dpkg")
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda args, **_k: _completed(returncode=0, stdout="lm-studio"),
    )
    monkeypatch.setattr(tray_module.shutil, "which", lambda _x: None)

    apps_dir = tmp_path / "Apps3"
    apps_dir.mkdir()
    tray_module.sync_app_state_for_tests(script_dir_val=str(apps_dir))
    monkeypatch.setattr(
        tray_module.os.path,
        "isdir",
        lambda p: str(apps_dir) == p,
    )
    monkeypatch.setattr(
        tray_module.os,
        "listdir",
        lambda _unused: ["LM-Studio.AppImage"],
    )

    status = tray.get_desktop_app_status()
    assert status == "stopped"
    assert (
        "dpkg reports lm-studio but executable not in PATH"
        in caplog.text
    )
    assert "Detected AppImage at" in caplog.text


def test_get_desktop_app_status_debug_no_repeat(
    tray_module, monkeypatch, caplog, _tmp_path
):
    """
    Calling get_desktop_app_status twice with the same environment
    only logs once.
    """
    tray = _make_tray_instance(tray_module)
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(
        tray_module, "get_desktop_app_pids", lambda: []
    )
    monkeypatch.setattr(
        tray_module, "get_dpkg_cmd", lambda: "/usr/bin/dpkg"
    )
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda _unused: _completed(returncode=0, stdout="lm-studio"),
    )
    monkeypatch.setattr(
        tray_module.shutil,
        "which",
        lambda _unused: "/usr/bin/lm-studio",
    )
    _ = tray.get_desktop_app_status()
    caplog.clear()
    _ = tray.get_desktop_app_status()
    assert caplog.text == ""


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
    pkill_x = any(
        c[0].endswith("pkill") and "-x" in c for c in calls
    )
    pkill_f = any(
        c[0].endswith("pkill") and "-f" in c for c in calls
    )
    assert pkill_x  # nosec B101
    assert pkill_f  # nosec B101


def test_force_stop_llmster_sigkill_escalation(tray_module, monkeypatch):
    """Escalate to SIGKILL when SIGTERM does not stop llmster in time."""
    tray = _make_tray_instance(tray_module)
    calls = []
    monkeypatch.setattr(
        tray_module.subprocess,
        "run",
        lambda args, **_kwargs: (
            calls.append(args) or _completed(returncode=0)
        ),
    )
    call_count = {"n": 0}

    def _is_running():
        call_count["n"] += 1
        return call_count["n"] <= 13

    monkeypatch.setattr(tray_module, "is_llmster_running", _is_running)
    monkeypatch.setattr(tray_module.time, "sleep", lambda _x: None)
    _call_member(tray, "_force_stop_llmster")
    pkill9_x = any(
        c[0].endswith("pkill") and "-9" in c and "-x" in c
        for c in calls
    )
    pkill9_f = any(
        c[0].endswith("pkill") and "-9" in c and "-f" in c
        for c in calls
    )
    assert pkill9_x  # nosec B101
    assert pkill9_f  # nosec B101


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
    assert any(sig == 9 for _unused_pid, sig in killed)  # nosec B101


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


def test_start_desktop_app_stops_daemon_even_on_false_negative(
    tray_module,
    monkeypatch,
):
    """Abort startup when stop fails despite initial false-negative check."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(tray_module, "is_llmster_running", lambda: False)
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
    popen_called = []

    def fake_popen(*_args, **_kwargs):
        popen_called.append(True)
        return DummyProcess(pid=123)

    monkeypatch.setattr(tray_module.subprocess, "Popen", fake_popen)
    tray.start_desktop_app(None)

    assert not popen_called  # nosec B101


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
    monkeypatch.setattr(
        tray_module.subprocess,
        "Popen",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("fail")),
    )

    notifications = []

    def capture_notify(cmd):
        notifications.append(cmd)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify)

    tray.start_desktop_app(None)
    assert any(  # nosec B101
        "Error" in str(n) for n in notifications
    )


def test_stop_desktop_app_exception_path(tray_module, monkeypatch):
    """Handle exception while stopping desktop app."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_desktop_app_pids", lambda: [123])

    def raise_error():
        raise OSError("fail")

    monkeypatch.setattr(tray, "_stop_desktop_app_processes", raise_error)
    monkeypatch.setattr(
        tray_module, "get_notify_send_cmd", lambda: "/usr/bin/notify-send"
    )

    notifications = []

    def capture_notify(cmd):
        notifications.append(cmd)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify)

    tray.stop_desktop_app(None)
    assert len(notifications) > 0  # nosec B101


def test_show_status_dialog_error_path(tray_module, monkeypatch):
    """Render status dialog with API fallback message when lms is missing."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: None)
    monkeypatch.setattr(
        tray_module.urllib_request,
        "urlopen",
        lambda *_a, **_k: (_ for _ in ()).throw(
            tray_module.urllib_error.URLError("connection refused")
        ),
    )
    tray.show_status_dialog(None)
    dialog = tray_module.Gtk.MessageDialog.last_instance
    assert "No models loaded" in dialog.secondary  # nosec B101


def test_show_status_dialog_success_path(tray_module, monkeypatch):
    """Render status dialog with CLI output on success."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
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

    class DummyResp:
        """A context manager mock for simulating HTTP responses in tests.

        This dummy response object mimics the behavior of a real HTTP response,
        allowing it to be used with context manager syntax (with statement).
        It returns an empty JSON model list when read.
        """
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def read(self):
            """
            Simulates reading data by returning a bytes object
            representing an empty JSON array of models.

            Returns:
                bytes: A JSON-formatted bytes object with an empty
                    "data" list.
            """
            return b'{"data": []}'  # no models
    monkeypatch.setattr(
        tray_module.urllib_request,
        "urlopen",
        lambda *args, **kwargs: DummyResp(),
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


def test_check_model_transition_notifications(
    tray_module,
    monkeypatch,
    caplog,
):
    """Notify on INFO->WARN, WARN->FAIL, and OK->INFO transitions.

    In debug mode we should also log a reason string explaining the
    underlying cause of each change (e.g. daemon started/stopped, model
    loaded/unloaded).  This test exercises both notifications and log
    messages.
    """
    tray = _make_tray_instance(tray_module)
    caplog.set_level(logging.DEBUG)

    monkeypatch.setattr(tray_module, "get_notify_send_cmd", lambda: "/n")
    monkeypatch.setattr(tray_module, "check_api_models", lambda: False)
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
    assert "desktop app stopped" in caplog.text.lower()

    tray.last_status = "WARN"
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "not_found")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "not_found")
    tray.check_model()
    assert "not installed" in caplog.text.lower()

    tray.last_status = "OK"
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    tray.check_model()
    assert "api reported no models" in caplog.text.lower()

    assert len(notifications) >= 3  # nosec B101


def test_check_model_empty_lms_output(tray_module, monkeypatch):
    """Keep INFO status for empty lms output and run OSError."""
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
    monkeypatch.setattr(
        tray_module, "get_notify_send_cmd", lambda: "/usr/bin/notify-send"
    )
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

    def require_version(*args, **kwargs):
        _ = (args, kwargs)
        return None

    monkeypatch.setattr(
        gi_mod,
        "require_version",
        require_version,
        raising=False,
    )
    gtk_mod = DummyGtkModule("gi.repository.Gtk")
    glib_mod = DummyGLibModule("gi.repository.GLib")
    gdkpixbuf_mod = DummyGdkPixbufModule("gi.repository.GdkPixbuf")
    app_mod = DummyAppIndicatorModule("gi.repository.AyatanaAppIndicator3")

    monkeypatch.setitem(sys.modules, "gi", gi_mod)
    monkeypatch.setitem(
        sys.modules,
        "gi.repository",
        ModuleType("gi.repository"),
    )
    monkeypatch.setitem(sys.modules, "gi.repository.Gtk", gtk_mod)
    monkeypatch.setitem(sys.modules, "gi.repository.GLib", glib_mod)
    monkeypatch.setitem(sys.modules, "gi.repository.GdkPixbuf", gdkpixbuf_mod)
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
        if name == "gi.repository.GdkPixbuf":
            return gdkpixbuf_mod
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
        sys.argv = ["lmstudio_tray.py", "--debug", "m", str(tmp_path)]
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
    """Auto-start always stops then starts daemon for fresh passkey."""
    tray = _make_tray_instance(tray_module)
    tray_module.sync_app_state_for_tests(auto_start_val=True)
    tray.action_lock_until = 123.0
    calls = []

    def record_stop_with_notification():
        calls.append("stop")

    def record_start(_widget):
        calls.append("start")

    monkeypatch.setattr(
        tray,
        "_stop_daemon_with_notification",
        record_stop_with_notification,
    )
    monkeypatch.setattr(tray, "start_daemon", record_start)
    result = _call_member(tray, "_maybe_auto_start_daemon")
    assert result is False  # nosec B101
    assert calls == ["stop", "start"]  # nosec B101
    assert tray.action_lock_until == 0.0  # nosec B101


def test_maybe_start_gui(monkeypatch, tray_module):
    """Invoke GUI start path when enabled."""
    tray = _make_tray_instance(tray_module)
    tray_module.sync_app_state_for_tests(gui_mode_val=True)
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
    with pytest.raises(ValueError, match="non-empty list"):
        _call_member(tray_module, "_run_safe_command", [])
    with pytest.raises(ValueError, match="non-empty list"):
        _call_member(tray_module, "_run_safe_command", "string")
    with pytest.raises(ValueError, match="must be strings"):
        _call_member(tray_module, "_run_safe_command", ["/bin/ls", 123])
    with pytest.raises(ValueError, match="absolute path"):
        _call_member(tray_module, "_run_safe_command", ["ls", "-l"])


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

    monkeypatch.setattr(tray_module, "get_pgrep_cmd", lambda: None)
    tray_module.kill_existing_instances()

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
        return 12345

    def mock_kill(pid, _sig):
        if pid == 99999:
            err = PermissionError("denied")
            errors_raised.append(err)
            raise err

    monkeypatch.setattr(tray_module.os, "getpid", mock_getpid)
    monkeypatch.setattr(tray_module.os, "kill", mock_kill)
    tray_module.kill_existing_instances()
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


def test_get_desktop_app_status_ignores_bench_appimage(
    tray_module, monkeypatch, tmp_path
):
    """Do not treat LM-Studio-Bench AppImage as desktop app install."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_desktop_app_pids", lambda: [])
    monkeypatch.setattr(tray_module, "get_dpkg_cmd", lambda: None)

    apps_dir = tmp_path / "Apps"
    apps_dir.mkdir()
    (apps_dir / "LM-Studio-Bench-x86_64.AppImage").touch()

    monkeypatch.setattr(
        tray_module.os.path,
        "expanduser",
        lambda p: str(apps_dir) if "Apps" in p else "/nonexistent",
    )
    monkeypatch.setattr(
        tray_module.os.path,
        "isdir",
        lambda p: str(p) == str(apps_dir),
    )

    result = _call_member(tray, "get_desktop_app_status")
    assert result == "not_found"  # nosec B101


def test_is_lm_studio_appimage_label_variants(tray_module):
    """Accept LM Studio Desktop App names and reject other tools."""
    assert _call_member(  # nosec B101
        tray_module,
        "_is_lm_studio_appimage_label",
        "LM-Studio-0.4.6-1-x64_f041fd4c995356505e187941a4c78adf.AppImage",
    )
    assert _call_member(  # nosec B101
        tray_module,
        "_is_lm_studio_appimage_label",
        "LM Studio.AppImage",
    )
    assert _call_member(  # nosec B101
        tray_module,
        "_is_lm_studio_appimage_label",
        "LM-Studio.AppImage",
    )
    assert not _call_member(  # nosec B101
        tray_module,
        "_is_lm_studio_appimage_label",
        "LM-Studio-Bench-x86_64.AppImage",
    )
    assert not _call_member(  # nosec B101
        tray_module,
        "_is_lm_studio_appimage_label",
        "lmstudio-tray-manager-0.6.2.AppImage",
    )


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
    monkeypatch.setattr(
        tray_module, "get_notify_send_cmd", lambda: "/usr/bin/notify-send"
    )

    call_count = {"count": 0}

    def raise_runtime_on_daemon(*_args, **_k):
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

    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(
        tray_module.os.path, "isfile", lambda _p: True
    )
    monkeypatch.setattr(tray_module.os, "access", lambda _p, _m: True)
    monkeypatch.setattr(
        tray_module, "get_notify_send_cmd", lambda: "/usr/bin/notify-send"
    )

    notifications = []

    def capture_notify(cmd):
        notifications.append(cmd)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify)

    _call_member(tray, "start_desktop_app", None)
    assert len(notifications) > 0  # nosec B101


def test_stop_desktop_app_no_pids(tray_module, monkeypatch):
    """Handle no running processes when stopping desktop app."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    monkeypatch.setattr(tray_module, "get_desktop_app_pids", lambda: [])
    monkeypatch.setattr(
        tray_module, "get_notify_send_cmd", lambda: "/usr/bin/notify-send"
    )

    notifications = []

    def capture_notify(cmd):
        notifications.append(cmd)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify)

    _call_member(tray, "stop_desktop_app", None)
    assert len(notifications) > 0  # nosec B101
    assert any("No running" in str(n) for n in notifications)  # nosec B101


def test_stop_desktop_app_success_and_failure(tray_module, monkeypatch):
    """Cover success and failure paths when stopping desktop app."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray, "begin_action_cooldown", lambda _x: True)
    pids_list = [[123, 456], [789]]
    monkeypatch.setattr(
        tray_module, "get_desktop_app_pids", lambda: pids_list.pop(0)
    )
    monkeypatch.setattr(
        tray_module,
        "get_notify_send_cmd",
        lambda: "/usr/bin/notify-send",
    )
    stop_results = [True, False]

    def mock_stop():
        return stop_results.pop(0)

    monkeypatch.setattr(tray, "_stop_desktop_app_processes", mock_stop)

    notifications = []

    def capture_notify(cmd):
        notifications.append(cmd)
        return _completed(returncode=0)

    monkeypatch.setattr(tray, "_run_validated_command", capture_notify)

    _call_member(tray, "stop_desktop_app", None)
    _call_member(tray, "stop_desktop_app", None)
    assert len(notifications) >= 2  # nosec B101


def test_run_daemon_attempts_invalid_command_format(tray_module):
    """Skip invalid command formats in _run_daemon_attempts."""
    tray = _make_tray_instance(tray_module)

    attempts = ["not_a_list", {"invalid": "dict"}, 123]
    result = _call_member(
        tray, "_run_daemon_attempts", attempts, lambda _r: False
    )
    assert result is None  # nosec B101

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


def test_parse_args_script_dir_normalized(tmp_path, tray_module):
    """When the user provides a relative script directory it becomes
    absolute after applying CLI args.

    The tray application should always operate with an absolute path
    because various subsystems (logging, file lookups) depend on it.
    This mirrors the behavior of :func:`_get_default_script_dir` for the
    default case, but we now explicitly convert user input as well.
    """
    base = tmp_path / "base"
    base.mkdir()
    rel = "relative/dir"
    abs_dir = os.path.abspath(os.path.join(str(base), rel))

    old_argv = sys.argv[:]
    try:
        sys.argv = ["prog", "mymodel", rel]
        args = tray_module.parse_args()
        _call_member(tray_module, "_AppState").apply_cli_args(args)
        assert (
            _call_member(tray_module, "_AppState").script_dir  # nosec B101
            == os.path.abspath(rel)
        )
        assert os.path.isabs(
            _call_member(tray_module, "_AppState").script_dir
        )  # nosec B101
        sys.argv = ["prog", "mymodel", abs_dir]
        args2 = tray_module.parse_args()
        _call_member(tray_module, "_AppState").apply_cli_args(args2)
        assert (
            _call_member(tray_module, "_AppState").script_dir == abs_dir
        )  # nosec B101
    finally:
        sys.argv = old_argv


def test_validate_url_scheme_valid_http(tray_module):
    """Validate that _validate_url_scheme accepts http URLs."""
    _call_member(tray_module, "_validate_url_scheme", "http://localhost:1234")


def test_validate_url_scheme_valid_https(tray_module):
    """Validate that _validate_url_scheme accepts https URLs."""
    _call_member(
        tray_module, "_validate_url_scheme", "https://api.example.com"
    )


def test_validate_url_scheme_invalid_file(tray_module):
    """Reject file:// URLs for security."""
    with pytest.raises(ValueError, match="scheme 'file' not permitted"):
        _call_member(tray_module, "_validate_url_scheme", "file:///etc/passwd")


def test_validate_url_scheme_invalid_ftp(tray_module):
    """Reject ftp:// URLs for security."""
    with pytest.raises(ValueError, match="scheme 'ftp' not permitted"):
        _call_member(
            tray_module, "_validate_url_scheme", "ftp://ftp.example.com"
        )


def test_show_status_dialog_api_fallback_lms_fail(
    tray_module, monkeypatch
):
    """Test show_status_dialog API fallback when lms ps fails."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda *_a, **_k: _completed(returncode=1, stdout=""),
    )

    api_response = {
        "data": [
            {"id": "mistralai/mistral-7b", "loaded": True},
            {"id": "openai/gpt-3", "loaded": True},
        ]
    }

    def mock_urlopen_json(*_a, **_k):
        response = DummyContextManager()
        response.payload = json.dumps(api_response).encode("utf-8")
        return response

    class DummyContextManager:
        """Dummy context manager for testing purposes.

        This class simulates a context manager that can be used in
        with statements. It provides a read() method that returns a
        payload and supports the context manager protocol via
        __enter__ and __exit__ methods.

        Attributes:
            payload (bytes): The data returned by read(). Defaults
                to an empty bytes object.
        """
        payload = b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            ...

        def read(self):
            """
            Retrieve the payload data.

            Returns:
                Any: The payload data stored in this object.
            """
            return self.payload

    monkeypatch.setattr(
        tray_module.urllib_request, "urlopen", mock_urlopen_json
    )

    tray.show_status_dialog(None)
    dialog = tray_module.Gtk.MessageDialog.last_instance
    assert "Models loaded via desktop app:" in dialog.secondary  # nosec


def test_show_status_dialog_api_fallback_no_lms(
    tray_module, monkeypatch
):
    """Test show_status_dialog API fallback when lms not available."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: None)

    api_response = {
        "data": [{"id": "meta/llama2", "loaded": True}]
    }

    def mock_urlopen_json(*_a, **_k):
        response = DummyContextManager()
        response.payload = json.dumps(api_response).encode("utf-8")
        return response

    class DummyContextManager:
        """A dummy context manager for testing purposes.

        This class simulates a context manager that holds a
        payload of bytes data. It can be used in with statements
        and provides a read method to retrieve the stored payload.
        """
        payload = b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            ...

        def read(self):
            """Retrieve the payload data.

            Returns:
                The payload content stored in this instance.
            """
            return self.payload

    monkeypatch.setattr(
        tray_module.urllib_request, "urlopen", mock_urlopen_json
    )

    tray.show_status_dialog(None)
    dialog = tray_module.Gtk.MessageDialog.last_instance
    assert "Models loaded via desktop app:" in dialog.secondary  # nosec B101


def test_show_status_dialog_api_invalid_json(
    tray_module, monkeypatch
):
    """Test show_status_dialog with invalid JSON from API."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda *_a, **_k: _completed(returncode=1, stdout=""),
    )

    def mock_urlopen_bad(*_a, **_k):
        response = DummyContextManager()
        response.payload = b"invalid json"
        return response

    class DummyContextManager:
        """A dummy context manager for testing purposes.

        This class simulates a context manager that holds a
        payload of bytes data. It can be used in with statements
        and provides a read() method to retrieve the stored
        payload.

        Attributes:
            payload (bytes): The data payload stored in this
                context manager.
        """
        payload = b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            ...

        def read(self):
            """Return the payload data stored in this object.

            Returns:
                The payload data.
            """
            return self.payload

    monkeypatch.setattr(
        tray_module.urllib_request, "urlopen", mock_urlopen_bad
    )

    tray.show_status_dialog(None)
    dialog = tray_module.Gtk.MessageDialog.last_instance
    assert "No models loaded" in dialog.secondary  # nosec B101


def test_show_status_dialog_api_non_dict_response(
    tray_module, monkeypatch
):
    """Test show_status_dialog with non-dict from API."""
    tray = _make_tray_instance(tray_module)
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda *_a, **_k: _completed(returncode=1, stdout=""),
    )

    class DummyContextManager:
        """Dummy context manager for API response testing."""

        payload = b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            ...

        def read(self):
            """
            Retrieve the payload data.

            Returns:
                The stored payload object.
            """
            return self.payload

    def mock_urlopen_list(*_a, **_k):
        """Return a list instead of dict to test error handling."""
        response = DummyContextManager()
        response.payload = b"[]"
        return response

    monkeypatch.setattr(
        tray_module.urllib_request, "urlopen", mock_urlopen_list
    )

    tray.show_status_dialog(None)
    dialog = tray_module.Gtk.MessageDialog.last_instance
    assert "No models loaded" in dialog.secondary  # nosec B101


def test_check_api_models_with_invalid_data(tray_module, monkeypatch):
    """Test check_api_models with invalid data structure."""

    def mock_urlopen_invalid(*_a, **_k):
        response = DummyContextManager()
        response.payload = json.dumps({"invalid": "structure"}).encode(
            "utf-8"
        )
        return response

    class DummyContextManager:
        """
        Dummy context manager for API response testing.
        This class simulates a context manager that can be used in
        with statements. It provides a read() method that returns a
        payload and supports the context manager protocol via
        __enter__ and __exit__ methods."""

        payload = b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            ...

        def read(self):
            """
            Read and return the payload data.

            Returns:
                The payload content stored in the instance."""
            return self.payload

    monkeypatch.setattr(
        tray_module.urllib_request, "urlopen", mock_urlopen_invalid
    )

    result = tray_module.check_api_models()
    assert result is False  # nosec B101


def test_get_default_script_dir_with_argv(tray_module, monkeypatch):
    """Test _get_default_script_dir returns directory from sys.argv[0]."""
    test_script_path = "/home/user/project/script.py"
    monkeypatch.setattr(sys, "argv", [test_script_path])
    result = _call_member(tray_module, "_get_default_script_dir")
    assert result == "/home/user/project"  # nosec B101


def test_get_default_script_dir_fallback_to_cwd(tray_module, monkeypatch):
    """Test _get_default_script_dir falls back to cwd when argv is empty."""
    monkeypatch.setattr(sys, "argv", [])
    monkeypatch.setattr(os, "getcwd", lambda: "/fallback/directory")
    result = _call_member(tray_module, "_get_default_script_dir")
    assert result == "/fallback/directory"  # nosec B101


def test_parse_args_both_flags_true(tray_module, monkeypatch):
    """Test parsing when both --auto-start-daemon and --gui are provided."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["lmstudio_tray.py", "--auto-start-daemon", "--gui"]
    )
    args = tray_module.parse_args()
    assert args.auto_start_daemon is True  # nosec B101
    assert args.gui is True  # nosec B101


def test_get_default_script_dir_with_none_argv(tray_module, monkeypatch):
    """Test _get_default_script_dir when sys.argv[0] is None."""
    monkeypatch.setattr(sys, "argv", [None])
    monkeypatch.setattr(os, "getcwd", lambda: "/current/dir")
    result = _call_member(tray_module, "_get_default_script_dir")
    assert result == "/current/dir"  # nosec B101


def test_get_asset_path_prefers_meipass(tray_module, tmp_path, monkeypatch):
    """Prefer bundled PyInstaller assets when _MEIPASS is present."""
    meipass_dir = tmp_path / "bundle"
    meipass_asset = meipass_dir / "assets" / "img" / "icon.svg"
    meipass_asset.parent.mkdir(parents=True)
    meipass_asset.write_text("svg", encoding="utf-8")

    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)
    tray_module.sync_app_state_for_tests(script_dir_val=str(tmp_path / "x"))

    result = tray_module.get_asset_path("img", "icon.svg")
    assert result == str(meipass_asset)  # nosec B101


def test_get_asset_path_falls_back_to_script_dir(
    tray_module, tmp_path, monkeypatch
):
    """Return asset from script_dir when bundle assets are unavailable."""
    script_dir = tmp_path / "script"
    script_asset = script_dir / "assets" / "img" / "icon.svg"
    script_asset.parent.mkdir(parents=True)
    script_asset.write_text("svg", encoding="utf-8")

    monkeypatch.setattr(sys, "_MEIPASS", None, raising=False)
    tray_module.sync_app_state_for_tests(script_dir_val=str(script_dir))

    result = tray_module.get_asset_path("img", "icon.svg")
    assert result == str(script_asset)  # nosec B101


def test_get_asset_path_falls_back_to_cwd(tray_module, tmp_path, monkeypatch):
    """Return asset from current working directory as last fallback."""
    cwd_dir = tmp_path / "cwd"
    cwd_asset = cwd_dir / "assets" / "img" / "icon.svg"
    cwd_asset.parent.mkdir(parents=True)
    cwd_asset.write_text("svg", encoding="utf-8")

    monkeypatch.setattr(sys, "_MEIPASS", None, raising=False)
    tray_module.sync_app_state_for_tests(script_dir_val=str(tmp_path / "none"))
    monkeypatch.chdir(cwd_dir)

    result = tray_module.get_asset_path("img", "icon.svg")
    assert result == str(cwd_asset)  # nosec B101


def test_get_asset_path_returns_none_when_missing(
    tray_module, tmp_path, monkeypatch
):
    """Return None when asset does not exist in any search location."""
    monkeypatch.setattr(sys, "_MEIPASS", None, raising=False)
    tray_module.sync_app_state_for_tests(script_dir_val=str(tmp_path / "none"))
    monkeypatch.chdir(tmp_path)

    result = tray_module.get_asset_path("img", "missing.svg")
    assert result is None  # nosec B101


def test_save_config_replace_failure_removes_tmp(
    tray_module, tmp_path, monkeypatch
):
    """Clean up temporary file if final replace fails."""
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(
        tray_module.os.path,
        "expanduser",
        lambda _p: str(config_file),
    )

    def _raise_replace(_src, _dst):
        raise OSError("replace failed")

    monkeypatch.setattr(tray_module.os, "replace", _raise_replace)

    with pytest.raises(OSError):
        tray_module.save_config("host", 1234)

    assert not (tmp_path / "config.json.tmp").exists()  # nosec B101


def test_save_config_replace_failure_remove_failure(
    tray_module, tmp_path, monkeypatch
):
    """Keep original error when tmp cleanup also fails."""
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(
        tray_module.os.path,
        "expanduser",
        lambda _p: str(config_file),
    )

    def _raise_replace(_src, _dst):
        raise OSError("replace failed")

    def _raise_remove(_path):
        raise OSError("remove failed")

    monkeypatch.setattr(tray_module.os, "replace", _raise_replace)
    monkeypatch.setattr(tray_module.os, "remove", _raise_remove)

    with pytest.raises(OSError):
        tray_module.save_config("host", 1234)


def test_validate_url_scheme_invalid_host_with_whitespace(tray_module):
    """Reject hosts containing whitespace."""
    tray_module.sync_app_state_for_tests(api_host_val="bad host")
    tray_module.sync_app_state_for_tests(api_port_val=1234)

    with pytest.raises(ValueError):
        _call_member(tray_module, "_validate_url_scheme", "http://x")


def test_validate_url_scheme_invalid_host_with_path_chars(tray_module):
    """Reject hosts containing slash/query/hash delimiters."""
    tray_module.sync_app_state_for_tests(api_host_val="example.com/path")
    tray_module.sync_app_state_for_tests(api_port_val=1234)

    with pytest.raises(ValueError):
        _call_member(tray_module, "_validate_url_scheme", "http://x")


def test_validate_url_scheme_invalid_single_colon_host(tray_module):
    """Reject host:port literals in API_HOST.

    Port is configured separately.
    """
    tray_module.sync_app_state_for_tests(api_host_val="localhost:8080")
    tray_module.sync_app_state_for_tests(api_port_val=1234)

    with pytest.raises(ValueError):
        _call_member(tray_module, "_validate_url_scheme", "http://x")


def test_validate_url_scheme_wraps_ipv6_host(tray_module):
    """Wrap bare IPv6 hosts in brackets when building endpoint URL."""
    tray_module.sync_app_state_for_tests(api_host_val="2001:db8::1")
    tray_module.sync_app_state_for_tests(api_port_val=1234)

    result = _call_member(tray_module, "_validate_url_scheme", "http://x")
    assert result == "http://[2001:db8::1]:1234"  # nosec B101


def test_validate_url_scheme_rejects_invalid_port(tray_module):
    """Reject out-of-range API ports."""
    tray_module.sync_app_state_for_tests(api_host_val="localhost")
    tray_module.sync_app_state_for_tests(api_port_val=70000)

    with pytest.raises(ValueError):
        _call_member(tray_module, "_validate_url_scheme", "http://x")


def test_show_config_dialog_without_gtk_logs_error(tray_module, monkeypatch):
    """Return early when GTK module is unavailable."""
    tray = _make_tray_instance(tray_module)
    app_state = _call_member(tray_module, "_AppState")
    monkeypatch.setattr(app_state, "Gtk", None)

    tray.show_config_dialog(None)


def test_show_config_dialog_save_error_shows_error_dialog(
    tray_module, monkeypatch
):
    """Display a GTK error dialog when save_config raises."""
    tray = _make_tray_instance(tray_module)
    tray_module.sync_app_state_for_tests(
        api_host_val="localhost",
        api_port_val=1234,
    )

    original_dialog = tray_module.Gtk.Dialog

    def _dialog_factory(**_kwargs):
        dialog = original_dialog(**_kwargs)
        setattr(dialog, "_response", tray_module.Gtk.ResponseType.OK)
        return dialog

    def _raise_save(_host, _port):
        raise OSError("disk full")

    monkeypatch.setattr(
        tray_module.Gtk.MessageType,
        "ERROR",
        tray_module.Gtk.MessageType.INFO,
        raising=False,
    )
    monkeypatch.setattr(tray_module.Gtk, "Dialog", _dialog_factory)
    monkeypatch.setattr(tray_module, "save_config", _raise_save)

    tray.show_config_dialog(None)

    error_dialog = tray_module.Gtk.MessageDialog.last_instance
    assert error_dialog is not None  # nosec B101
    assert error_dialog.ran is True  # nosec B101
    assert error_dialog.destroyed is True  # nosec B101
    assert "Failed to save configuration" in error_dialog.text  # nosec B101


def test_show_config_dialog_invalid_input_warns(tray_module, monkeypatch):
    """Do not save when host/port input is invalid."""
    tray = _make_tray_instance(tray_module)
    tray_module.sync_app_state_for_tests(
        api_host_val="",
        api_port_val="invalid",
    )

    original_dialog = tray_module.Gtk.Dialog

    def _set_response(dialog, response):
        _call_member(dialog, "__setattr__", "_response", response)

    def _dialog_factory(**_kwargs):
        dialog = original_dialog(**_kwargs)
        _set_response(dialog, tray_module.Gtk.ResponseType.OK)
        return dialog

    called = {"save": False}

    def _save_marker(_host, _port):
        called["save"] = True

    monkeypatch.setattr(tray_module.Gtk, "Dialog", _dialog_factory)
    monkeypatch.setattr(tray_module, "save_config", _save_marker)

    tray.show_config_dialog(None)
    assert called["save"] is False  # nosec B101


def test_run_validated_command_adds_info_icon_to_notify(
    tray_module, monkeypatch
):
    """Prepend info icon for notify-send messages without icon prefix."""
    calls = []

    def _capture(command):
        calls.append(command)
        return _completed(returncode=0)

    monkeypatch.setattr(tray_module, "_run_safe_command", _capture)

    _call_member(
        tray_module.TrayIcon,
        "_run_validated_command",
        ["/usr/bin/notify-send", "Title", "message"],
    )

    assert calls[0][2] == "ℹ️ message"  # nosec B101


def test_run_validated_command_keeps_existing_icon(tray_module, monkeypatch):
    """Keep existing icon prefix on notify-send messages."""
    calls = []

    def _capture(command):
        calls.append(command)
        return _completed(returncode=0)

    monkeypatch.setattr(tray_module, "_run_safe_command", _capture)

    _call_member(
        tray_module.TrayIcon,
        "_run_validated_command",
        ["/usr/bin/notify-send", "Title", "✅ already"],
    )

    assert calls[0][2] == "✅ already"  # nosec B101


def test_run_daemon_attempts_breaks_on_timeout(tray_module, monkeypatch):
    """Stop daemon attempt loop when a command times out."""
    tray = _make_tray_instance(tray_module)

    def _timeout(_command):
        raise subprocess.TimeoutExpired(cmd="cmd", timeout=1)

    monkeypatch.setattr(tray, "_run_validated_command", _timeout)
    attempts = [["/bin/echo", "x"]]

    result = _call_member(
        tray,
        "_run_daemon_attempts",
        attempts,
        lambda _r: False,
    )
    assert result is None  # nosec B101


def test_start_desktop_app_daemon_still_running_after_verification(
    tray_module, monkeypatch
):
    """Notify and abort GUI launch when daemon still runs after stop."""
    tray = _make_tray_instance(tray_module)
    notify_calls = []

    states = [False, True]

    def _is_running():
        return states.pop(0) if states else True

    def _capture_notify(command):
        notify_calls.append(command)
        return _completed(returncode=0)

    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(tray_module, "is_llmster_running", _is_running)
    monkeypatch.setattr(
        tray,
        "_stop_daemon_with_notification",
        lambda: (True, None),
    )
    monkeypatch.setattr(
        tray_module,
        "get_notify_send_cmd",
        lambda: "/usr/bin/notify-send",
    )
    monkeypatch.setattr(tray, "_run_validated_command", _capture_notify)

    tray.start_desktop_app(None)

    assert any("Daemon could not be stopped" in str(c) for c in notify_calls)


@pytest.mark.parametrize(
    "api_has_models,expected_icon",
    [(True, "emblem-default"), (False, "dialog-information")],
)
def test_check_model_daemon_running_without_lms_ps_uses_api(
    tray_module,
    monkeypatch,
    api_has_models,
    expected_icon,
):
    """Use API fallback when daemon runs and lms-ps path is skipped."""
    tray = _make_tray_instance(tray_module)
    tray.last_status = "WARN"

    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(tray, "_can_use_lms_ps", lambda *_a: False)
    monkeypatch.setattr(
        tray_module,
        "check_api_models",
        lambda: api_has_models,
    )
    monkeypatch.setattr(tray_module, "get_notify_send_cmd", lambda: None)

    assert tray.check_model() is True  # nosec B101
    assert tray.indicator.icon_calls[-1][0] == expected_icon  # nosec B101


def test_check_model_app_running_lms_ps_no_models_sets_info(
    tray_module, monkeypatch
):
    """Set INFO when lms ps succeeds but reports no loaded model."""
    tray = _make_tray_instance(tray_module)
    tray.last_status = "WARN"

    monkeypatch.setattr(tray, "get_daemon_status", lambda: "stopped")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "running")
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(tray, "_can_use_lms_ps", lambda *_a: True)
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=0, stdout="available models only"),
    )
    monkeypatch.setattr(tray_module, "check_api_models", lambda: False)
    monkeypatch.setattr(tray_module, "get_notify_send_cmd", lambda: None)

    assert tray.check_model() is True  # nosec B101
    assert (
        tray.indicator.icon_calls[-1][0]
        == "dialog-information"
    )  # nosec B101


def test_check_model_app_running_lms_ps_error_uses_api_false(
    tray_module, monkeypatch
):
    """Set INFO when lms ps fails and API reports no loaded models."""
    tray = _make_tray_instance(tray_module)
    tray.last_status = "WARN"

    monkeypatch.setattr(tray, "get_daemon_status", lambda: "stopped")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "running")
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(tray, "_can_use_lms_ps", lambda *_a: True)
    monkeypatch.setattr(
        tray_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=1, stdout="", stderr="boom"),
    )
    monkeypatch.setattr(tray_module, "check_api_models", lambda: False)
    monkeypatch.setattr(tray_module, "get_notify_send_cmd", lambda: None)

    assert tray.check_model() is True  # nosec B101
    assert (
        tray.indicator.icon_calls[-1][0]
        == "dialog-information"
    )  # nosec B101


def test_check_model_any_running_without_lms_uses_api_true(
    tray_module, monkeypatch
):
    """Set OK when runtime is active and API reports loaded models."""
    tray = _make_tray_instance(tray_module)
    tray.last_status = "WARN"

    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(tray_module, "get_lms_cmd", lambda: None)
    monkeypatch.setattr(tray_module, "check_api_models", lambda: True)
    monkeypatch.setattr(tray_module, "get_notify_send_cmd", lambda: None)

    assert tray.check_model() is True  # nosec B101
    assert tray.indicator.icon_calls[-1][0] == "emblem-default"  # nosec B101


class DummyRumpsMenuItem:
    """Lightweight rumps.MenuItem stub for testing."""

    def __init__(self, title="", callback=None, **_kwargs):
        """Initialize a dummy menu item."""
        self.title = title
        self.callback = callback
        self._children = []

    def add(self, item):
        """Add a child menu item."""
        self._children.append(item)


class DummyRumpsMenu:
    """Lightweight rumps.Menu stub."""

    def __init__(self):
        """Initialize an empty menu."""
        self._items = []

    def clear(self):
        """Clear all menu items."""
        self._items.clear()

    def update(self, items):
        """Add new items to the menu."""
        for item in items:
            self._items.append(item)

    def __iter__(self):
        """Iterate over menu items."""
        return iter(self._items)


class DummyRumpsTimer:
    """Lightweight rumps.Timer stub."""

    def __init__(self, callback, interval):
        """Initialize a dummy timer."""
        self.callback = callback
        self.interval = interval
        self.running = False

    def start(self):
        """Mark timer as started."""
        self.running = True

    def stop(self):
        """Mark timer as stopped."""
        self.running = False


class DummyRumpsApp:
    """Base class stub for rumps.App."""

    def __init__(self, name, **_kwargs):
        """Initialize the app stub."""
        self.name = name
        self.title = ""
        self.menu = DummyRumpsMenu()
        self.icon = None

    def run(self):
        """Stub run method - does nothing in tests."""


class DummyRumpsModule(ModuleType):
    """Stub for the rumps module used in macOS tray tests."""

    App = DummyRumpsApp
    MenuItem = DummyRumpsMenuItem
    Timer = DummyRumpsTimer
    _notifications = []
    _alerts = []
    _quit_called = False

    @staticmethod
    def notification(title="", subtitle="", message="", sound=False):
        """Record a notification call."""
        DummyRumpsModule._notifications.append(
            (title, subtitle, message)
        )

    @staticmethod
    def alert(title="", message=""):
        """Record an alert call."""
        DummyRumpsModule._alerts.append((title, message))

    @staticmethod
    def quit_application():
        """Record quit call."""
        DummyRumpsModule._quit_called = True

    @classmethod
    def get_notifications(cls):
        """Get the list of recorded notifications."""
        return cls._notifications

    @classmethod
    def get_alerts(cls):
        """Get the list of recorded alerts."""
        return cls._alerts

    @classmethod
    def is_quit_called(cls):
        """Check if quit was called."""
        return cls._quit_called

    @classmethod
    def reset(cls):
        """Reset recorded state between tests."""
        cls._notifications.clear()
        cls._alerts.clear()
        cls._quit_called = False


@pytest.fixture(name="macos_module")
def macos_module_fixture(monkeypatch, tmp_path):
    """Load lmstudio_tray with IS_MACOS=True and a rumps stub."""
    rumps_stub = DummyRumpsModule("rumps")
    DummyRumpsModule.reset()

    monkeypatch.setitem(sys.modules, "rumps", rumps_stub)

    gi_mod = ModuleType("gi")
    monkeypatch.setattr(
        gi_mod,
        "require_version",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    monkeypatch.setitem(sys.modules, "gi", gi_mod)

    def safe_run(*_args, **_kwargs):
        """Return a safe default subprocess result during import."""
        return _completed(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", safe_run)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(os, "getpid", lambda: 99999)

    module_name = "lmstudio_tray_macos"
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

    monkeypatch.setattr(module, "IS_MACOS", True)
    monkeypatch.setattr(module, "_rumps_lib", rumps_stub)
    monkeypatch.setattr(module, "_RumpsBase", DummyRumpsApp)

    yield module


def _make_macos_tray(module):
    """Build a partially initialised MacOSTrayIcon for unit tests."""
    tray = module.MacOSTrayIcon.__new__(module.MacOSTrayIcon)
    tray.title = "⚠️"
    tray.menu = DummyRumpsMenu()
    tray.last_status = None
    tray.action_lock_until = 0.0
    tray.lms_ps_resume_at = 0.0
    _call_member(tray, "__setattr__", "_seen_desktop_call", False)
    _call_member(tray, "__setattr__", "_last_desktop_detection", None)
    tray.last_update_version = None
    tray.update_status = "Unknown"
    tray.latest_update_version = None
    tray.last_update_error = None
    tray.build_menu = lambda: None
    return tray


def test_is_macos_flag_exists(tray_module):
    """IS_MACOS must be a boolean attribute on the module."""
    assert isinstance(tray_module.IS_MACOS, bool)  # nosec B101


def test_rumps_base_is_object_when_rumps_missing(tray_module):
    """_RumpsBase is 'object' when rumps is not installed."""
    assert (
        _call_member(tray_module, "__getattribute__", "_rumps_lib") is None
    )  # nosec B101
    assert (
        _call_member(tray_module, "__getattribute__", "_RumpsBase") is object
    )  # nosec B101


def test_get_desktop_app_pids_macos_app_detected(
    macos_module, monkeypatch
):
    """macOS process table entry for LM Studio.app is recognised."""
    ps_output = (
        "1234 /Applications/LM Studio.app/Contents/MacOS/LM Studio\n"
        "5678 --type=renderer something\n"
    )
    monkeypatch.setattr(
        macos_module,
        "get_ps_cmd",
        lambda: "/bin/ps",
    )
    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=0, stdout=ps_output),
    )
    pids = macos_module.get_desktop_app_pids()
    assert pids == [1234]  # nosec B101


def test_get_desktop_app_pids_macos_excludes_linux_patterns(
    macos_module, monkeypatch
):
    """On macOS, Linux-specific .appimage paths are not matched."""
    ps_output = (
        "9999 /home/user/LM-Studio-0.4.0-x86_64.AppImage --no-sandbox\n"
    )
    monkeypatch.setattr(macos_module, "get_ps_cmd", lambda: "/bin/ps")
    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=0, stdout=ps_output),
    )
    assert macos_module.get_desktop_app_pids() == []  # nosec B101


def test_get_desktop_app_pids_macos_lm_studio_process_name(
    macos_module, monkeypatch
):
    """Bare 'LM Studio' process name is matched on macOS."""
    ps_output = "1111 LM Studio\n"
    monkeypatch.setattr(macos_module, "get_ps_cmd", lambda: "/bin/ps")
    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=0, stdout=ps_output),
    )
    assert macos_module.get_desktop_app_pids() == [1111]  # nosec B101


def test_macos_get_daemon_status_not_found(macos_module, monkeypatch):
    """Returns 'not_found' when llmster is absent."""
    tray = _make_macos_tray(macos_module)
    monkeypatch.setattr(macos_module, "get_llmster_cmd", lambda: None)
    assert tray.get_daemon_status() == "not_found"  # nosec B101


def test_macos_get_daemon_status_running(macos_module, monkeypatch):
    """Returns 'running' when llmster process is detected."""
    tray = _make_macos_tray(macos_module)
    monkeypatch.setattr(
        macos_module, "get_llmster_cmd", lambda: "/usr/local/bin/llmster"
    )
    monkeypatch.setattr(macos_module, "is_llmster_running", lambda: True)
    assert tray.get_daemon_status() == "running"  # nosec B101


def test_macos_get_daemon_status_stopped(macos_module, monkeypatch):
    """Returns 'stopped' when llmster is installed but not running."""
    tray = _make_macos_tray(macos_module)
    monkeypatch.setattr(
        macos_module, "get_llmster_cmd", lambda: "/usr/local/bin/llmster"
    )
    monkeypatch.setattr(macos_module, "is_llmster_running", lambda: False)
    assert tray.get_daemon_status() == "stopped"  # nosec B101


def test_macos_get_daemon_status_error(macos_module, monkeypatch):
    """Returns 'not_found' on subprocess errors."""
    tray = _make_macos_tray(macos_module)
    monkeypatch.setattr(
        macos_module,
        "get_llmster_cmd",
        lambda: "/usr/local/bin/llmster",
    )

    def raise_oserror():
        raise OSError("no such process")

    monkeypatch.setattr(macos_module, "is_llmster_running", raise_oserror)
    assert tray.get_daemon_status() == "not_found"  # nosec B101


def test_macos_get_desktop_app_status_running(macos_module, monkeypatch):
    """Returns 'running' when PIDs are found for LM Studio."""
    tray = _make_macos_tray(macos_module)
    monkeypatch.setattr(
        macos_module, "get_desktop_app_pids", lambda: [1234]
    )
    assert tray.get_desktop_app_status() == "running"  # nosec B101


def test_macos_get_desktop_app_status_stopped(
    macos_module, monkeypatch, tmp_path
):
    """Returns 'stopped' when .app bundle is present but not running."""
    tray = _make_macos_tray(macos_module)
    monkeypatch.setattr(
        macos_module, "get_desktop_app_pids", lambda: []
    )
    app_dir = tmp_path / "LM Studio.app"
    app_dir.mkdir()
    monkeypatch.setattr(
        macos_module.MacOSTrayIcon,
        "_APP_LOCATIONS",
        [str(app_dir)],
    )
    assert tray.get_desktop_app_status() == "stopped"  # nosec B101


def test_macos_get_desktop_app_status_not_found(
    macos_module, monkeypatch
):
    """Returns 'not_found' when .app is absent and no PIDs exist."""
    tray = _make_macos_tray(macos_module)
    monkeypatch.setattr(
        macos_module, "get_desktop_app_pids", lambda: []
    )
    monkeypatch.setattr(
        macos_module.MacOSTrayIcon,
        "_APP_LOCATIONS",
        [],
    )
    assert tray.get_desktop_app_status() == "not_found"  # nosec B101


def test_macos_get_status_indicator(macos_module):
    """Status strings produce the expected emoji indicators."""
    tray = _make_macos_tray(macos_module)
    assert tray.get_status_indicator("running") == "🟢"  # nosec B101
    assert tray.get_status_indicator("stopped") == "🟡"  # nosec B101
    assert tray.get_status_indicator("not_found") == "🔴"  # nosec B101
    assert tray.get_status_indicator("unknown") == "🔴"  # nosec B101


def test_macos_notify_sends_rumps_notification(macos_module):
    """_notify() calls rumps.notification with the right arguments."""
    DummyRumpsModule.reset()
    tray = _make_macos_tray(macos_module)
    _call_member(tray, "_notify", "Hello", "World")
    notifications = DummyRumpsModule.get_notifications()
    assert len(notifications) == 1  # nosec B101
    assert notifications[0][0] == "Hello"  # nosec B101
    assert notifications[0][2] == "World"  # nosec B101


def test_macos_build_menu_daemon_running(macos_module, monkeypatch):
    """build_menu shows stop action when daemon is running."""
    tray = _make_macos_tray(macos_module)
    tray.build_menu = lambda: macos_module.MacOSTrayIcon.build_menu(tray)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "not_found")
    tray.build_menu()
    titles = [
        i.title for i in tray.menu if isinstance(i, DummyRumpsMenuItem)
    ]
    assert any("Daemon (Running)" in t for t in titles)  # nosec B101
    assert any("Stop Daemon" in t for t in titles)  # nosec B101


def test_macos_build_menu_daemon_stopped(macos_module, monkeypatch):
    """build_menu shows start action when daemon is stopped."""
    tray = _make_macos_tray(macos_module)
    tray.build_menu = MethodType(
        macos_module.MacOSTrayIcon.build_menu, tray
    )
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "stopped")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "not_found")
    tray.build_menu()
    titles = [
        i.title for i in tray.menu if isinstance(i, DummyRumpsMenuItem)
    ]
    assert any("Start Daemon" in t for t in titles)  # nosec B101


def test_macos_build_menu_daemon_not_found(macos_module, monkeypatch):
    """build_menu shows 'Not Installed' label when daemon absent."""
    tray = _make_macos_tray(macos_module)
    tray.build_menu = lambda: macos_module.MacOSTrayIcon.build_menu(tray)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "not_found")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "not_found")
    tray.build_menu()
    titles = [
        i.title for i in tray.menu if isinstance(i, DummyRumpsMenuItem)
    ]
    assert any("Not Installed" in t for t in titles)  # nosec B101


def test_macos_build_menu_app_running(macos_module, monkeypatch):
    """build_menu shows stop action when desktop app is running."""
    tray = _make_macos_tray(macos_module)
    tray.build_menu = lambda: macos_module.MacOSTrayIcon.build_menu(tray)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "not_found")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "running")
    tray.build_menu()
    titles = [
        i.title for i in tray.menu if isinstance(i, DummyRumpsMenuItem)
    ]
    assert any("Desktop App (Running)" in t for t in titles)  # nosec B101
    assert any("Stop Desktop App" in t for t in titles)  # nosec B101


def test_macos_build_menu_app_stopped(macos_module, monkeypatch):
    """build_menu shows start action when desktop app is stopped."""
    tray = _make_macos_tray(macos_module)
    tray.build_menu = lambda: macos_module.MacOSTrayIcon.build_menu(tray)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "not_found")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    tray.build_menu()
    titles = [
        i.title for i in tray.menu if isinstance(i, DummyRumpsMenuItem)
    ]
    assert any("Start Desktop App" in t for t in titles)  # nosec B101


def test_macos_check_model_fail(macos_module, monkeypatch):
    """Sets ❌ title and emits notification when both are not_found."""
    tray = _make_macos_tray(macos_module)
    tray.last_status = "WARN"
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "not_found")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "not_found")
    tray.check_model()
    assert tray.title == "❌"  # nosec B101
    notifications = DummyRumpsModule.get_notifications()
    assert any(
        "not installed" in n[2].lower()
        for n in notifications
    )  # nosec B101


def test_macos_check_model_warn(macos_module, monkeypatch):
    """Sets ⚠️ title when both daemon and app are stopped."""
    tray = _make_macos_tray(macos_module)
    tray.last_status = "OK"
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "stopped")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    tray.check_model()
    assert tray.title == "⚠️"  # nosec B101


def test_macos_check_model_ok_via_lms_ps(macos_module, monkeypatch):
    """Sets ✅ title when lms ps reports a loaded model."""
    tray = _make_macos_tray(macos_module)
    tray.last_status = "WARN"
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(macos_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=0, stdout="model loaded"),
    )
    monkeypatch.setattr(macos_module, "_has_loaded_model", lambda _: True)
    tray.check_model()
    assert tray.title == "✅"  # nosec B101


def test_macos_check_model_info_no_model(macos_module, monkeypatch):
    """Sets ℹ️ title when daemon is running but no model is loaded."""
    tray = _make_macos_tray(macos_module)
    tray.last_status = "WARN"
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(macos_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=0, stdout="no models"),
    )
    monkeypatch.setattr(macos_module, "_has_loaded_model", lambda _: False)
    monkeypatch.setattr(macos_module, "check_api_models", lambda: False)
    tray.check_model()
    assert tray.title == "ℹ️"  # nosec B101


def test_macos_check_model_ok_via_api(macos_module, monkeypatch):
    """Sets ✅ via API fallback when lms ps fails."""
    tray = _make_macos_tray(macos_module)
    tray.last_status = "WARN"
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(macos_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=1, stdout="", stderr=""),
    )
    monkeypatch.setattr(macos_module, "check_api_models", lambda: True)
    tray.check_model()
    assert tray.title == "✅"  # nosec B101


def test_macos_check_model_info_no_lms_cmd(macos_module, monkeypatch):
    """Sets ℹ️ when runtime is active but lms cmd not found and API empty."""
    tray = _make_macos_tray(macos_module)
    tray.last_status = None
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(macos_module, "get_lms_cmd", lambda: None)
    monkeypatch.setattr(macos_module, "check_api_models", lambda: False)
    tray.check_model()
    assert tray.title == "ℹ️"  # nosec B101


def test_macos_check_model_ok_api_no_lms(macos_module, monkeypatch):
    """Sets ✅ via API when lms cmd is absent but API shows model loaded."""
    tray = _make_macos_tray(macos_module)
    tray.last_status = None
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(macos_module, "get_lms_cmd", lambda: None)
    monkeypatch.setattr(macos_module, "check_api_models", lambda: True)
    tray.check_model()
    assert tray.title == "✅"  # nosec B101


def test_macos_check_model_error_sets_fail_icon(
    macos_module, monkeypatch
):
    """Sets ❌ when an OSError occurs during status check."""
    tray = _make_macos_tray(macos_module)
    tray.last_status = None

    def raise_oserror():
        raise OSError("test error")

    monkeypatch.setattr(tray, "get_daemon_status", raise_oserror)
    tray.check_model()
    assert tray.title == "❌"  # nosec B101


def test_macos_check_model_timeout_keeps_status(
    macos_module, monkeypatch
):
    """TimeoutExpired in check_model is caught without changing title."""
    tray = _make_macos_tray(macos_module)
    tray.title = "✅"

    def raise_timeout():
        raise subprocess.TimeoutExpired(cmd="lms", timeout=5)

    monkeypatch.setattr(tray, "get_daemon_status", raise_timeout)
    tray.check_model()
    assert tray.title == "✅"  # nosec B101


def test_macos_check_model_status_change_ok_notification(
    macos_module, monkeypatch
):
    """Status change to OK sends a notification."""
    tray = _make_macos_tray(macos_module)
    tray.last_status = "WARN"
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(macos_module, "get_lms_cmd", lambda: "/usr/bin/lms")

    def _run_safe_command_stub(command):
        _ = command
        return _completed(returncode=0, stdout="model loaded")

    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        _run_safe_command_stub,
    )
    monkeypatch.setattr(macos_module, "_has_loaded_model", lambda _: True)
    tray.check_model()
    notifications = DummyRumpsModule.get_notifications()
    assert any(
        "model is loaded" in n[2].lower()
        for n in notifications
    )  # nosec B101


def test_macos_check_model_status_change_info_notification(
    macos_module, monkeypatch
):
    """Status change to INFO sends the appropriate notification."""
    tray = _make_macos_tray(macos_module)
    tray.last_status = "OK"
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(macos_module, "get_lms_cmd", lambda: None)
    monkeypatch.setattr(macos_module, "check_api_models", lambda: False)
    tray.check_model()
    notifications = DummyRumpsModule.get_notifications()
    assert any(
        "no model" in n[2].lower()
        for n in notifications
    )  # nosec B101


def test_macos_check_model_status_change_warn_notification(
    macos_module, monkeypatch
):
    """Status change to WARN sends the appropriate notification."""
    tray = _make_macos_tray(macos_module)
    tray.last_status = "OK"
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "stopped")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    tray.check_model()
    assert any(
        "neither" in n[2].lower()
        for n in DummyRumpsModule.get_notifications()
    )  # nosec B101


def test_macos_build_daemon_attempts_start(macos_module, monkeypatch):
    """_build_daemon_attempts returns start commands when lms is found."""
    tray = _make_macos_tray(macos_module)
    monkeypatch.setattr(
        macos_module, "get_lms_cmd", lambda: "/usr/local/bin/lms"
    )
    monkeypatch.setattr(macos_module, "get_llmster_cmd", lambda: None)
    attempts = _call_member(tray, "_build_daemon_attempts", "start")
    assert len(attempts) > 0  # nosec B101
    assert all(a[0] == "/usr/local/bin/lms" for a in attempts)  # nosec B101


def test_macos_build_daemon_attempts_stop(macos_module, monkeypatch):
    """_build_daemon_attempts returns stop commands when lms is found."""
    tray = _make_macos_tray(macos_module)
    monkeypatch.setattr(
        macos_module, "get_lms_cmd", lambda: "/usr/local/bin/lms"
    )
    monkeypatch.setattr(macos_module, "get_llmster_cmd", lambda: None)
    attempts = _call_member(tray, "_build_daemon_attempts", "stop")
    assert len(attempts) > 0  # nosec B101
    assert all("down" in a or "stop" in a for a in attempts)  # nosec B101


def test_macos_stop_daemon_with_notification_no_cmd(
    macos_module, monkeypatch
):
    """_stop_daemon_with_notification notifies when no stop command found."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(macos_module, "get_lms_cmd", lambda: None)
    monkeypatch.setattr(macos_module, "get_llmster_cmd", lambda: None)
    stopped, _ = _call_member(tray, "_stop_daemon_with_notification")
    assert not stopped  # nosec B101
    assert any(
        "not found" in n[2].lower()
        for n in DummyRumpsModule.get_notifications()
    )  # nosec B101


def test_macos_stop_daemon_with_notification_success(
    macos_module, monkeypatch
):
    """_stop_daemon_with_notification notifies on successful stop."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(
        macos_module, "get_lms_cmd", lambda: "/usr/local/bin/lms"
    )
    monkeypatch.setattr(macos_module, "get_llmster_cmd", lambda: None)
    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        lambda cmd: _completed(returncode=0),
    )
    monkeypatch.setattr(macos_module, "is_llmster_running", lambda: False)
    monkeypatch.setattr(
        tray,
        "_force_stop_llmster",
        lambda: None,
    )
    stopped, _ = _call_member(tray, "_stop_daemon_with_notification")
    assert stopped  # nosec B101
    notifications = DummyRumpsModule.get_notifications()
    assert any(
        "stopped" in n[2].lower()
        for n in notifications
    )  # nosec B101


def test_macos_stop_daemon_with_notification_fail(
    macos_module, monkeypatch
):
    """_stop_daemon_with_notification notifies on failed stop."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(
        macos_module, "get_lms_cmd", lambda: "/usr/local/bin/lms"
    )
    monkeypatch.setattr(macos_module, "get_llmster_cmd", lambda: None)
    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        lambda *_args, **_kwargs: _completed(returncode=1, stderr="nope"),
    )
    monkeypatch.setattr(macos_module, "is_llmster_running", lambda: True)
    monkeypatch.setattr(tray, "_force_stop_llmster", lambda: None)
    stopped, _ = _call_member(tray, "_stop_daemon_with_notification")
    assert not stopped  # nosec B101
    assert any(
        "failed" in n[2].lower()
        for n in DummyRumpsModule.get_notifications()
    )  # nosec B101


def test_macos_start_daemon_body_no_cmd(macos_module, monkeypatch):
    """_start_daemon_body notifies when no start command is available."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(macos_module, "get_lms_cmd", lambda: None)
    monkeypatch.setattr(macos_module, "get_llmster_cmd", lambda: None)
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    _call_member(tray, "_start_daemon_body")
    notifications = DummyRumpsModule.get_notifications()
    assert any(
        "not found" in n[2].lower()
        for n in notifications
    )  # nosec B101


def test_macos_start_daemon_body_success(macos_module, monkeypatch):
    """_start_daemon_body notifies when daemon starts."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(
        macos_module, "get_lms_cmd", lambda: "/usr/local/bin/lms"
    )
    monkeypatch.setattr(macos_module, "get_llmster_cmd", lambda: None)
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        lambda cmd: _completed(returncode=0),
    )
    monkeypatch.setattr(macos_module, "is_llmster_running", lambda: True)
    monkeypatch.setattr(tray, "_schedule_menu_refresh", lambda *_: None)
    _call_member(tray, "_start_daemon_body")
    notifications = DummyRumpsModule.get_notifications()
    assert any(
        "running" in n[2].lower()
        for n in notifications
    )  # nosec B101


def test_macos_start_daemon_body_fail(macos_module, monkeypatch):
    """_start_daemon_body notifies on failure to start daemon."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(
        macos_module, "get_lms_cmd", lambda: "/usr/local/bin/lms"
    )
    monkeypatch.setattr(macos_module, "get_llmster_cmd", lambda: None)
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")

    def _run_safe_command_stub(command):
        _ = command
        return _completed(returncode=0)

    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        _run_safe_command_stub,
    )
    monkeypatch.setattr(macos_module, "is_llmster_running", lambda: False)
    _call_member(tray, "_start_daemon_body")
    notifications = DummyRumpsModule.get_notifications()
    assert any(
        "failed" in n[2].lower()
        for n in notifications
    )  # nosec B101


def test_macos_start_daemon_cooldown(macos_module, monkeypatch):
    """start_daemon respects the action cooldown."""
    tray = _make_macos_tray(macos_module)
    tray.action_lock_until = float("inf")
    called = []
    monkeypatch.setattr(
        tray, "_start_daemon_body", lambda: called.append(1)
    )
    tray.start_daemon(None)
    assert not called  # nosec B101


def test_macos_stop_daemon_body_success(macos_module, monkeypatch):
    """_stop_daemon_body calls stop and refreshes menu on success."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    refreshed = []
    monkeypatch.setattr(
        tray,
        "_stop_daemon_with_notification",
        lambda: (True, None),
    )
    monkeypatch.setattr(tray, "build_menu", lambda: refreshed.append(1))
    monkeypatch.setattr(tray, "_schedule_menu_refresh", lambda *_: None)
    _call_member(tray, "_stop_daemon_body")
    assert refreshed  # nosec B101


def test_macos_start_desktop_app_body_no_open(
    macos_module, monkeypatch
):
    """_start_desktop_app_body notifies when 'open' is unavailable."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(macos_module, "is_llmster_running", lambda: False)
    monkeypatch.setattr(macos_module.shutil, "which", lambda _: None)
    _call_member(tray, "_start_desktop_app_body")
    notifications = DummyRumpsModule.get_notifications()
    assert any(
        "open" in n[2].lower()
        for n in notifications
    )  # nosec B101


def test_macos_start_desktop_app_body_not_found(
    macos_module, monkeypatch
):
    """_start_desktop_app_body notifies when .app bundle is missing."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(macos_module, "is_llmster_running", lambda: False)
    monkeypatch.setattr(
        macos_module.shutil, "which", lambda _: "/usr/bin/open"
    )
    monkeypatch.setattr(
        macos_module.MacOSTrayIcon, "_APP_LOCATIONS", []
    )
    _call_member(tray, "_start_desktop_app_body")
    notifications = DummyRumpsModule.get_notifications()
    assert any(
        "no lm studio" in n[2].lower()
        for n in notifications
    )  # nosec B101


def test_macos_start_desktop_app_body_success(
    macos_module, monkeypatch, tmp_path
):
    """_start_desktop_app_body launches the app and notifies success."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    app_dir = tmp_path / "LM Studio.app"
    app_dir.mkdir()
    monkeypatch.setattr(macos_module, "is_llmster_running", lambda: False)
    monkeypatch.setattr(
        macos_module.shutil, "which", lambda _: "/usr/bin/open"
    )
    monkeypatch.setattr(
        macos_module.MacOSTrayIcon, "_APP_LOCATIONS", [str(app_dir)]
    )
    monkeypatch.setattr(tray, "_schedule_menu_refresh", lambda *_: None)

    launched = []

    def fake_popen(cmd, **kwargs):
        _ = kwargs
        launched.append(cmd)
        return SimpleNamespace()

    monkeypatch.setattr(macos_module.subprocess, "Popen", fake_popen)
    _call_member(tray, "_start_desktop_app_body")
    assert launched  # nosec B101
    notifications = DummyRumpsModule.get_notifications()
    assert any(
        "starting" in n[2].lower()
        for n in notifications
    )  # nosec B101


def test_macos_stop_desktop_app_no_pids(macos_module, monkeypatch):
    """stop_desktop_app does nothing when no desktop PIDs found."""
    tray = _make_macos_tray(macos_module)
    tray.action_lock_until = 0.0
    monkeypatch.setattr(
        macos_module, "get_desktop_app_pids", lambda: []
    )
    kills = []
    monkeypatch.setattr(os, "kill", lambda pid, _sig: kills.append(pid))
    tray.stop_desktop_app(None)
    assert not kills  # nosec B101


def test_macos_stop_desktop_app_sends_sigterm(
    macos_module, monkeypatch
):
    """stop_desktop_app sends SIGTERM to desktop app PIDs."""
    tray = _make_macos_tray(macos_module)
    tray.action_lock_until = 0.0
    monkeypatch.setattr(
        macos_module, "get_desktop_app_pids", lambda: [4321]
    )
    kills = []
    monkeypatch.setattr(
        os, "kill", lambda pid, sig: kills.append((pid, sig))
    )
    monkeypatch.setattr(tray, "_schedule_menu_refresh", lambda *_: None)
    tray.stop_desktop_app(None)
    assert (4321, signal.SIGTERM) in kills  # nosec B101


def test_macos_show_status_dialog_lms_ps_success(
    macos_module, monkeypatch
):
    """show_status_dialog shows lms ps output in a rumps alert."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(
        macos_module, "get_lms_cmd", lambda: "/usr/local/bin/lms"
    )
    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        lambda _: _completed(returncode=0, stdout="model: qwen"),
    )
    tray.show_status_dialog(None)
    alerts = DummyRumpsModule.get_alerts()
    assert alerts  # nosec B101
    assert "qwen" in alerts[0][1]  # nosec B101


def test_macos_show_status_dialog_no_lms_cmd(
    macos_module, monkeypatch
):
    """show_status_dialog shows fallback message when lms is absent."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(macos_module, "get_lms_cmd", lambda: None)
    tray.show_status_dialog(None)
    alerts = DummyRumpsModule.get_alerts()
    assert alerts  # nosec B101
    assert "No models" in alerts[0][1]  # nosec B101


def test_macos_show_about_dialog(macos_module):
    """show_about_dialog shows version and repository info."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    app_state = _call_member(
        macos_module,
        "__getattribute__",
        "_AppState",
    )
    app_state.APP_VERSION = "1.2.3"
    tray.show_about_dialog(None)
    alerts = DummyRumpsModule.get_alerts()
    assert alerts  # nosec B101
    assert "1.2.3" in alerts[0][1]  # nosec B101


def test_macos_check_updates_dev_build(macos_module):
    """check_updates returns False for dev build."""
    tray = _make_macos_tray(macos_module)
    app_state = _call_member(
        macos_module,
        "__getattribute__",
        "_AppState",
    )
    app_state.APP_VERSION = "dev"
    result = tray.check_updates()
    assert not result  # nosec B101
    assert tray.update_status == "Dev build"  # nosec B101


def test_macos_check_updates_no_latest(macos_module, monkeypatch):
    """check_updates returns False when release fetch fails."""
    tray = _make_macos_tray(macos_module)
    app_state = _call_member(
        macos_module,
        "__getattribute__",
        "_AppState",
    )
    app_state.APP_VERSION = "v1.0.0"
    monkeypatch.setattr(
        macos_module,
        "get_latest_release_version",
        lambda: (None, "timeout"),
    )
    result = tray.check_updates()
    assert not result  # nosec B101
    assert tray.update_status == "Unknown"  # nosec B101


def test_macos_check_updates_up_to_date(macos_module, monkeypatch):
    """check_updates sets status to 'Up to date' when current."""
    tray = _make_macos_tray(macos_module)
    app_state = _call_member(
        macos_module,
        "__getattribute__",
        "_AppState",
    )
    app_state.APP_VERSION = "v1.0.0"
    monkeypatch.setattr(
        macos_module,
        "get_latest_release_version",
        lambda: ("v1.0.0", None),
    )
    result = tray.check_updates()
    assert not result  # nosec B101
    assert tray.update_status == "Up to date"  # nosec B101


def test_macos_check_updates_new_version(macos_module, monkeypatch):
    """check_updates notifies when a newer version is available."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    app_state = _call_member(
        macos_module,
        "__getattribute__",
        "_AppState",
    )
    app_state.APP_VERSION = "v1.0.0"
    monkeypatch.setattr(
        macos_module,
        "get_latest_release_version",
        lambda: ("v1.1.0", None),
    )
    result = tray.check_updates()
    assert result  # nosec B101
    assert tray.update_status == "Update available"  # nosec B101
    assert DummyRumpsModule.get_notifications()  # nosec B101


def test_macos_manual_check_updates_up_to_date(
    macos_module, monkeypatch
):
    """manual_check_updates shows an alert when already up to date."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "check_updates", lambda: False)
    tray.update_status = "Up to date"
    app_state = _call_member(
        macos_module,
        "__getattribute__",
        "_AppState",
    )
    app_state.APP_VERSION = "v1.0.0"
    tray.manual_check_updates(None)
    alerts = DummyRumpsModule.get_alerts()
    assert alerts  # nosec B101
    assert "up to date" in alerts[0][1].lower()  # nosec B101


def test_macos_manual_check_updates_error(macos_module, monkeypatch):
    """manual_check_updates shows an alert with error detail."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "check_updates", lambda: False)
    tray.update_status = "Unknown"
    tray.last_update_error = "connection refused"
    tray.latest_update_version = None
    tray.manual_check_updates(None)
    alerts = DummyRumpsModule.get_alerts()
    assert alerts  # nosec B101
    assert "connection refused" in alerts[0][1]  # nosec B101


def test_macos_manual_check_updates_dev_build(
    macos_module, monkeypatch
):
    """manual_check_updates shows 'Dev build' message."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "check_updates", lambda: False)
    tray.update_status = "Dev build"
    tray.manual_check_updates(None)
    alerts = DummyRumpsModule.get_alerts()
    assert alerts  # nosec B101
    assert "dev build" in alerts[0][1].lower()  # nosec B101


def test_macos_manual_check_updates_ahead_of_release(
    macos_module, monkeypatch
):
    """manual_check_updates shows 'Ahead of release' message."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "check_updates", lambda: False)
    tray.update_status = "Ahead of release"
    tray.latest_update_version = "v0.9.0"
    app_state = _call_member(
        macos_module,
        "__getattribute__",
        "_AppState",
    )
    app_state.APP_VERSION = "v1.0.0"
    tray.manual_check_updates(None)
    assert DummyRumpsModule.get_alerts()  # nosec B101


def test_macos_quit_app(macos_module):
    """quit_app calls rumps.quit_application."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    tray.quit_app(None)
    assert DummyRumpsModule.is_quit_called()  # nosec B101


def test_macos_begin_action_cooldown_allows(macos_module):
    """begin_action_cooldown allows action when not in cooldown."""
    tray = _make_macos_tray(macos_module)
    tray.action_lock_until = 0.0
    assert tray.begin_action_cooldown("test")  # nosec B101


def test_macos_begin_action_cooldown_blocks(macos_module):
    """begin_action_cooldown blocks action when in cooldown."""
    tray = _make_macos_tray(macos_module)
    tray.action_lock_until = float("inf")
    assert not tray.begin_action_cooldown("test")  # nosec B101


def test_macos_force_stop_llmster_no_pkill(macos_module, monkeypatch):
    """_force_stop_llmster logs warning when pkill is absent."""
    tray = _make_macos_tray(macos_module)
    monkeypatch.setattr(macos_module, "get_pkill_cmd", lambda: None)
    # Should not raise
    _call_member(tray, "_force_stop_llmster")


def test_macos_force_stop_llmster_stops_process(
    macos_module, monkeypatch
):
    """_force_stop_llmster calls pkill to stop llmster."""
    tray = _make_macos_tray(macos_module)
    monkeypatch.setattr(
        macos_module, "get_pkill_cmd", lambda: "/usr/bin/pkill"
    )
    calls = []
    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        lambda cmd: calls.append(cmd) or _completed(returncode=0),
    )
    monkeypatch.setattr(
        macos_module, "is_llmster_running", lambda: False
    )
    _call_member(tray, "_force_stop_llmster")
    assert calls  # nosec B101


def test_run_macos_missing_rumps(macos_module, monkeypatch):
    """_run_macos exits with error when rumps is not installed."""
    monkeypatch.setattr(macos_module, "_rumps_lib", None)
    with pytest.raises(SystemExit) as exc_info:
        _call_member(macos_module, "_run_macos", SimpleNamespace())
    assert exc_info.value.code == 1  # nosec B101


def test_macos_stop_desktop_app_processes(macos_module, monkeypatch):
    """_stop_desktop_app_processes sends SIGTERM to desktop PIDs."""
    tray = _make_macos_tray(macos_module)
    monkeypatch.setattr(
        macos_module, "get_desktop_app_pids", lambda: [1111]
    )
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    kills = []
    monkeypatch.setattr(
        os, "kill", lambda pid, sig: kills.append((pid, sig))
    )
    result = _call_member(tray, "_stop_desktop_app_processes")
    assert result  # nosec B101
    assert any(p == 1111 for p, _ in kills)  # nosec B101


def test_macos_timer_callbacks(macos_module, monkeypatch):
    """Timer callbacks delegate to their respective methods."""
    tray = _make_macos_tray(macos_module)
    tray.build_menu = lambda: None
    called = []
    monkeypatch.setattr(
        tray, "check_model", lambda: called.append("model") or True
    )
    monkeypatch.setattr(
        tray, "check_updates", lambda: called.append("updates") or False
    )
    sender = DummyRumpsTimer(None, 5)
    _call_member(tray, "_check_model_tick", sender)
    _call_member(tray, "_update_check_tick", sender)
    _call_member(tray, "_initial_update_check_once", sender)
    assert "model" in called  # nosec B101
    assert "updates" in called  # nosec B101
    assert not sender.running  # noqa: SLF001 (stopped after initial)


def test_macos_schedule_menu_refresh(macos_module, monkeypatch):
    """_schedule_menu_refresh schedules a delayed rebuild via threading."""
    tray = _make_macos_tray(macos_module)
    scheduled = []

    class ImmediateTimer:  # pylint: disable=too-few-public-methods
        """Immediate timer stub that runs callbacks synchronously in tests."""

        def __init__(self, _delay, fn):
            """Run the provided callback immediately and record scheduling."""
            self.daemon = True
            fn()
            scheduled.append(fn)

        def start(self):
            """Provide a Timer-compatible start method for monkeypatching."""
            return None

    monkeypatch.setattr(macos_module.threading, "Timer", ImmediateTimer)
    monkeypatch.setattr(tray, "build_menu", lambda: None)
    _call_member(tray, "_schedule_menu_refresh", 0)
    assert scheduled  # nosec B101


def test_macos_maybe_auto_start_daemon(macos_module, monkeypatch):
    """_maybe_auto_start_daemon stops then starts the daemon."""
    tray = _make_macos_tray(macos_module)
    calls = []
    monkeypatch.setattr(
        tray,
        "_stop_daemon_with_notification",
        lambda: calls.append("stop") or (True, None),
    )
    monkeypatch.setattr(
        tray, "start_daemon", lambda sender: calls.append("start")
    )
    _call_member(tray, "_maybe_auto_start_daemon")
    assert "stop" in calls  # nosec B101
    assert "start" in calls  # nosec B101


def test_macos_maybe_start_gui(macos_module, monkeypatch):
    """_maybe_start_gui calls start_desktop_app."""
    tray = _make_macos_tray(macos_module)
    called = []
    monkeypatch.setattr(
        tray, "start_desktop_app", lambda s: called.append(1)
    )
    _call_member(tray, "_maybe_start_gui")
    assert called  # nosec B101


def test_macos_check_updates_ahead_of_release(macos_module, monkeypatch):
    """check_updates sets 'Ahead of release' when current is newer."""
    tray = _make_macos_tray(macos_module)
    app_state = _call_member(macos_module, "__getattribute__", "_AppState")
    app_state.APP_VERSION = "v2.0.0"
    monkeypatch.setattr(
        macos_module,
        "get_latest_release_version",
        lambda: ("v1.0.0", None),
    )
    tray.check_updates()
    assert tray.update_status == "Ahead of release"  # nosec B101


def test_macos_start_desktop_app_cooldown(macos_module, monkeypatch):
    """start_desktop_app respects the action cooldown."""
    tray = _make_macos_tray(macos_module)
    tray.action_lock_until = float("inf")
    called = []
    monkeypatch.setattr(
        tray, "_start_desktop_app_body", lambda: called.append(1)
    )
    tray.start_desktop_app(None)
    assert not called  # nosec B101


def test_macos_stop_daemon_cooldown(macos_module, monkeypatch):
    """stop_daemon respects the action cooldown."""
    tray = _make_macos_tray(macos_module)
    tray.action_lock_until = float("inf")
    called = []
    monkeypatch.setattr(
        tray, "_stop_daemon_body", lambda: called.append(1)
    )
    tray.stop_daemon(None)
    assert not called  # nosec B101


def test_macos_check_updates_notified_once(macos_module, monkeypatch):
    """check_updates notifies only once per unique latest version."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    app_state = _call_member(macos_module, "__getattribute__", "_AppState")
    app_state.APP_VERSION = "v1.0.0"
    monkeypatch.setattr(
        macos_module,
        "get_latest_release_version",
        lambda: ("v1.1.0", None),
    )
    tray.check_updates()
    tray.check_updates()
    notifications = DummyRumpsModule.get_notifications()
    assert len(notifications) == 1  # nosec B101


def test_macos_start_daemon_body_stops_app_first(
    macos_module, monkeypatch
):
    """_start_daemon_body stops desktop app before starting daemon."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    calls = []
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "running")
    monkeypatch.setattr(
        tray,
        "_stop_desktop_app_processes",
        lambda: calls.append("stopped") or True,
    )
    monkeypatch.setattr(
        macos_module, "get_lms_cmd", lambda: "/usr/local/bin/lms"
    )
    monkeypatch.setattr(macos_module, "get_llmster_cmd", lambda: None)
    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        lambda cmd: _completed(returncode=0),
    )
    monkeypatch.setattr(macos_module, "is_llmster_running", lambda: True)
    monkeypatch.setattr(tray, "_schedule_menu_refresh", lambda *_: None)
    _call_member(tray, "_start_daemon_body")
    assert "stopped" in calls  # nosec B101


def test_macos_start_daemon_body_app_stop_fails(
    macos_module, monkeypatch
):
    """_start_daemon_body notifies when desktop app cannot be stopped."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "running")
    monkeypatch.setattr(
        tray, "_stop_desktop_app_processes", lambda: False
    )
    _call_member(tray, "_start_daemon_body")
    notifications = DummyRumpsModule.get_notifications()
    assert any(
        "failed" in n[2].lower()
        for n in notifications
    )  # nosec B101


def test_macos_show_status_dialog_lms_ps_empty(
    macos_module, monkeypatch
):
    """show_status_dialog shows fallback when lms ps output is empty."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(
        macos_module, "get_lms_cmd", lambda: "/usr/local/bin/lms"
    )
    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        lambda unused_arg: _completed(returncode=0, stdout=""),
    )
    tray.show_status_dialog(None)
    alerts = DummyRumpsModule.get_alerts()
    assert alerts  # nosec B101
    assert "No model" in alerts[0][1]  # nosec B101


def test_macos_show_status_dialog_lms_ps_error(
    macos_module, monkeypatch
):
    """show_status_dialog shows error text when lms ps raises OSError."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(
        macos_module, "get_lms_cmd", lambda: "/usr/local/bin/lms"
    )

    def raise_os(cmd):
        raise OSError("oops")

    monkeypatch.setattr(macos_module, "_run_safe_command", raise_os)
    tray.show_status_dialog(None)
    alerts = DummyRumpsModule.get_alerts()
    assert alerts  # nosec B101
    assert "oops" in alerts[0][1]  # nosec B101


def test_macos_build_menu_includes_quit(macos_module, monkeypatch):
    """build_menu always includes a Quit Tray item."""
    tray = _make_macos_tray(macos_module)
    tray.build_menu = lambda: macos_module.MacOSTrayIcon.build_menu(tray)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "not_found")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "not_found")
    tray.build_menu()
    titles = [
        i.title for i in tray.menu if isinstance(i, DummyRumpsMenuItem)
    ]
    assert any("Quit" in t for t in titles)  # nosec B101


def test_macos_build_menu_includes_show_status(
    macos_module, monkeypatch
):
    """build_menu always includes Show Status item."""
    tray = _make_macos_tray(macos_module)
    build_method = macos_module.MacOSTrayIcon.build_menu
    tray.build_menu = lambda: build_method(tray)
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "not_found")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "not_found")
    tray.build_menu()
    titles = [
        i.title for i in tray.menu if isinstance(i, DummyRumpsMenuItem)
    ]
    assert any("Show Status" in t for t in titles)  # nosec B101


def test_macos_force_stop_llmster_sigkill_path(
    macos_module, monkeypatch
):
    """_force_stop_llmster escalates to SIGKILL when process persists."""
    tray = _make_macos_tray(macos_module)
    still_running = [True]
    calls = []

    def fake_run_safe(cmd):
        calls.append(cmd)
        return _completed(returncode=0)

    call_count = [0]

    def still_running_check():
        call_count[0] += 1
        if call_count[0] <= 13:
            return still_running[0]
        return False

    monkeypatch.setattr(
        macos_module, "get_pkill_cmd", lambda: "/usr/bin/pkill"
    )
    monkeypatch.setattr(macos_module, "_run_safe_command", fake_run_safe)
    monkeypatch.setattr(
        macos_module, "is_llmster_running", still_running_check
    )
    monkeypatch.setattr(macos_module.time, "sleep", lambda _: None)
    _call_member(tray, "_force_stop_llmster")
    kill_cmds = [c for c in calls if "-9" in c]
    assert kill_cmds  # nosec B101


def test_macos_stop_desktop_app_processes_sigkill(
    macos_module, monkeypatch
):
    """_stop_desktop_app_processes escalates to SIGKILL when app persists."""
    tray = _make_macos_tray(macos_module)
    call_count = [0]

    def still_running():
        call_count[0] += 1
        return "running" if call_count[0] <= 10 else "stopped"

    monkeypatch.setattr(
        macos_module, "get_desktop_app_pids", lambda: [5555]
    )
    monkeypatch.setattr(
        tray, "get_desktop_app_status", still_running
    )
    kills = []
    monkeypatch.setattr(
        os, "kill", lambda pid, sig: kills.append((pid, sig))
    )
    monkeypatch.setattr(macos_module.time, "sleep", lambda _: None)
    _call_member(tray, "_stop_desktop_app_processes")
    sigs = [sig for _, sig in kills]
    assert signal.SIGTERM in sigs  # nosec B101


def test_macos_stop_daemon_body_error(macos_module, monkeypatch):
    """_stop_daemon_body notifies on OSError."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()

    def raise_oserror():
        raise OSError("test error")

    monkeypatch.setattr(
        tray, "_stop_daemon_with_notification", raise_oserror
    )
    _call_member(tray, "_stop_daemon_body")
    notifications = DummyRumpsModule.get_notifications()
    assert any("test error" in n[2] for n in notifications)  # nosec B101


def test_macos_manual_check_updates_update_available(
    macos_module, monkeypatch
):
    """manual_check_updates shows update URL when version is available."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "check_updates", lambda: False)
    tray.update_status = "Update available"
    tray.latest_update_version = "v2.0.0"
    app_state = _call_member(macos_module, "__getattribute__", "_AppState")
    app_state.APP_VERSION = "v1.0.0"
    tray.manual_check_updates(None)
    alerts = DummyRumpsModule.get_alerts()
    assert alerts  # nosec B101
    assert "v2.0.0" in alerts[0][1]  # nosec B101


def test_macos_maybe_auto_start_daemon_error(
    macos_module, monkeypatch
):
    """_maybe_auto_start_daemon handles stop errors gracefully."""
    tray = _make_macos_tray(macos_module)
    calls = []

    def raise_oserror():
        raise OSError("stop error")

    monkeypatch.setattr(
        tray, "_stop_daemon_with_notification", raise_oserror
    )
    monkeypatch.setattr(
        tray, "start_daemon", lambda _unused: calls.append("start")
    )
    _call_member(tray, "_maybe_auto_start_daemon")
    assert "start" in calls  # nosec B101


def test_macos_start_desktop_app_body_stops_daemon(
    macos_module, monkeypatch
):
    """_start_desktop_app_body stops daemon when it is running."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    stopped = []
    monkeypatch.setattr(macos_module, "is_llmster_running", lambda: True)
    monkeypatch.setattr(
        tray,
        "_stop_daemon_with_notification",
        lambda: stopped.append(1) or (True, None),
    )
    monkeypatch.setattr(
        macos_module.shutil, "which", lambda _: None
    )
    _call_member(tray, "_start_desktop_app_body")
    assert stopped  # nosec B101


def test_macos_start_desktop_app_body_popen_error(
    macos_module, monkeypatch, tmp_path
):
    """_start_desktop_app_body notifies when Popen raises OSError."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    app_dir = tmp_path / "LM Studio.app"
    app_dir.mkdir()
    monkeypatch.setattr(macos_module, "is_llmster_running", lambda: False)
    monkeypatch.setattr(
        macos_module.shutil, "which", lambda _: "/usr/bin/open"
    )
    monkeypatch.setattr(
        macos_module.MacOSTrayIcon, "_APP_LOCATIONS", [str(app_dir)]
    )

    def raise_oserror(*_unused_a, **_unused_kw):
        raise OSError("permission denied")

    monkeypatch.setattr(macos_module.subprocess, "Popen", raise_oserror)
    _call_member(tray, "_start_desktop_app_body")
    notifications = DummyRumpsModule.get_notifications()
    assert any(
        "permission denied" in n[2] for n in notifications
    )  # nosec B101


def test_macos_get_desktop_app_status_caches_detection(
    macos_module, monkeypatch, tmp_path
):
    """get_desktop_app_status caches the detection result."""
    tray = _make_macos_tray(macos_module)
    monkeypatch.setattr(
        macos_module, "get_desktop_app_pids", lambda: []
    )
    app_dir = tmp_path / "LM Studio.app"
    app_dir.mkdir()
    monkeypatch.setattr(
        macos_module.MacOSTrayIcon, "_APP_LOCATIONS", [str(app_dir)]
    )
    status1 = tray.get_desktop_app_status()
    status2 = tray.get_desktop_app_status()
    assert status1 == "stopped"  # nosec B101
    assert status2 == "stopped"  # nosec B101
    seen_call = _call_member(tray, "__getattribute__", "_seen_desktop_call")
    assert seen_call  # nosec B101


def test_macos_check_model_no_last_status_no_notify(
    macos_module, monkeypatch
):
    """check_model does not notify on first status observation."""
    tray = _make_macos_tray(macos_module)
    tray.last_status = None
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "not_found")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "not_found")
    tray.check_model()
    notifications = DummyRumpsModule.get_notifications()
    assert not notifications  # nosec B101


def test_macos_stop_daemon_with_notification_detail_from_stderr(
    macos_module, monkeypatch
):
    """_stop_daemon_with_notification includes stderr detail on failure."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(
        macos_module, "get_lms_cmd", lambda: "/usr/local/bin/lms"
    )
    monkeypatch.setattr(macos_module, "get_llmster_cmd", lambda: None)
    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        lambda _unused_cmd: _completed(returncode=1, stderr="port in use"),
    )
    monkeypatch.setattr(macos_module, "is_llmster_running", lambda: True)
    monkeypatch.setattr(tray, "_force_stop_llmster", lambda: None)
    stopped, _ = _call_member(tray, "_stop_daemon_with_notification")
    assert not stopped  # nosec B101
    notifications = DummyRumpsModule.get_notifications()
    assert any("port in use" in n[2] for n in notifications)  # nosec B101


def test_macos_stop_desktop_app_cooldown(macos_module, monkeypatch):
    """stop_desktop_app respects cooldown."""
    tray = _make_macos_tray(macos_module)
    tray.action_lock_until = float("inf")
    kills = []
    monkeypatch.setattr(
        os, "kill", lambda pid, sig: kills.append((pid, sig))
    )
    tray.stop_desktop_app(None)
    assert not kills  # nosec B101


def test_macos_tray_icon_init(macos_module, monkeypatch):
    """MacOSTrayIcon.__init__ creates timers and initialises state."""
    timers_started = []

    class FakeTimer:
        """Stub timer class for testing."""

        def __init__(self, cb, interval):
            """Initialize timer with callback and interval."""
            self.cb = cb
            self.interval = interval
            self.running = False

        def start(self):
            """Mark timer as started."""
            self.running = True
            timers_started.append(self)

    rumps_lib = _call_member(macos_module, "__getattribute__", "_rumps_lib")
    monkeypatch.setattr(rumps_lib, "Timer", FakeTimer)
    monkeypatch.setattr(
        macos_module,
        "get_llmster_cmd",
        lambda: None,
    )
    monkeypatch.setattr(
        macos_module,
        "get_desktop_app_pids",
        lambda: [],
    )
    monkeypatch.setattr(
        macos_module.MacOSTrayIcon,
        "_APP_LOCATIONS",
        [],
    )
    tray = macos_module.MacOSTrayIcon()
    assert tray is not None  # nosec B101
    assert len(timers_started) == 3  # nosec B101
    assert all(t.running for t in timers_started)  # nosec B101


def test_macos_tray_icon_init_auto_start(macos_module, monkeypatch):
    """MacOSTrayIcon.__init__ launches auto-start thread when flag is set."""

    class FakeTimer:
        """Stub timer class for testing."""

        def __init__(self, *_unused_args):
            """Initialize timer (unused args)."""

        def start(self):
            """No-op timer start."""

    rumps_lib = _call_member(macos_module, "__getattribute__", "_rumps_lib")
    monkeypatch.setattr(rumps_lib, "Timer", FakeTimer)
    monkeypatch.setattr(macos_module, "get_llmster_cmd", lambda: None)
    monkeypatch.setattr(macos_module, "get_desktop_app_pids", lambda: [])
    monkeypatch.setattr(
        macos_module.MacOSTrayIcon, "_APP_LOCATIONS", []
    )
    app_state = _call_member(macos_module, "__getattribute__", "_AppState")
    app_state.AUTO_START_DAEMON = True
    threads_started = []
    original_thread = macos_module.threading.Thread

    class FakeThread:
        """Stub thread class for testing."""

        def __init__(self, target=None, daemon=True, name=""):
            """Initialize thread with target and name."""
            self.target = target
            self.daemon = daemon
            self.name = name

        def start(self):
            """Record thread start."""
            threads_started.append(self.name)

    monkeypatch.setattr(macos_module.threading, "Thread", FakeThread)
    try:
        tray = macos_module.MacOSTrayIcon()
        assert tray is not None  # nosec B101
        assert any("auto-start" in n for n in threads_started)  # nosec B101
    finally:
        app_state.AUTO_START_DAEMON = False
        monkeypatch.setattr(macos_module.threading, "Thread", original_thread)


def test_macos_tray_icon_init_gui_mode(macos_module, monkeypatch):
    """MacOSTrayIcon.__init__ launches GUI thread when --gui is set."""

    class FakeTimer:
        """Stub timer class for testing."""

        def __init__(self, *_a):
            """Initialize fake timer (unused args)."""

        def start(self):
            """No-op timer start."""

    monkeypatch.setattr(
        _call_member(macos_module, "__getattribute__", "_rumps_lib"),
        "Timer",
        FakeTimer,
    )
    monkeypatch.setattr(macos_module, "get_llmster_cmd", lambda: None)
    monkeypatch.setattr(macos_module, "get_desktop_app_pids", lambda: [])
    monkeypatch.setattr(
        macos_module.MacOSTrayIcon, "_APP_LOCATIONS", []
    )
    app_state = _call_member(macos_module, "__getattribute__", "_AppState")
    app_state.GUI_MODE = True
    threads_started = []

    class FakeThread:
        """Stub thread class for testing."""

        def __init__(self, target=None, daemon=True, name=""):
            """Initialize thread with target and name."""
            self.name = name

        def start(self):
            """Record thread start."""
            threads_started.append(self.name)

    monkeypatch.setattr(macos_module.threading, "Thread", FakeThread)
    try:
        tray = macos_module.MacOSTrayIcon()
        assert tray is not None  # nosec B101
        assert any("auto-gui" in n for n in threads_started)  # nosec B101
    finally:
        app_state.GUI_MODE = False


def test_macos_start_daemon_thread_starts(macos_module, monkeypatch):
    """start_daemon launches a thread when cooldown allows."""
    tray = _make_macos_tray(macos_module)
    tray.action_lock_until = 0.0
    called = []
    monkeypatch.setattr(
        tray, "_start_daemon_body", lambda: called.append(1)
    )
    tray.start_daemon(None)
    assert called  # nosec B101


def test_macos_stop_daemon_thread_starts(macos_module, monkeypatch):
    """stop_daemon launches a thread when cooldown allows."""
    tray = _make_macos_tray(macos_module)
    tray.action_lock_until = 0.0
    called = []
    monkeypatch.setattr(
        tray, "_stop_daemon_body", lambda: called.append(1)
    )
    tray.stop_daemon(None)
    assert called  # nosec B101


def test_macos_start_desktop_app_thread_starts(
    macos_module, monkeypatch
):
    """start_desktop_app launches a thread when cooldown allows."""
    tray = _make_macos_tray(macos_module)
    tray.action_lock_until = 0.0
    called = []
    monkeypatch.setattr(
        tray, "_start_desktop_app_body", lambda: called.append(1)
    )
    tray.start_desktop_app(None)
    assert called  # nosec B101


def test_macos_force_stop_llmster_oserror_ignored(
    macos_module, monkeypatch
):
    """_force_stop_llmster silently ignores OSError from pkill."""
    tray = _make_macos_tray(macos_module)
    monkeypatch.setattr(
        macos_module, "get_pkill_cmd", lambda: "/usr/bin/pkill"
    )
    call_count = [0]

    def raise_oserror(_cmd):
        """Raise OSError simulating pkill failure."""
        call_count[0] += 1
        raise OSError("permission denied")

    monkeypatch.setattr(macos_module, "_run_safe_command", raise_oserror)
    monkeypatch.setattr(macos_module, "is_llmster_running", lambda: False)
    _call_member(tray, "_force_stop_llmster")
    assert call_count[0] > 0  # nosec B101


def test_macos_check_model_lms_ps_fail_api_false(
    macos_module, monkeypatch
):
    """Sets INFO when lms ps errors and API reports no model."""
    tray = _make_macos_tray(macos_module)
    tray.last_status = "WARN"
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "get_daemon_status", lambda: "running")
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")
    monkeypatch.setattr(macos_module, "get_lms_cmd", lambda: "/usr/bin/lms")
    monkeypatch.setattr(
        macos_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=1, stdout="", stderr=""),
    )
    monkeypatch.setattr(macos_module, "check_api_models", lambda: False)
    tray.check_model()
    assert tray.title == "ℹ️"  # nosec B101


def test_macos_get_desktop_app_status_get_pids_error(
    macos_module, monkeypatch
):
    """get_desktop_app_status handles OSError from get_desktop_app_pids."""
    tray = _make_macos_tray(macos_module)

    def raise_oserror():
        raise OSError("no ps")

    monkeypatch.setattr(macos_module, "get_desktop_app_pids", raise_oserror)
    monkeypatch.setattr(
        macos_module.MacOSTrayIcon, "_APP_LOCATIONS", []
    )
    status = tray.get_desktop_app_status()
    assert status == "not_found"  # nosec B101


def test_macos_stop_desktop_app_kill_permission_error(
    macos_module, monkeypatch
):
    """stop_desktop_app ignores PermissionError when killing process."""
    tray = _make_macos_tray(macos_module)
    tray.action_lock_until = 0.0
    monkeypatch.setattr(
        macos_module, "get_desktop_app_pids", lambda: [9999]
    )

    def raise_permerror(_pid, _sig):
        """Raise PermissionError simulating kill failure."""
        raise PermissionError("not allowed")

    monkeypatch.setattr(os, "kill", raise_permerror)
    monkeypatch.setattr(tray, "_schedule_menu_refresh", lambda *_: None)
    tray.stop_desktop_app(None)


def test_macos_manual_check_updates_returns_when_notified(
    macos_module, monkeypatch
):
    """manual_check_updates returns early when check_updates notifies."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(tray, "check_updates", lambda: True)
    tray.manual_check_updates(None)
    alerts = DummyRumpsModule.get_alerts()
    assert not alerts  # nosec B101


def test_run_macos_launches_tray(macos_module, monkeypatch, tmp_path):
    """_run_macos sets up logging and calls MacOSTrayIcon().run()."""
    ran = []

    class FakeTimer:
        """Stub timer class for testing."""

        def __init__(self, *_a):
            """Initialize fake timer (unused args)."""

        def start(self):
            """No-op timer start."""

    rumps_lib = _call_member(
        macos_module, "__getattribute__", "_rumps_lib"
    )
    monkeypatch.setattr(rumps_lib, "Timer", FakeTimer)
    monkeypatch.setattr(macos_module, "get_llmster_cmd", lambda: None)
    monkeypatch.setattr(macos_module, "get_desktop_app_pids", lambda: [])
    monkeypatch.setattr(
        macos_module.MacOSTrayIcon, "_APP_LOCATIONS", []
    )
    monkeypatch.setattr(
        macos_module, "kill_existing_instances", lambda: None
    )
    monkeypatch.setattr(
        macos_module, "get_app_version", lambda: "v1.0.0"
    )
    app_state = _call_member(macos_module, "__getattribute__", "_AppState")
    monkeypatch.setattr(app_state, "script_dir", str(tmp_path))

    original_run = macos_module.MacOSTrayIcon.run

    def fake_run(_self):
        """Record run invocation."""
        ran.append(1)

    monkeypatch.setattr(macos_module.MacOSTrayIcon, "run", fake_run)
    try:
        _call_member(
            macos_module,
            "_run_macos",
            SimpleNamespace(auto_start_daemon=False, gui=False),
        )
        assert ran  # nosec B101
    finally:
        monkeypatch.setattr(macos_module.MacOSTrayIcon, "run", original_run)


def test_macos_start_daemon_body_attempt_oserror(
    macos_module, monkeypatch
):
    """_start_daemon_body catches OSError during daemon start attempt."""
    tray = _make_macos_tray(macos_module)
    DummyRumpsModule.reset()
    monkeypatch.setattr(
        macos_module, "get_lms_cmd", lambda: "/usr/local/bin/lms"
    )
    monkeypatch.setattr(macos_module, "get_llmster_cmd", lambda: None)
    monkeypatch.setattr(tray, "get_desktop_app_status", lambda: "stopped")

    def raise_oserror(_cmd):
        """Raise OSError simulating command execution failure."""
        raise OSError("exec failed")

    monkeypatch.setattr(macos_module, "_run_safe_command", raise_oserror)
    monkeypatch.setattr(macos_module, "is_llmster_running", lambda: False)
    _call_member(tray, "_start_daemon_body")
    notifications = DummyRumpsModule.get_notifications()
    assert any(
        "failed" in n[2].lower()
        for n in notifications
    )  # nosec B101


def test_macos_build_daemon_attempts_llmster(macos_module, monkeypatch):
    """_build_daemon_attempts uses llmster when lms is absent."""
    tray = _make_macos_tray(macos_module)
    monkeypatch.setattr(macos_module, "get_lms_cmd", lambda: None)
    monkeypatch.setattr(
        macos_module,
        "get_llmster_cmd",
        lambda: "/usr/local/bin/llmster",
    )
    start_attempts = _call_member(
        tray, "_build_daemon_attempts", "start"
    )
    stop_attempts = _call_member(
        tray, "_build_daemon_attempts", "stop"
    )
    assert len(start_attempts) > 0  # nosec B101
    assert all(
        a[0] == "/usr/local/bin/llmster" for a in start_attempts
    )  # nosec B101
    assert len(stop_attempts) > 0  # nosec B101
