"""This module provides compatibility fixtures for pytest tests.

It includes an alias fixture `_monkeypatch` that returns the standard
pytest `monkeypatch` fixture, allowing legacy tests to use the expected
fixture name without modification."""

import pytest


@pytest.fixture
def _monkeypatch(monkeypatch):
    """Compatibility alias for tests expecting `_monkeypatch`.

    Many legacy tests refer to `_monkeypatch`.  Provide a simple alias that
    returns the real ``monkeypatch`` fixture so both names work.
    """
    return monkeypatch


@pytest.fixture
def _tmp_path(tmp_path):
    """Alias for pytest's ``tmp_path``.

    A handful of legacy tests expect a fixture called ``_tmp_path``; this
    alias keeps them happy without forcing every test to be rewritten.

    Returns:
        pathlib.Path: the temporary directory provided by pytest.
    """
    return tmp_path
