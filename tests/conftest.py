"""Shared fixtures: an isolated Job Journal home and SQLite DB per test."""

import pytest


@pytest.fixture
def jj_home(tmp_path, monkeypatch):
    """Point every module-level path at a temp dir and build a fresh schema.

    jj.db and jj.config both import the paths at module load, so each copy is
    patched. Returns the temp home.
    """
    import jj.config as config
    import jj.db as db
    import jj.prompts as prompts

    home = tmp_path / ".job-journal"
    home.mkdir()
    db_path = home / "journal.db"
    monkeypatch.setattr(config, "JJ_HOME", home)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "PROFILE_PATH", home / "profile.yaml")
    monkeypatch.setattr(config, "CONFIG_PATH", home / "config.yaml")
    monkeypatch.setattr(db, "JJ_HOME", home)
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(prompts, "JJ_HOME", home)
    monkeypatch.setattr(prompts, "QUICK_SCREEN_PROMPT_OVERRIDE", home / "quick-screen-prompt.md")
    db.init_database()
    return home
