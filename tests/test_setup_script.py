"""Smoke tests for `setup.sh` logic."""

import subprocess
from pathlib import Path


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
    )
    return proc


def test_gtk_typelib_check_present():
    """The script should include a GTK3/GObject typelib check step."""
    proc = run_setup()
    out = proc.stdout
    assert "Step 4: Checking GTK3/GObject typelibs" in out
    assert "GTK3/GObject typelibs" in out
    assert proc.returncode == 0


def test_exit_if_user_declines_install(_monkeypatch, tmp_path):
    """If dependencies are missing and user answers no, the script stops."""
    script_dir = tmp_path / "repo"
    script_dir.mkdir()
    orig = Path(__file__).resolve().parents[1] / "setup.sh"
    script_copy = script_dir / "setup.sh"
    script_copy.write_text(orig.read_text(), encoding="utf-8")
    (script_dir / "lms").write_text("", encoding="utf-8")
    (script_dir / "lmstudio-tray-manager").write_text("", encoding="utf-8")
    script_copy.chmod(0o755)
    proc = subprocess.run(
        ["bash", "-c", "echo n | OSTYPE=linux-gnu bash setup.sh --dry-run"],
        cwd=script_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "Setup cancelled" in proc.stdout or "Setup cancelled" in proc.stderr
