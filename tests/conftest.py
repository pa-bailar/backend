"""Shared test setup: every test writes to a temporary folder, never to the real data/ or state/."""

import pytest

from pa_bailar import config


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "FLYERS_DIR", tmp_path / "data" / "flyers")
    monkeypatch.setattr(config, "PREVIEWS_DIR", tmp_path / "data" / "previews")
    monkeypatch.setattr(config, "EVENTS_FILE", tmp_path / "data" / "events.json")
    monkeypatch.setattr(config, "META_FILE", tmp_path / "data" / "meta.json")
    monkeypatch.setattr(config, "PROCESSED_POSTS_FILE", tmp_path / "state" / "processed_posts.json")
    monkeypatch.setattr(config, "ACCOUNT_STATE_FILE", tmp_path / "state" / "accounts.json")
    monkeypatch.setattr(config, "GEMINI_USAGE_FILE", tmp_path / "state" / "gemini_usage.json")
    monkeypatch.setattr(config, "RUN_HISTORY_FILE", tmp_path / "state" / "run_history.json")
    monkeypatch.setattr(config, "HIDDEN_EVENTS_FILE", tmp_path / "state" / "hidden_events.json")
    monkeypatch.setattr(config, "ACCOUNTS_FILE", tmp_path / "accounts.txt")
    return tmp_path
