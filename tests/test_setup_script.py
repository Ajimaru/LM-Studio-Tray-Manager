"""Smoke tests for `setup.sh` logic."""

import subprocess
from pathlib import Path

# setup.sh reads from stdin. A prompt that never gets an answer used to spin
# forever, which blocked the whole suite rather than failing one test - so
# every invocation here is bounded. Generous enough for a slow CI runner.
SETUP_TIMEOUT = 60


def run_setup(dry_run=True):
    """
    Runs the setup shell script in a simulated Linux environment.

    Args:
        dry_run (bool, optional): If True, adds the '--dry-run' flag to the
            setup script to simulate execution without making changes.
            Defaults to True.

    Returns:
        subprocess.CompletedProcess: The result of the executed process,
            containing stdout, stderr, and return code.
    """
    cmd = "OSTYPE=linux-gnu bash setup.sh"
    if dry_run:
        cmd += " --dry-run"
    proc = subprocess.run(
        ["bash", "-c", cmd],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        timeout=SETUP_TIMEOUT,
    )
    return proc


def _make_setup_copy(tmp_path):
    """Copy setup.sh into a temp directory and return (script_dir, script)."""
    script_dir = tmp_path / "repo"
    script_dir.mkdir()
    orig = Path(__file__).resolve().parents[1] / "setup.sh"
    script_copy = script_dir / "setup.sh"
    script_copy.write_text(orig.read_text(), encoding="utf-8")
    script_copy.chmod(0o755)
    return script_dir, script_copy


def test_gtk_typelib_check_present():
    """The script should include a GTK3/GObject typelib check step."""
    proc = run_setup()
    out = proc.stdout
    assert "Step 4: Checking GTK3/GObject typelibs" in out
    assert "GTK3/GObject typelibs" in out
    assert proc.returncode == 0


def test_exit_if_user_declines_install(_monkeypatch, tmp_path):
    """If dependencies are missing and user answers no, the script stops."""
    script_dir, _ = _make_setup_copy(tmp_path)
    (script_dir / "lmstudio-tray-manager").write_text("", encoding="utf-8")
    proc = subprocess.run(
        ["bash", "-c", "echo n | OSTYPE=linux-gnu bash setup.sh"],
        cwd=script_dir,
        capture_output=True,
        text=True,
        check=False,
        timeout=SETUP_TIMEOUT,
    )
    assert proc.returncode != 0
    assert "Setup cancelled" in proc.stdout or "Setup cancelled" in proc.stderr


def test_appimage_detected_dry_run(tmp_path):
    """An AppImage in the script dir is detected and reported in dry-run."""
    script_dir, _ = _make_setup_copy(tmp_path)
    appimage = script_dir / "lmstudio-tray-manager-0.5.3-linux-x86_64.AppImage"
    appimage.write_text("", encoding="utf-8")
    appimage.chmod(0o755)
    proc = subprocess.run(
        ["bash", "-c", "OSTYPE=linux-gnu bash setup.sh --dry-run"],
        cwd=script_dir,
        capture_output=True,
        text=True,
        check=False,
        timeout=SETUP_TIMEOUT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "AppImage release detected" in proc.stdout


def test_appimage_skips_gtk3_check(tmp_path):
    """When an AppImage is present, the GTK3 check step is skipped."""
    script_dir, _ = _make_setup_copy(tmp_path)
    appimage = script_dir / "lmstudio-tray-manager-0.5.3-linux-x86_64.AppImage"
    appimage.write_text("", encoding="utf-8")
    appimage.chmod(0o755)
    proc = subprocess.run(
        ["bash", "-c", "OSTYPE=linux-gnu bash setup.sh --dry-run"],
        cwd=script_dir,
        capture_output=True,
        text=True,
        check=False,
        timeout=SETUP_TIMEOUT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "AppImage bundles its own GTK3" in proc.stdout


def test_appimage_not_executable_dry_run(tmp_path):
    """A non-executable AppImage triggers chmod offer in dry-run mode."""
    script_dir, _ = _make_setup_copy(tmp_path)
    appimage = script_dir / "lmstudio-tray-manager-0.5.3-linux-x86_64.AppImage"
    appimage.write_text("", encoding="utf-8")
    appimage.chmod(0o644)  # not executable
    proc = subprocess.run(
        ["bash", "-c", "OSTYPE=linux-gnu bash setup.sh --dry-run"],
        cwd=script_dir,
        capture_output=True,
        text=True,
        check=False,
        timeout=SETUP_TIMEOUT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Would make it executable" in proc.stdout
    assert "AppImage" in proc.stdout


def test_appimage_not_executable_user_declines(tmp_path):
    """Declining chmod on a non-executable AppImage cancels setup."""
    script_dir, _ = _make_setup_copy(tmp_path)
    appimage = script_dir / "lmstudio-tray-manager-0.5.3-linux-x86_64.AppImage"
    appimage.write_text("", encoding="utf-8")
    appimage.chmod(0o644)  # not executable
    proc = subprocess.run(
        ["bash", "-c", "echo n | OSTYPE=linux-gnu bash setup.sh"],
        cwd=script_dir,
        capture_output=True,
        text=True,
        check=False,
        timeout=SETUP_TIMEOUT,
    )
    assert proc.returncode != 0
    assert "Setup cancelled" in proc.stdout or "Setup cancelled" in proc.stderr


def test_exhausted_stdin_does_not_spin(tmp_path):
    """Stdin running dry mid-run must end setup, not spin on the prompt.

    A single piped "n" is consumed by the earlier desktop-app prompt, so
    ask_yes_no() later reads from an exhausted stdin. It used to treat the
    resulting empty response as invalid input and retry forever - 16k retry
    lines in a few seconds, blocking the whole suite rather than failing one
    test. Feeding no input at all does *not* reproduce this: the earlier
    `read -p` fails first and set -e ends the script, so the piped "n" is
    what makes this test bite.

    The subprocess timeout would catch a true hang; counting the retry
    prompt also pins down a spin that happens to stay under it.
    """
    script_dir, _ = _make_setup_copy(tmp_path)
    (script_dir / "lmstudio-tray-manager").write_text("", encoding="utf-8")
    proc = subprocess.run(
        ["bash", "-c", "echo n | OSTYPE=linux-gnu bash setup.sh"],
        cwd=script_dir,
        capture_output=True,
        text=True,
        check=False,
        timeout=SETUP_TIMEOUT,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0
    # More than a couple of retry prompts is the signature of the old spin.
    assert combined.count("Please answer y or n") < 3
