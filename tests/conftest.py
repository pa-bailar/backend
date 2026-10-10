"""Shared test setup: every test writes to a temporary folder, never to the real data/ or state/."""

import pytest

from pa_bailar import config, prefilter


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "FLYERS_DIR", tmp_path / "data" / "flyers")
    monkeypatch.setattr(config, "PREVIEWS_DIR", tmp_path / "data" / "previews")
    monkeypatch.setattr(config, "ARCHIVE_DIR", tmp_path / "data" / "archive")
    monkeypatch.setattr(config, "ARCHIVE_FLYERS_DIR", tmp_path / "data" / "archive" / "flyers")
    monkeypatch.setattr(config, "EVENTS_FILE", tmp_path / "data" / "events.json")
    monkeypatch.setattr(config, "META_FILE", tmp_path / "data" / "meta.json")
    monkeypatch.setattr(config, "PROCESSED_POSTS_FILE", tmp_path / "state" / "processed_posts.json")
    monkeypatch.setattr(config, "ACCOUNT_STATE_FILE", tmp_path / "state" / "accounts.json")
    monkeypatch.setattr(config, "GEMINI_USAGE_FILE", tmp_path / "state" / "gemini_usage.json")
    monkeypatch.setattr(config, "EXTERNAL_USAGE_FILE", tmp_path / "state" / "external_usage.json")
    monkeypatch.setattr(config, "RUN_HISTORY_FILE", tmp_path / "state" / "run_history.json")
    monkeypatch.setattr(config, "HIDDEN_EVENTS_FILE", tmp_path / "state" / "hidden_events.json")
    monkeypatch.setattr(config, "ADMIN_RUNS_FILE", tmp_path / "state" / "admin_runs.json")
    monkeypatch.setattr(config, "ACCOUNTS_FILE", tmp_path / "accounts.txt")
    for provider in config.EXTERNAL_PROVIDERS:  # keys from a local .env: no test may reach Groq or OpenRouter
        monkeypatch.delenv(provider.key_env, raising=False)
    # The pre-filter's OCR: none, as on CI (rapidocr isn't in requirements.txt), whatever this computer has installed;
    # tests of the pre-filter pass their own image text.
    monkeypatch.setattr(prefilter, "image_text", lambda image: None)
    return tmp_path
