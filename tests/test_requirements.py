"""
Tests for the pinned requirements files.

Two things are checked here:

* the scanner-facing requirements files (requirements.txt and
  requirements-windows.txt) do not contain pip hash specifiers ('--hash') or
  line continuation backslashes ('\\'), as they are intended for scanners and
  should remain hash-free and scanner-friendly;
* the provenance comments ('# <package> <version> (source: ...)') still match
  the pin below them. Dependabot only rewrites the pin, so those comments go
  stale silently -- in requirements-build.txt they sit directly above the
  ``--hash`` lines and would otherwise document an artifact the hashes no
  longer belong to.
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

# "# setuptools 83.0.0 (source: setuptools-83.0.0.tar.gz + py3-none-any wheel)"
PROVENANCE_RE = re.compile(
    r"^#\s*(?P<name>[A-Za-z0-9_.-]+)\s+(?P<version>[0-9][^\s(]*)\s*\(source:\s*(?P<source>[^)]*)\)"
)
# "setuptools==83.0.0 \" -- also matches commented-out pins such as the
# optional macOS "# rumps==0.4.0 \" block, which is deliberate.
PIN_RE = re.compile(r"^#?\s*(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s\\]+)")


def _normalize(name):
    """Compare package names the way PEP 503 does."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _provenance_entries(path):
    """Yield (line_no, package, comment_version, source, pin_version) tuples.

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
                yield (
                    comment_line,
                    comment["name"],
                    comment["version"],
                    comment["source"],
                    pin["version"],
                )
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
def test_provenance_comments_match_pins(filename):
    """Every "(source: ...)" comment states the version that is pinned below it."""
    path = Path(filename)
    entries = list(_provenance_entries(path))
    assert entries, f"no provenance comments found in {filename}"

    stale = [
        f"{filename}:{line_no}: comment says {name} {comment_version}, pin is {pin_version}"
        for line_no, name, comment_version, _, pin_version in entries
        if comment_version != pin_version
    ]
    assert not stale, "stale provenance comments:\n" + "\n".join(stale)


@pytest.mark.parametrize("filename", REQUIREMENTS_FILES)
def test_provenance_sources_name_the_pinned_version(filename):
    """The artifact named in a "(source: ...)" comment carries the pinned version.

    Guards against half-finished updates where the version in the comment is
    corrected but the file name next to it still refers to the old release.
    """
    mismatched = [
        f"{filename}:{line_no}: source {source!r} does not mention {name} {pin_version}"
        for line_no, name, _, source, pin_version in _provenance_entries(Path(filename))
        if pin_version not in source
    ]
    assert not mismatched, "outdated source artifacts:\n" + "\n".join(mismatched)
