"""
Test suite for the Windows platform primitives in lmstudio_tray.py.

These cover the platform-neutral half of the module - paths, process
detection and single-instance handling - as it behaves once the platform
is Windows. The tray class itself is covered in
``test_lmstudio_tray_windows_tray.py``.

The ``windows_module`` fixture (see ``conftest.py``) imports a second copy
of the module with ``sys.platform`` pinned to ``win32``, so these branches
run on any host - including the Linux CI runner, which has neither
``pystray`` nor ``Pillow`` installed.

Covered here:
- platform flag derivation (IS_WINDOWS / IS_LINUX / IS_MACOS)
- Windows path conventions (%APPDATA%, %LOCALAPPDATA%, lms.exe)
- tasklist CSV parsing and the process queries built on it
- taskkill invocation
- single-instance handling for frozen vs. source runs
"""

import os
import signal
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

from windows_stubs import completed as _completed

# ---------------------------------------------------------------------
# Platform flags
# ---------------------------------------------------------------------


def test_platform_flags_windows(windows_module):
    """IS_WINDOWS is the only flag set when sys.platform is win32."""
    assert windows_module.IS_WINDOWS is True  # nosec B101
    assert windows_module.IS_MACOS is False  # nosec B101
    assert windows_module.IS_LINUX is False  # nosec B101


def test_platform_flags_are_mutually_exclusive(windows_module):
    """Exactly one platform flag is ever true."""
    flags = (
        windows_module.IS_WINDOWS,
        windows_module.IS_MACOS,
        windows_module.IS_LINUX,
    )
    assert sum(1 for flag in flags if flag) == 1  # nosec B101


def test_pystray_and_pil_import_guards(windows_module):
    """Optional GUI libraries are resolved through the import guards."""
    assert windows_module._pystray_lib is not None  # nosec B101
    assert windows_module._pil_image is not None  # nosec B101


# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------


def test_config_path_uses_appdata(windows_module, tmp_path):
    """Config lives under %APPDATA%, not ~/.config, on Windows."""
    expected = (
        tmp_path / "AppData" / "Roaming"
        / "lmstudio-tray-manager" / "lmstudio_tray.json"
    )
    assert (  # nosec B101
        Path(windows_module._get_config_path()) == expected
    )


def test_config_path_falls_back_without_appdata(
    windows_module, monkeypatch, tmp_path
):
    """A missing %APPDATA% falls back to the standard Roaming location."""
    monkeypatch.delenv("APPDATA", raising=False)
    path = Path(windows_module._get_config_path())
    assert path.name == "lmstudio_tray.json"  # nosec B101
    assert "Roaming" in path.parts  # nosec B101
    assert str(tmp_path / "home") in str(path)  # nosec B101


def test_config_read_paths_include_legacy_location(windows_module):
    """The old ~/.config path is still read so upgrades keep settings."""
    paths = windows_module._get_config_read_paths()
    assert len(paths) == 2  # nosec B101
    assert paths[0] == windows_module._get_config_path()  # nosec B101
    assert paths[1].endswith("lmstudio_tray.json")  # nosec B101
    assert ".config" in paths[1]  # nosec B101


def test_load_config_reads_legacy_path(windows_module, tmp_path):
    """A legacy config is used when the %APPDATA% one is absent."""
    legacy = tmp_path / "home" / ".config"
    legacy.mkdir(parents=True)
    (legacy / "lmstudio_tray.json").write_text(
        '{"api_host": "10.0.0.5", "api_port": 4321}', encoding="utf-8"
    )

    windows_module.load_config()

    assert windows_module._AppState.API_HOST == "10.0.0.5"  # nosec B101
    assert windows_module._AppState.API_PORT == 4321  # nosec B101


def test_load_config_prefers_appdata_over_legacy(windows_module, tmp_path):
    """When both configs exist the %APPDATA% one wins."""
    legacy = tmp_path / "home" / ".config"
    legacy.mkdir(parents=True)
    (legacy / "lmstudio_tray.json").write_text(
        '{"api_host": "10.0.0.5", "api_port": 4321}', encoding="utf-8"
    )
    current = Path(windows_module._get_config_path())
    current.parent.mkdir(parents=True)
    current.write_text(
        '{"api_host": "192.168.1.9", "api_port": 1234}', encoding="utf-8"
    )

    windows_module.load_config()

    assert windows_module._AppState.API_HOST == "192.168.1.9"  # nosec B101
    assert windows_module._AppState.API_PORT == 1234  # nosec B101


def test_save_config_round_trip(windows_module):
    """A saved config is read back from the %APPDATA% location."""
    windows_module.save_config("172.16.0.3", 8080)

    assert os.path.isfile(windows_module._get_config_path())  # nosec B101

    windows_module._AppState.API_HOST = "127.0.0.1"
    windows_module._AppState.API_PORT = 1234
    windows_module.load_config()

    assert windows_module._AppState.API_HOST == "172.16.0.3"  # nosec B101
    assert windows_module._AppState.API_PORT == 8080  # nosec B101


def test_user_data_dir_uses_localappdata(windows_module, tmp_path):
    """Machine-local state goes under %LOCALAPPDATA%."""
    expected = tmp_path / "AppData" / "Local" / "lmstudio-tray-manager"
    assert (  # nosec B101
        Path(windows_module._get_user_data_dir()) == expected
    )


def test_user_data_dir_falls_back_without_localappdata(
    windows_module, monkeypatch
):
    """A missing %LOCALAPPDATA% falls back to the standard Local path."""
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    path = Path(windows_module._get_user_data_dir())
    assert path.name == "lmstudio-tray-manager"  # nosec B101
    assert "Local" in path.parts  # nosec B101


def test_writable_logs_dir_falls_back_to_user_data_dir(
    windows_module, monkeypatch, tmp_path
):
    """An unwritable install directory pushes logs to %LOCALAPPDATA%."""
    install_dir = str(tmp_path / "program-files")
    real_makedirs = os.makedirs

    def makedirs_denying_install_dir(path, *args, **kwargs):
        """Reject the read-only install directory, allow the fallback."""
        if str(path).startswith(install_dir):
            raise PermissionError("read-only")
        return real_makedirs(path, *args, **kwargs)

    monkeypatch.setattr(
        windows_module.os, "makedirs", makedirs_denying_install_dir
    )

    logs_dir = windows_module._get_writable_logs_dir(install_dir)

    expected = (
        tmp_path / "AppData" / "Local" / "lmstudio-tray-manager" / "logs"
    )
    assert Path(logs_dir) == expected  # nosec B101
    assert os.path.isdir(logs_dir)  # nosec B101


def test_lms_cli_uses_exe_suffix(windows_module):
    """The bundled lms CLI is lms.exe on Windows."""
    assert windows_module.LMS_CLI.endswith("lms.exe")  # nosec B101


def test_is_executable_file_ignores_permission_bit(windows_module, tmp_path):
    """NTFS has no execute bit, so existence is the only usable test."""
    candidate = tmp_path / "lms.exe"
    candidate.write_text("", encoding="utf-8")

    assert windows_module._is_executable_file(str(candidate))  # nosec B101
    assert not windows_module._is_executable_file(  # nosec B101
        str(tmp_path / "missing.exe")
    )


def test_get_lms_cmd_prefers_bundled_exe(windows_module, monkeypatch):
    """The bundled lms.exe wins over anything on PATH."""
    lms_path = Path(windows_module.LMS_CLI)
    lms_path.parent.mkdir(parents=True, exist_ok=True)
    lms_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        windows_module.shutil, "which", lambda _name: r"C:\other\lms.exe"
    )

    assert (  # nosec B101
        windows_module.get_lms_cmd() == windows_module.LMS_CLI
    )


def test_get_llmster_cmd_finds_exe_in_install_dir(
    windows_module, monkeypatch, tmp_path
):
    """The directory scan accepts llmster.exe, not just llmster."""
    monkeypatch.setattr(windows_module.shutil, "which", lambda _name: None)
    llmster_dir = tmp_path / "home" / ".lmstudio" / "llmster" / "0.0.21"
    llmster_dir.mkdir(parents=True)
    binary = llmster_dir / "llmster.exe"
    binary.write_text("", encoding="utf-8")

    resolved = windows_module.get_llmster_cmd()

    assert resolved is not None  # nosec B101
    # expanduser("~/.lmstudio/...") keeps its forward slashes, which Windows
    # accepts but does not normalise, so compare as paths rather than text.
    assert Path(resolved) == binary  # nosec B101


def test_get_llmster_cmd_picks_highest_version(
    windows_module, monkeypatch, tmp_path
):
    """With several installs the last sorted candidate is used."""
    monkeypatch.setattr(windows_module.shutil, "which", lambda _name: None)
    root = tmp_path / "home" / ".lmstudio" / "llmster"
    for version in ("0.0.19", "0.0.21"):
        version_dir = root / version
        version_dir.mkdir(parents=True)
        (version_dir / "llmster.exe").write_text("", encoding="utf-8")

    resolved = windows_module.get_llmster_cmd()

    assert resolved is not None  # nosec B101
    assert "0.0.21" in resolved  # nosec B101


# ---------------------------------------------------------------------
# tasklist parsing
# ---------------------------------------------------------------------


def test_parse_tasklist_csv_handles_names_with_spaces(windows_module):
    """Quoted image names containing spaces survive the CSV parse."""
    output = (
        '"LM Studio.exe","4321","Console","1","350.000 K"\r\n'
        '"LM Studio.exe","4322","Console","1","120.000 K"\r\n'
    )

    assert windows_module._parse_tasklist_csv(output) == [  # nosec B101
        ("LM Studio.exe", 4321),
        ("LM Studio.exe", 4322),
    ]


def test_parse_tasklist_csv_skips_info_line(windows_module):
    """The 'no tasks match' notice is not mistaken for a process row."""
    output = (
        "INFO: No tasks are running which match the specified criteria.\r\n"
    )

    assert windows_module._parse_tasklist_csv(output) == []  # nosec B101


def test_parse_tasklist_csv_handles_empty_output(windows_module):
    """Empty stdout yields no processes."""
    assert windows_module._parse_tasklist_csv("") == []  # nosec B101
    assert windows_module._parse_tasklist_csv("\r\n\r\n") == []  # nosec B101


def test_parse_tasklist_csv_skips_non_numeric_pid(windows_module):
    """Rows whose PID column is not numeric are discarded."""
    output = '"llmster.exe","not-a-pid","Console","1","1 K"\r\n'

    assert windows_module._parse_tasklist_csv(output) == []  # nosec B101


def test_query_tasklist_builds_filter(windows_module, monkeypatch):
    """The tasklist query uses an IMAGENAME filter with CSV output."""
    calls = []

    monkeypatch.setattr(
        windows_module.shutil,
        "which",
        lambda _name: r"C:\Windows\System32\tasklist.exe",
    )

    def fake_run(command):
        """Record the command and return one matching process."""
        calls.append(command)
        return _completed(
            returncode=0, stdout='"llmster.exe","777","Console","1","1 K"\r\n'
        )

    monkeypatch.setattr(windows_module, "_run_safe_command", fake_run)

    result = windows_module._query_tasklist("llmster.exe")

    assert result == [("llmster.exe", 777)]  # nosec B101
    assert calls[0][1:] == [  # nosec B101
        "/FI", "IMAGENAME eq llmster.exe", "/NH", "/FO", "CSV",
    ]


def test_query_tasklist_without_tasklist_available(
    windows_module, monkeypatch
):
    """A missing tasklist.exe yields no processes rather than raising."""
    monkeypatch.setattr(windows_module.shutil, "which", lambda _name: None)

    assert windows_module._query_tasklist("llmster.exe") == []  # nosec B101


def test_query_tasklist_swallows_subprocess_errors(
    windows_module, monkeypatch
):
    """An OSError from tasklist is logged, not propagated."""
    monkeypatch.setattr(
        windows_module.shutil,
        "which",
        lambda _name: r"C:\Windows\System32\tasklist.exe",
    )

    def boom(_command):
        """Simulate tasklist failing to launch."""
        raise OSError("boom")

    monkeypatch.setattr(windows_module, "_run_safe_command", boom)

    assert windows_module._query_tasklist("llmster.exe") == []  # nosec B101


def test_query_tasklist_ignores_nonzero_exit(windows_module, monkeypatch):
    """A non-zero tasklist exit yields no processes."""
    monkeypatch.setattr(
        windows_module.shutil,
        "which",
        lambda _name: r"C:\Windows\System32\tasklist.exe",
    )
    monkeypatch.setattr(
        windows_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=1, stdout="whatever"),
    )

    assert windows_module._query_tasklist("llmster.exe") == []  # nosec B101


# ---------------------------------------------------------------------
# taskkill
# ---------------------------------------------------------------------


def test_run_taskkill_passes_arguments(windows_module, monkeypatch):
    """taskkill is invoked with the absolute exe plus the given arguments."""
    calls = []
    monkeypatch.setattr(
        windows_module.shutil,
        "which",
        lambda _name: r"C:\Windows\System32\taskkill.exe",
    )
    monkeypatch.setattr(
        windows_module,
        "_run_safe_command",
        lambda cmd: calls.append(cmd) or _completed(returncode=0),
    )

    assert windows_module._run_taskkill(  # nosec B101
        ["/IM", "llmster.exe", "/T"]
    )
    assert calls == [[  # nosec B101
        r"C:\Windows\System32\taskkill.exe", "/IM", "llmster.exe", "/T",
    ]]


def test_run_taskkill_reports_no_match_as_success(
    windows_module, monkeypatch
):
    """Exit 128 means 'nothing matched', which is a successful no-op."""
    monkeypatch.setattr(
        windows_module.shutil,
        "which",
        lambda _name: r"C:\Windows\System32\taskkill.exe",
    )
    monkeypatch.setattr(
        windows_module,
        "_run_safe_command",
        lambda _cmd: _completed(returncode=128),
    )

    assert windows_module._run_taskkill(["/IM", "x.exe"])  # nosec B101


def test_run_taskkill_without_taskkill_available(windows_module, monkeypatch):
    """A missing taskkill.exe reports failure instead of raising."""
    monkeypatch.setattr(windows_module.shutil, "which", lambda _name: None)

    assert not windows_module._run_taskkill(["/IM", "x.exe"])  # nosec B101


def test_run_taskkill_swallows_subprocess_errors(windows_module, monkeypatch):
    """A SubprocessError from taskkill is logged, not propagated."""
    monkeypatch.setattr(
        windows_module.shutil,
        "which",
        lambda _name: r"C:\Windows\System32\taskkill.exe",
    )

    def boom(_command):
        """Simulate taskkill failing to launch."""
        raise subprocess.SubprocessError("boom")

    monkeypatch.setattr(windows_module, "_run_safe_command", boom)

    assert not windows_module._run_taskkill(["/IM", "x.exe"])  # nosec B101


# ---------------------------------------------------------------------
# Process detection
# ---------------------------------------------------------------------


def test_is_llmster_running_true(windows_module, monkeypatch):
    """A matching llmster.exe process means the daemon is running."""
    monkeypatch.setattr(
        windows_module,
        "_query_tasklist",
        lambda name: [("llmster.exe", 42)] if name == "llmster.exe" else [],
    )

    assert windows_module.is_llmster_running() is True  # nosec B101


def test_is_llmster_running_false(windows_module, monkeypatch):
    """No matching process means the daemon is not running."""
    monkeypatch.setattr(windows_module, "_query_tasklist", lambda _name: [])

    assert windows_module.is_llmster_running() is False  # nosec B101


def test_is_llmster_running_never_calls_pgrep(windows_module, monkeypatch):
    """The Windows branch returns before touching the POSIX helpers."""
    def fail(*_args, **_kwargs):
        """Fail the test if a POSIX helper is reached."""
        pytest.fail("POSIX process helper called on Windows")

    monkeypatch.setattr(windows_module, "get_pgrep_cmd", fail)
    monkeypatch.setattr(windows_module, "get_ps_cmd", fail)
    monkeypatch.setattr(windows_module, "_query_tasklist", lambda _name: [])

    assert windows_module.is_llmster_running() is False  # nosec B101


def test_get_desktop_app_pids_returns_all_electron_pids(
    windows_module, monkeypatch
):
    """Every LM Studio.exe PID is returned, helpers included."""
    monkeypatch.setattr(
        windows_module,
        "_query_tasklist",
        lambda name: (
            [("LM Studio.exe", 100), ("LM Studio.exe", 101)]
            if name == "LM Studio.exe"
            else []
        ),
    )

    assert windows_module.get_desktop_app_pids() == [100, 101]  # nosec B101


def test_get_desktop_app_pids_empty_when_not_running(
    windows_module, monkeypatch
):
    """No matching processes yields an empty PID list."""
    monkeypatch.setattr(windows_module, "_query_tasklist", lambda _name: [])

    assert windows_module.get_desktop_app_pids() == []  # nosec B101


# ---------------------------------------------------------------------
# Single-instance handling
# ---------------------------------------------------------------------


def test_kill_existing_instances_skips_when_not_frozen(
    windows_module, monkeypatch
):
    """Running from source, python.exe cannot be matched safely."""
    monkeypatch.delattr(windows_module.sys, "frozen", raising=False)

    def fail(_name):
        """Fail the test if tasklist is consulted."""
        pytest.fail("tasklist queried for a non-frozen run")

    monkeypatch.setattr(windows_module, "_query_tasklist", fail)

    windows_module.kill_existing_instances()


def test_kill_existing_instances_terminates_other_frozen_copies(
    windows_module, monkeypatch
):
    """A frozen build terminates other copies but never itself."""
    monkeypatch.setattr(windows_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(windows_module.os, "getppid", lambda: 88888)
    monkeypatch.setattr(
        windows_module,
        "_query_tasklist",
        lambda name: (
            [
                ("lmstudio-tray-manager.exe", 99999),
                ("lmstudio-tray-manager.exe", 555),
            ]
            if name == "lmstudio-tray-manager.exe"
            else []
        ),
    )

    killed = []
    monkeypatch.setattr(
        windows_module.os, "kill", lambda pid, sig: killed.append((pid, sig))
    )

    windows_module.kill_existing_instances()

    assert killed == [(555, signal.SIGTERM)]  # nosec B101


def test_kill_existing_instances_spares_the_bootloader(
    windows_module, monkeypatch
):
    """The one-file bootloader parent is never terminated.

    PyInstaller runs a one-file build as two processes sharing an image
    name. Killing the parent orphans the unpacked temporary directory it
    is responsible for deleting.
    """
    monkeypatch.setattr(windows_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(windows_module.os, "getppid", lambda: 11112)
    monkeypatch.setattr(
        windows_module,
        "_query_tasklist",
        lambda _name: [
            ("lmstudio-tray-manager.exe", 11112),
            ("lmstudio-tray-manager.exe", 99999),
        ],
    )

    killed = []
    monkeypatch.setattr(
        windows_module.os, "kill", lambda pid, sig: killed.append(pid)
    )

    windows_module.kill_existing_instances()

    assert killed == []  # nosec B101


def test_own_process_pids_without_getppid(windows_module, monkeypatch):
    """A missing getppid degrades to protecting just this process."""
    monkeypatch.delattr(windows_module.os, "getppid", raising=False)

    assert windows_module._own_process_pids() == {99999}  # nosec B101


def test_kill_existing_instances_survives_permission_error(
    windows_module, monkeypatch
):
    """A PID that cannot be signalled is logged, not fatal."""
    monkeypatch.setattr(windows_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        windows_module,
        "_query_tasklist",
        lambda _name: [("lmstudio-tray-manager.exe", 555)],
    )

    def deny(_pid, _sig):
        """Simulate a process owned by another user."""
        raise PermissionError("access denied")

    monkeypatch.setattr(windows_module.os, "kill", deny)

    windows_module.kill_existing_instances()


def test_kill_existing_instances_never_calls_pgrep(
    windows_module, monkeypatch
):
    """The Windows branch returns before reaching the pgrep path."""
    monkeypatch.delattr(windows_module.sys, "frozen", raising=False)

    def fail():
        """Fail the test if pgrep is looked up."""
        pytest.fail("get_pgrep_cmd called on Windows")

    monkeypatch.setattr(windows_module, "get_pgrep_cmd", fail)

    windows_module.kill_existing_instances()


# ---------------------------------------------------------------------
# Autostart (Startup-folder shortcut)
# ---------------------------------------------------------------------


@pytest.fixture(name="startup_dir")
def startup_dir_fixture(windows_module, monkeypatch, tmp_path):
    """Redirect the Startup folder into tmp_path.

    Without this the helpers ask the real shell where Startup is, and on a
    Windows host these tests would create and delete shortcuts in the
    developer's actual Startup folder.
    """
    startup = tmp_path / "Startup"
    startup.mkdir()
    monkeypatch.setattr(
        windows_module, "_get_startup_dir", lambda: str(startup)
    )
    return startup


def test_startup_dir_prefers_the_shell(windows_module, monkeypatch, tmp_path):
    """SHGetFolderPathW decides, so folder redirection is honoured."""
    resolved = tmp_path / "Redirected"

    class FakeBuffer:
        """Minimal stand-in for a ctypes string buffer."""

        value = ""

    class FakeShell32:
        """Namespace mirroring ctypes.windll.shell32."""

        @staticmethod
        def SHGetFolderPathW(  # pylint: disable=invalid-name
            _token, _csidl, _handle, _flags, buf
        ):
            """Write the redirected path and report success."""
            buf.value = str(resolved)
            return 0

    class FakeWindll:
        """Namespace mirroring ctypes.windll."""

        shell32 = FakeShell32

    class FakeCtypes:
        """Stand-in for the ctypes module's Windows surface."""

        windll = FakeWindll

        @staticmethod
        def create_unicode_buffer(_size):
            """Return an object exposing a writable ``value``."""
            return FakeBuffer()

    monkeypatch.setitem(sys.modules, "ctypes", FakeCtypes)

    assert windows_module._get_startup_dir() == str(resolved)  # nosec B101


def test_startup_dir_falls_back_to_appdata(
    windows_module, monkeypatch, tmp_path
):
    """When the shell call is unavailable, %APPDATA% supplies the path."""
    monkeypatch.setitem(sys.modules, "ctypes", None)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))

    expected = os.path.join(
        str(tmp_path / "Roaming"),
        "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    )

    assert windows_module._get_startup_dir() == expected  # nosec B101


def test_startup_dir_without_appdata(windows_module, monkeypatch):
    """With neither the shell nor %APPDATA%, there is no answer to give."""
    monkeypatch.setitem(sys.modules, "ctypes", None)
    monkeypatch.delenv("APPDATA", raising=False)

    assert windows_module._get_startup_dir() is None  # nosec B101


def test_shortcut_path_uses_the_shared_name(windows_module, startup_dir):
    """The name matches the PowerShell script and the installer."""
    expected = os.path.join(
        str(startup_dir), windows_module.AUTOSTART_SHORTCUT_NAME
    )

    assert (  # nosec B101
        windows_module.get_autostart_shortcut_path() == expected
    )
    assert (  # nosec B101
        windows_module.AUTOSTART_SHORTCUT_NAME
        == "LM Studio Tray Manager.lnk"
    )


def test_shortcut_path_without_a_startup_folder(windows_module, monkeypatch):
    """No Startup folder means no shortcut path."""
    monkeypatch.setattr(windows_module, "_get_startup_dir", lambda: None)

    assert windows_module.get_autostart_shortcut_path() is None  # nosec B101


def test_is_autostart_enabled_tracks_the_shortcut(windows_module, startup_dir):
    """Presence of the file is the whole state."""
    assert windows_module.is_autostart_enabled() is False  # nosec B101

    (startup_dir / windows_module.AUTOSTART_SHORTCUT_NAME).write_text(
        "", encoding="utf-8"
    )

    assert windows_module.is_autostart_enabled() is True  # nosec B101


def test_is_autostart_enabled_without_a_startup_folder(
    windows_module, monkeypatch
):
    """An unknown Startup folder reads as not enabled rather than raising."""
    monkeypatch.setattr(windows_module, "_get_startup_dir", lambda: None)

    assert windows_module.is_autostart_enabled() is False  # nosec B101


def test_autostart_target_frozen(windows_module, monkeypatch, tmp_path):
    """A frozen build registers its own executable with no arguments."""
    exe = tmp_path / "lmstudio-tray-manager.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(windows_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(windows_module.sys, "executable", str(exe))

    assert windows_module._get_autostart_target() == (  # nosec B101
        str(exe), [], str(tmp_path),
    )


def test_autostart_target_frozen_but_missing(
    windows_module, monkeypatch, tmp_path
):
    """A frozen build whose executable has gone registers nothing."""
    monkeypatch.setattr(windows_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        windows_module.sys, "executable", str(tmp_path / "gone.exe")
    )

    assert windows_module._get_autostart_target() is None  # nosec B101


def test_autostart_target_source_prefers_pythonw(
    windows_module, monkeypatch, tmp_path
):
    """From source, pythonw.exe avoids a console window at login."""
    monkeypatch.delattr(windows_module.sys, "frozen", raising=False)
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    (scripts / "python.exe").write_text("", encoding="utf-8")
    (scripts / "pythonw.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        windows_module.sys, "executable", str(scripts / "python.exe")
    )

    executable, arguments, working_dir = (
        windows_module._get_autostart_target()
    )
    script = os.path.abspath(windows_module.__file__)

    assert executable == str(scripts / "pythonw.exe")  # nosec B101
    assert arguments == [script]  # nosec B101
    # The repository, not the interpreter's folder: the log directory and
    # the default script_dir are resolved relative to the process's cwd.
    assert working_dir == os.path.dirname(script)  # nosec B101


def test_autostart_target_source_falls_back_to_python(
    windows_module, monkeypatch, tmp_path
):
    """Without pythonw.exe the console interpreter still works."""
    monkeypatch.delattr(windows_module.sys, "frozen", raising=False)
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    (scripts / "python.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        windows_module.sys, "executable", str(scripts / "python.exe")
    )

    executable = windows_module._get_autostart_target()[0]

    assert executable == str(scripts / "python.exe")  # nosec B101


def test_autostart_target_without_an_interpreter(
    windows_module, monkeypatch, tmp_path
):
    """No usable interpreter means nothing can be registered."""
    monkeypatch.delattr(windows_module.sys, "frozen", raising=False)
    monkeypatch.setattr(
        windows_module.sys, "executable", str(tmp_path / "gone.exe")
    )

    assert windows_module._get_autostart_target() is None  # nosec B101


def test_ps_quote_doubles_apostrophes(windows_module):
    """A path such as ``Rob's Git`` must not end the quoted literal."""
    assert (  # nosec B101
        windows_module._ps_quote("D:\\Rob's Git\\app.exe")
        == "'D:\\Rob''s Git\\app.exe'"
    )


def _stub_powershell(windows_module, monkeypatch, shortcut, returncode=0):
    """Point the helpers at a fake powershell that creates the shortcut.

    Returns:
        list: The commands the fake powershell was handed.
    """
    recorded = []

    def fake_run(command):
        """Record the command and create the shortcut on success."""
        recorded.append(command)
        if returncode == 0:
            Path(shortcut).write_text("shortcut", encoding="utf-8")
        return _completed(returncode=returncode, stdout="", stderr="boom")

    monkeypatch.setattr(
        windows_module, "get_powershell_cmd", lambda: "C:\\Windows\\ps.exe"
    )
    monkeypatch.setattr(windows_module, "_run_safe_command", fake_run)
    return recorded


def test_enable_autostart_writes_the_shortcut(
    windows_module, monkeypatch, startup_dir, tmp_path
):
    """The generated command carries the target and working directory."""
    exe = tmp_path / "lmstudio-tray-manager.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        windows_module,
        "_get_autostart_target",
        lambda: (str(exe), [], str(tmp_path)),
    )
    shortcut = startup_dir / windows_module.AUTOSTART_SHORTCUT_NAME
    recorded = _stub_powershell(windows_module, monkeypatch, shortcut)

    assert windows_module.enable_autostart() is True  # nosec B101
    assert shortcut.is_file()  # nosec B101

    script = recorded[0][-1]
    assert windows_module._ps_quote(str(exe)) in script  # nosec B101
    assert (  # nosec B101
        f"$s.WorkingDirectory = {windows_module._ps_quote(str(tmp_path))};"
        in script
    )
    assert "WScript.Shell" in script  # nosec B101


def test_enable_autostart_passes_source_arguments(
    windows_module, monkeypatch, startup_dir, tmp_path
):
    """A source run registers the interpreter plus the script path."""
    interpreter = tmp_path / "pythonw.exe"
    interpreter.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        windows_module,
        "_get_autostart_target",
        lambda: (
            str(interpreter), ["D:\\repo\\lmstudio_tray.py"], "D:\\repo"
        ),
    )
    shortcut = startup_dir / windows_module.AUTOSTART_SHORTCUT_NAME
    recorded = _stub_powershell(windows_module, monkeypatch, shortcut)

    assert windows_module.enable_autostart() is True  # nosec B101
    script = recorded[0][-1]
    assert (  # nosec B101
        "$s.Arguments = 'D:\\repo\\lmstudio_tray.py';" in script
    )
    assert "$s.WorkingDirectory = 'D:\\repo';" in script  # nosec B101


def test_enable_autostart_without_a_startup_folder(
    windows_module, monkeypatch
):
    """An unknown Startup folder is reported rather than guessed at."""
    monkeypatch.setattr(windows_module, "_get_startup_dir", lambda: None)

    assert windows_module.enable_autostart() is False  # nosec B101


def test_enable_autostart_without_a_target(
    windows_module, monkeypatch, startup_dir
):
    """Nothing to point the shortcut at means no shortcut."""
    _ = startup_dir
    monkeypatch.setattr(windows_module, "_get_autostart_target", lambda: None)

    assert windows_module.enable_autostart() is False  # nosec B101


def test_enable_autostart_without_powershell(
    windows_module, monkeypatch, startup_dir, tmp_path
):
    """Creating a .lnk needs the shell's COM object via powershell.exe."""
    _ = startup_dir
    exe = tmp_path / "app.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        windows_module,
        "_get_autostart_target",
        lambda: (str(exe), [], str(tmp_path)),
    )
    monkeypatch.setattr(windows_module, "get_powershell_cmd", lambda: None)

    assert windows_module.enable_autostart() is False  # nosec B101


def test_enable_autostart_reports_a_failing_powershell(
    windows_module, monkeypatch, startup_dir, tmp_path
):
    """A non-zero exit is a failure even though no exception is raised."""
    exe = tmp_path / "app.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        windows_module,
        "_get_autostart_target",
        lambda: (str(exe), [], str(tmp_path)),
    )
    shortcut = startup_dir / windows_module.AUTOSTART_SHORTCUT_NAME
    _stub_powershell(windows_module, monkeypatch, shortcut, returncode=1)

    assert windows_module.enable_autostart() is False  # nosec B101
    assert not shortcut.exists()  # nosec B101


def test_enable_autostart_reports_a_silent_no_op(
    windows_module, monkeypatch, startup_dir, tmp_path
):
    """Exit 0 without a resulting file is still a failure."""
    _ = startup_dir
    exe = tmp_path / "app.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        windows_module,
        "_get_autostart_target",
        lambda: (str(exe), [], str(tmp_path)),
    )
    monkeypatch.setattr(
        windows_module, "get_powershell_cmd", lambda: "C:\\Windows\\ps.exe"
    )
    monkeypatch.setattr(
        windows_module,
        "_run_safe_command",
        lambda _command: _completed(returncode=0, stdout="", stderr=""),
    )

    assert windows_module.enable_autostart() is False  # nosec B101


def test_enable_autostart_survives_a_subprocess_error(
    windows_module, monkeypatch, startup_dir, tmp_path
):
    """A raising powershell is reported, not propagated to the menu."""
    _ = startup_dir
    exe = tmp_path / "app.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        windows_module,
        "_get_autostart_target",
        lambda: (str(exe), [], str(tmp_path)),
    )
    monkeypatch.setattr(
        windows_module, "get_powershell_cmd", lambda: "C:\\Windows\\ps.exe"
    )

    def boom(_command):
        """Simulate powershell.exe failing to launch."""
        raise OSError("cannot run")

    monkeypatch.setattr(windows_module, "_run_safe_command", boom)

    assert windows_module.enable_autostart() is False  # nosec B101


def test_disable_autostart_removes_the_shortcut(windows_module, startup_dir):
    """Disabling deletes the file the other tools also recognise."""
    shortcut = startup_dir / windows_module.AUTOSTART_SHORTCUT_NAME
    shortcut.write_text("", encoding="utf-8")

    assert windows_module.disable_autostart() is True  # nosec B101
    assert not shortcut.exists()  # nosec B101


def test_disable_autostart_is_idempotent(windows_module, startup_dir):
    """Already-absent is the requested end state, so it counts as success."""
    _ = startup_dir

    assert windows_module.disable_autostart() is True  # nosec B101


def test_disable_autostart_without_a_startup_folder(
    windows_module, monkeypatch
):
    """An unknown Startup folder cannot be cleaned up."""
    monkeypatch.setattr(windows_module, "_get_startup_dir", lambda: None)

    assert windows_module.disable_autostart() is False  # nosec B101


def test_disable_autostart_reports_a_locked_shortcut(
    windows_module, monkeypatch, startup_dir
):
    """A removal that fails is reported rather than claimed as success."""
    shortcut = startup_dir / windows_module.AUTOSTART_SHORTCUT_NAME
    shortcut.write_text("", encoding="utf-8")

    def deny(_path):
        """Simulate the file being locked or permission denied."""
        raise OSError("in use")

    monkeypatch.setattr(windows_module.os, "remove", deny)

    assert windows_module.disable_autostart() is False  # nosec B101
