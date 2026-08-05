"""This module provides compatibility fixtures for pytest tests.

It includes an alias fixture `_monkeypatch` that returns the standard
pytest `monkeypatch` fixture, allowing legacy tests to use the expected
fixture name without modification."""

import os

import pytest


@pytest.fixture(autouse=True)
def _block_real_process_signals(monkeypatch):
    """Stop tests from signalling processes outside the test session.

    ``kill_existing_instances()`` resolves targets with
    ``pgrep -f lmstudio_tray.py``. During a test run that pattern also
    matches pytest's own command line (``pytest tests/test_lmstudio_tray.py``)
    as well as any tray app the developer happens to be running, so a test
    reaching the real ``os.kill`` terminates the test session itself - the
    run dies with exit code 144 partway through, and a locally running app
    disappears with it.

    Tests that care about signalling still override ``os.kill`` themselves;
    this fixture only guarantees that an unmocked path cannot escape.
    """
    def blocked_kill(pid, sig):
        """Swallow the signal instead of delivering it to a real process."""
        _ = (pid, sig)
        return None

    monkeypatch.setattr(os, "kill", blocked_kill)
    yield


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
