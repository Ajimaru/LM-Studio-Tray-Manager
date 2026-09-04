"""
Tests for the pinned requirements files.

Two things are checked here:

* the scanner-facing requirements files (requirements.txt and
  requirements-windows.txt) do not contain pip hash specifiers ('--hash') or
  line continuation backslashes ('\\'), as they are intended for scanners and
  should remain hash-free and scanner-friendly;
* the provenance comments ('# <package> (source: ...)') name the same
  package as the pin below them. Dependabot only rewrites the pin, so a
  comment that also stated the version would go stale silently -- these
  comments deliberately describe the artifact shape (sdist/wheel) rather
  than a version, so there is nothing left for an update to desynchronize.
"""

import re
from pathlib import Path

import pytest

REQUIREMENTS_FILES = (
    "requirements.txt",
    "requirements-build.txt",
    "requirements-windows.txt",
)

# Files that must stay parseable by vulnerability scanners, and so carry
# pinned versions but no pip hash specifiers.
HASH_FREE_FILES = ("requirements.txt", "requirements-windows.txt")

# "# setuptools (source: sdist + py3-none-any wheel)"
PROVENANCE_RE = re.compile(
    r"^#\s*(?P<name>[A-Za-z0-9_.-]+)\s*\(source:\s*(?P<source>[^)]*)\)"
)
# "setuptools==83.0.0 \" -- also matches commented-out pins such as the
# optional macOS "# rumps==0.4.0 \" block, which is deliberate.
PIN_RE = re.compile(r"^#?\s*(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s\\]+)")


def _normalize(name):
    """Compare package names the way PEP 503 does."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _provenance_entries(path):
    """Yield (line_no, package, source) tuples.

    A provenance comment describes the first pin that follows it; intervening
    comment lines (for example "# Required by PyInstaller") are skipped.
    """
    pending = None
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        comment = PROVENANCE_RE.match(line)
        if comment:
            pending = (line_no, comment)
            continue
        pin = PIN_RE.match(line)
        if pin and pending:
            comment_line, comment = pending
            if _normalize(comment["name"]) == _normalize(pin["name"]):
                yield (comment_line, comment["name"], comment["source"])
                pending = None


@pytest.mark.parametrize("filename", HASH_FREE_FILES)
def test_scanner_facing_requirements_have_no_hashes(filename):
    """The scanner-facing requirements files carry no pip ``--hash``
    specifiers or continuation backslashes.
    """
    text = Path(filename).read_text(encoding="utf-8")
    assert "--hash" not in text, f"{filename} still contains hash pins"
    assert "\\" not in text, f"{filename} still uses line continuations"


@pytest.mark.parametrize("filename", REQUIREMENTS_FILES)
def test_pins_have_provenance_comments(filename):
    """Every pin is preceded by a "(source: ...)" comment naming it.

    The comment intentionally omits the version (see module docstring), so
    there is nothing for a Dependabot bump to leave stale; this just checks
    the comment itself wasn't dropped.
    """
    entries = list(_provenance_entries(Path(filename)))
    assert entries, f"no provenance comments found in {filename}"
