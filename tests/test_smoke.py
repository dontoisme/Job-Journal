"""Smoke tests: import the package and exercise pure, data-free helpers.

These intentionally avoid touching ~/.job-journal, the SQLite DB, Google/Gmail,
or the network so they run anywhere (including CI) without user configuration.
They exist to (a) keep CI honest that the package imports and core invariants
hold, and (b) give contributors a place to grow real coverage.
"""

import importlib


def test_package_imports():
    """Core modules import without side effects (no DB/network required)."""
    for mod in ("jj", "jj.db", "jj.config", "jj.cli", "jj.notifier"):
        assert importlib.import_module(mod) is not None


def test_cli_app_constructed():
    """The Typer CLI app is built and exposes registered sub-apps."""
    from jj.cli import app

    assert app is not None
    # Typer keeps registered sub-apps here; the project wires several.
    assert len(app.registered_groups) >= 1


def test_status_constants_are_consistent():
    """Status sets are disjoint where expected and ALL is their union."""
    from jj import db

    assert db.ACTIVE_STATUSES.isdisjoint(db.TERMINAL_STATUSES)
    assert db.ACTIVE_STATUSES.isdisjoint(db.ARCHIVE_STATUSES)
    assert db.ALL_STATUSES == db.ACTIVE_STATUSES | db.TERMINAL_STATUSES
    # Every active and terminal status has a defined progression order.
    for status in db.ACTIVE_STATUSES | db.TERMINAL_STATUSES:
        assert status in db.STATUS_ORDER


def test_resolution_to_status_targets_are_real():
    """Email-resolution mappings point at known statuses."""
    from jj import db

    for status in db.RESOLUTION_TO_STATUS.values():
        assert status in db.ALL_STATUSES


def test_score_label_tiers():
    """_score_label returns the expected tier text per score_type/threshold."""
    from jj.notifier import _score_label

    assert _score_label("Corpus Fit", 80) == "Strong fits (80+)"
    assert _score_label("Corpus Fit", 65) == "Good fits (65+)"
    assert _score_label("Corpus Fit", 50) == "Moderate fits (50+)"
    assert _score_label("Title Fit", 80) == "Strong title match (80+)"
    assert _score_label("Title Fit", 50) == "Good title match (50+)"
