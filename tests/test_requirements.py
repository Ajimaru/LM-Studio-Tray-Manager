"""
Test to ensure that the top-level requirements.txt file does not contain
pip hash specifiers ('--hash') or line continuation backslashes ('\\'),
as it is intended for scanners and should remain simple and unpinned.
"""
from pathlib import Path


def test_requirements_txt_no_hashes():
    """The top-level requirements.txt is intended for scanners and should
    not contain pip ``--hash`` specifiers or continuation backslashes.
    """
    text = Path("requirements.txt").read_text(encoding="utf-8")
    assert "--hash" not in text, "requirements.txt still contains hash pins"
    assert "\\" not in text, "requirements.txt still uses line continuations"
