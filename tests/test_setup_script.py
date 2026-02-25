"""Smoke tests for `setup.sh` logic."""

import subprocess
import sys
from pathlib import Path


def run_setup(dry_run=True):
    # Execute the shell script in a simulated Linux environment by overriding
    # OSTYPE. We capture stdout for assertions.
    cmd = "OSTYPE=linux-gnu bash setup.sh"
    if dry_run:
        cmd += " --dry-run"
    proc = subprocess.run(
        ["bash", "-c", cmd],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    return proc


def test_gtk_typelib_check_present():
    """The script should include a GTK3/GObject typelib check step."""
    proc = run_setup()
    out = proc.stdout
    assert "Step 4: Checking GTK3/GObject typelibs" in out
    # In dry-run mode the script reports what it *would* do.
    assert "GTK3/GObject typelibs" in out
    assert proc.returncode == 0


def test_exit_if_user_declines_install(monkeypatch, tmp_path):
    """If dependencies are missing and user answers no, the script stops."""
    # simulate a system without the typelibs by forcing python import failure
    # and automatically answering 'n' to the prompt
    # we'll use a minimal shell wrapper to feed 'n' into stdin.
    cmd = (
        "OSTYPE=linux-gnu bash -c '\
read -p \"Install required GTK3 packages now? [y/n]: \" -r ans; \
if [ \"$ans\" = n ]; then exit 1; fi'"
    )
    # simpler: run the real script but pipe 'n' into it; the first check for
    # daemon will stop early though, so we override checks by creating a
    # fake "lms" and "lmstudio-tray-manager" to bypass earlier steps.
    script_dir = tmp_path / "repo"
    script_dir.mkdir()
    # copy setup.sh into temp location
    orig = Path(__file__).resolve().parents[1] / "setup.sh"
    script_copy = script_dir / "setup.sh"
    script_copy.write_text(orig.read_text(), encoding="utf-8")
    # create dummy binaries so earlier checks pass
    (script_dir / "lms").write_text("", encoding="utf-8")
    (script_dir / "lmstudio-tray-manager").write_text("", encoding="utf-8")
    script_copy.chmod(0o755)
    proc = subprocess.run(
        ["bash", "-c", "echo n | OSTYPE=linux-gnu bash setup.sh --dry-run"],
        cwd=script_dir,
        capture_output=True,
        text=True,
    )
    # returncode should be nonzero because user declined installation
    assert proc.returncode != 0
    assert "Setup cancelled" in proc.stdout or "Setup cancelled" in proc.stderr
