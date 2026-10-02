"""ModelPool: per-model daily budgets, quota errors and fallbacks, without calling Gemini."""

import pytest
from google.genai import errors

from pabailar import config, extraction
from pabailar.models import Triage


class FakeModels:
    """Stands in for client.models: answers or raises per model, records the calls."""

    def __init__(self, behaviour: dict[str, list]):
        self.behaviour = behaviour
        self.calls: list[str] = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        outcome = self.behaviour[model].pop(0)
        if isinstance(outcome, Exception):
            raise outcome

        class Response:
            parsed = outcome

        return Response()


def client_error(code: int, message: str) -> errors.ClientError:
    return errors.ClientError(code, {"error": {"code": code, "message": message, "status": "X"}})


@pytest.fixture
def pool(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_USAGE_FILE", tmp_path / "usage.json")
    monkeypatch.setattr(config, "PACING_MARGIN_SECONDS", 0)
    monkeypatch.setattr(extraction.time, "sleep", lambda seconds: None)
    instance = extraction.ModelPool.__new__(extraction.ModelPool)
    instance._day = extraction._quota_day()
    instance._used = extraction.Counter()
    instance._last_call = {}
    instance.requests_this_run = extraction.Counter()
    return instance


def with_models(pool, behaviour):
    fake = FakeModels(behaviour)

    class Client:
        models = fake

    pool._client = Client()
    return fake


ANSWER = Triage(is_event_post=True, reason="ok")


def test_first_model_with_an_answer_wins(pool):
    fake = with_models(pool, {"gemini-3.8-flash": [ANSWER]})
    answer, model = pool.generate(["gemini-3.8-flash", "gemini-3.5-flash"], [], Triage)
    assert (answer, model) == (ANSWER, "gemini-3.8-flash") and fake.calls == ["gemini-3.8-flash"]


def test_daily_quota_error_moves_to_the_next_model_and_marks_the_first_spent(pool):
    daily = client_error(429, "Quota exceeded for metric generate_content_free_tier_requests, limit per day")
    fake = with_models(pool, {"gemini-3.8-flash": [daily], "gemini-3.5-flash": [ANSWER]})
    _, model = pool.generate(["gemini-3.8-flash", "gemini-3.5-flash"], [], Triage)
    assert model == "gemini-3.5-flash"
    assert not pool.has_budget("gemini-3.8-flash")
    assert fake.calls == ["gemini-3.8-flash", "gemini-3.5-flash"]


def test_per_minute_limit_waits_and_retries_the_same_model(pool):
    per_minute = client_error(429, "Quota exceeded for requests per minute")
    fake = with_models(pool, {"gemini-3.8-flash": [per_minute, ANSWER]})
    _, model = pool.generate(["gemini-3.8-flash"], [], Triage)
    assert model == "gemini-3.8-flash" and fake.calls == ["gemini-3.8-flash", "gemini-3.8-flash"]


def test_models_without_budget_are_skipped_without_a_request(pool):
    pool._used["gemini-3.8-flash"] = config.MODEL_LIMITS["gemini-3.8-flash"].requests_per_day
    fake = with_models(pool, {"gemini-3.5-flash": [ANSWER]})
    pool.generate(["gemini-3.8-flash", "gemini-3.5-flash"], [], Triage)
    assert fake.calls == ["gemini-3.5-flash"]


def test_no_model_left_raises_extraction_error(pool):
    with_models(pool, {"gemini-3.8-flash": [client_error(404, "not found")]})
    with pytest.raises(extraction.ExtractionError):
        pool.generate(["gemini-3.8-flash"], [], Triage)


def test_usage_is_saved_and_counted_per_day(pool):
    with_models(pool, {"gemini-3.5-flash-lite": [ANSWER]})
    pool.generate(["gemini-3.5-flash-lite"], [], Triage)
    saved = extraction.storage.load_gemini_usage()
    assert saved == {"day": extraction._quota_day(), "requests": {"gemini-3.5-flash-lite": 1}}
