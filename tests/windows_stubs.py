"""
Shared test doubles for the Windows tray backend.

``lmstudio_tray`` decides at import time which platform it runs on and
which optional GUI library to use. The Windows tests therefore load a
second copy of the module with ``sys.platform`` pinned to ``win32`` and
``pystray``/``PIL`` replaced by the stubs below, so the Windows branches
can be exercised on any host - including the Linux CI runner, which has
neither library installed.

The ``windows_module`` fixture that performs that import lives in
``conftest.py``; everything reusable but fixture-independent lives here.
"""

import threading
from types import ModuleType, SimpleNamespace


def completed(returncode=0, stdout="", stderr=""):
    """Create a subprocess-like completed result object.

    Args:
        returncode: Exit status to report.
        stdout: Captured standard output.
        stderr: Captured standard error.

    Returns:
        SimpleNamespace: Object with the CompletedProcess attributes used
        by the tray.
    """
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class DummyMenuItem:
    """Stand-in for ``pystray.MenuItem``."""

    def __init__(self, text, action=None, enabled=True, checked=None):
        """Record the item's text, callback, enabled and checked state."""
        self.text = text
        self.action = action
        self.enabled = enabled
        # pystray accepts either None (not a checkbox) or a callable it
        # invokes with the item; the stub keeps it unevaluated so tests can
        # assert on the state at the moment they choose.
        self.checked = checked

    def __repr__(self):
        """Return a debugging representation naming the item."""
        return f"<DummyMenuItem {self.text!r}>"


class DummyMenu:
    """Stand-in for ``pystray.Menu``."""

    SEPARATOR = "---SEPARATOR---"

    def __init__(self, *items):
        """Store the items the menu was built from."""
        self.items = list(items)


class DummyIcon:
    """Stand-in for ``pystray.Icon`` recording every interaction."""

    def __init__(self, name, icon=None, title=None, menu=None):
        """Create the icon stub with empty interaction logs."""
        self.name = name
        self.icon = icon
        self.title = title
        self.menu = menu
        self.visible = False
        self.notifications = []
        self.update_menu_calls = 0
        self.stopped = False
        self.ran = False

    def notify(self, message, title=None):
        """Record a notification instead of showing one."""
        self.notifications.append((title, message))

    def update_menu(self):
        """Count menu refreshes."""
        self.update_menu_calls += 1

    def run(self, setup=None):
        """Run the setup callback synchronously, as pystray would."""
        self.ran = True
        if setup is not None:
            setup(self)

    def stop(self):
        """Record that the icon was stopped."""
        self.stopped = True


class DummyPystrayModule(ModuleType):
    """Minimal stand-in for the ``pystray`` package."""

    def __init__(self, name="pystray"):
        """Create the stub module with the pystray API surface used."""
        super().__init__(name)
        self.Icon = DummyIcon
        self.Menu = DummyMenu
        self.MenuItem = DummyMenuItem


class DummyPilImage(ModuleType):
    """Minimal stand-in for ``PIL.Image`` recording open/new calls."""

    def __init__(self, name="PIL.Image"):
        """Create the stub module with recording ``open`` and ``new``."""
        super().__init__(name)
        self.opened = []
        self.created = []

        def _open(path, *_args, **_kwargs):
            """Record the opened path and return a marker object."""
            self.opened.append(path)
            return f"image:{path}"

        def _new(mode, size, color=None):
            """Record the fallback image and return a marker object."""
            self.created.append((mode, size, color))
            return "image:fallback"

        self.open = _open
        self.new = _new


class DummyThread:
    """Synchronous stand-in for ``threading.Thread``.

    The tray hands daemon and desktop-app actions to worker threads.
    Running the target inline means a menu callback has finished its work
    by the time it returns, with no waiting or polling in the tests.
    """

    def __init__(self, target, args=(), kwargs=None, **_ignored):
        """Store the callable and its arguments."""
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = True

    def start(self):
        """Invoke the target immediately on the calling thread."""
        self.target(*self.args, **self.kwargs)

    def join(self, timeout=None):
        """Return at once; the target already ran in start()."""
        _ = timeout


class DummyTimer:
    """Stand-in for ``threading.Timer`` that records instead of firing.

    Instances are collected on the class so a test can assert that the
    delayed menu refresh was scheduled, and with what delay, without
    waiting for it or leaving a live timer behind after teardown.
    """

    created: list = []

    def __init__(self, interval, function, args=(), kwargs=None):
        """Record the scheduled call."""
        self.interval = interval
        self.function = function
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = False
        self.started = False

    def start(self):
        """Mark the timer as started without scheduling anything."""
        self.started = True
        type(self).created.append(self)

    def fire(self):
        """Invoke the scheduled callable, as the real timer would."""
        return self.function(*self.args, **self.kwargs)


def install_sync_threads(monkeypatch):
    """Run worker threads inline and neutralise delayed timers.

    Args:
        monkeypatch: pytest monkeypatch fixture.
    """
    DummyTimer.created.clear()
    monkeypatch.setattr(threading, "Thread", DummyThread)
    monkeypatch.setattr(threading, "Timer", DummyTimer)


def make_tray(module):
    """Build a WindowsTrayIcon with a stub icon, bypassing ``__init__``.

    Mirrors ``_make_macos_tray`` in the main suite: the real constructor
    starts monitoring threads and builds a menu, neither of which most
    unit tests want.

    Args:
        module: The Windows-flavoured ``lmstudio_tray`` module.

    Returns:
        The partially initialised tray instance.
    """
    tray = module.WindowsTrayIcon.__new__(module.WindowsTrayIcon)
    tray.last_status = None
    tray.action_lock_until = 0.0
    tray.lms_ps_resume_at = 0.0
    tray.remote_loaded_models = []
    tray.last_update_version = None
    tray.update_status = "Unknown"
    tray.latest_update_version = None
    tray.last_update_error = None
    tray.icon = DummyIcon("test", title="⚠️ test")
    setattr(
        tray,
        "_desktop_detection",
        {"seen_call": False, "last_detection": None},
    )
    setattr(
        tray,
        "_update_info",
        {
            "status": "Unknown",
            "last_error": None,
            "latest_version": None,
            "last_version": None,
        },
    )
    setattr(tray, "_status_emoji", "⚠️")
    setattr(tray, "_stop_event", threading.Event())
    return tray


def menu_labels(tray):
    """Return the text of every entry in the tray's current menu.

    Args:
        tray: The tray whose menu should be inspected.

    Returns:
        list: Item texts, with separators kept as their sentinel value.
    """
    return [
        item.text if isinstance(item, DummyMenuItem) else item
        for item in tray.icon.menu.items
    ]


def menu_item(tray, needle):
    """Return the first menu item whose text contains ``needle``.

    Args:
        tray: The tray whose menu should be searched.
        needle: Substring to look for.

    Returns:
        DummyMenuItem: The matching item.

    Raises:
        AssertionError: When no item matches.
    """
    for item in tray.icon.menu.items:
        if isinstance(item, DummyMenuItem) and needle in item.text:
            return item
    raise AssertionError(f"No menu item matching {needle!r}")


def stub_statuses(module, monkeypatch, daemon, app):
    """Pin both status probes for a menu-building test.

    Args:
        module: The Windows-flavoured ``lmstudio_tray`` module.
        monkeypatch: pytest monkeypatch fixture.
        daemon: Daemon status to report.
        app: Desktop app status to report.
    """
    monkeypatch.setattr(module, "is_remote_endpoint", lambda: False)
    monkeypatch.setattr(
        module.WindowsTrayIcon, "get_daemon_status", lambda _self: daemon
    )
    monkeypatch.setattr(
        module.WindowsTrayIcon, "get_desktop_app_status", lambda _self: app
    )
