"""ModelPool: per-model daily budgets, quota errors and fallbacks, without calling Gemini."""

import pytest
from google.genai import errors

from pa_bailar import config, gemini
from pa_bailar.models import Triage


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


class FakeClient:
    def __init__(self):
        self.models = FakeModels({})


@pytest.fixture
def pool(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_USAGE_FILE", tmp_path / "usage.json")
    monkeypatch.setattr(config, "PACING_MARGIN_SECONDS", 0)
    monkeypatch.setattr(gemini.time, "sleep", lambda seconds: None)
    return gemini.ModelPool("unused-key", client=FakeClient())


def with_models(pool, behaviour):
    pool._client.models.behaviour = behaviour
    return pool._client.models


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


def test_no_quota_left_is_its_own_error_not_a_failure(pool):
    pool._used["gemini-3.8-flash"] = config.MODEL_LIMITS["gemini-3.8-flash"].requests_per_day
    with pytest.raises(gemini.QuotaExhaustedError):
        pool.generate(["gemini-3.8-flash"], [], Triage)


@pytest.mark.parametrize("code", [403, 404])
def test_a_model_this_key_cant_use_is_skipped_and_reported(pool, code):
    fake = with_models(pool, {"gemini-3.8-flash": [client_error(code, "not available")], "gemini-3.5-flash": [ANSWER]})
    assert pool.generate(["gemini-3.8-flash", "gemini-3.5-flash"], [], Triage)[1] == "gemini-3.5-flash"
    assert pool.unavailable == {"gemini-3.8-flash"} and not pool.has_budget("gemini-3.8-flash")
    assert fake.calls == ["gemini-3.8-flash", "gemini-3.5-flash"]


def test_models_that_keep_failing_raise_a_plain_extraction_error(pool):
    bad = "not json"
    with_models(pool, {"gemini-3.8-flash": [bad, bad, bad]})
    with pytest.raises(gemini.ExtractionError) as raised:
        pool.generate(["gemini-3.8-flash"], [], Triage)
    assert not isinstance(raised.value, gemini.QuotaExhaustedError)


def test_usage_is_saved_and_counted_per_day(pool):
    with_models(pool, {"gemini-3.5-flash-lite": [ANSWER]})
    pool.generate(["gemini-3.5-flash-lite"], [], Triage)
    saved = gemini.storage.load_gemini_usage()
    assert saved == {"day": gemini.quota_day(), "requests": {"gemini-3.5-flash-lite": 1}}


def test_a_request_gemini_refuses_is_permanent_not_retried(pool):
    fake = with_models(pool, {"gemini-3.8-flash": [client_error(400, "Unable to process input image")]})
    with pytest.raises(gemini.RejectedRequestError):
        pool.generate(("gemini-3.8-flash", "gemini-3.5-flash"), [], Triage)
    assert fake.calls == ["gemini-3.8-flash"]  # no retry, no fallback: the request itself is the problem


def test_server_errors_are_retried(pool):
    busy = errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})
    fake = with_models(pool, {"gemini-3.8-flash": [busy, ANSWER]})
    assert pool.generate(("gemini-3.8-flash",), [], Triage) == (ANSWER, "gemini-3.8-flash")
    assert fake.calls == ["gemini-3.8-flash", "gemini-3.8-flash"]


class Blocked:
    """An answer Gemini blocked (e.g. its safety filter): no parsed JSON, and a finish reason saying why."""

    parsed = None
    prompt_feedback = None

    def __init__(self, reason: str):
        class Reason:
            name = reason

        class Candidate:
            finish_reason = Reason()

        self.candidates = [Candidate()]


def test_a_blocked_answer_is_rejected_at_once_without_retries(pool, monkeypatch):
    fake = with_models(pool, {"gemini-3.8-flash": [Blocked("SAFETY")], "gemini-3.5-flash": [ANSWER]})
    monkeypatch.setattr(fake, "generate_content", blocked_or(fake.generate_content))
    with pytest.raises(gemini.RejectedRequestError, match="SAFETY"):
        pool.generate(["gemini-3.8-flash", "gemini-3.5-flash"], [], Triage)
    assert fake.calls == ["gemini-3.8-flash"]  # not 3 tries on each model: it would be blocked every time


def blocked_or(generate):
    def answer(model, contents, config):
        outcome = generate(model, contents, config)
        return outcome.parsed if isinstance(outcome.parsed, Blocked) else outcome

    return answer


@pytest.mark.parametrize(
    "error",
    [
        client_error(400, "API key not valid. Please pass a valid API key. [reason: API_KEY_INVALID]"),
        client_error(400, "API key expired. Please renew the API key."),
        client_error(401, "Request had invalid authentication credentials."),
    ],
)
def test_a_key_that_doesnt_work_stops_everything_instead_of_rejecting_posts(pool, error):
    with_models(pool, {"gemini-3.8-flash": [error]})
    with pytest.raises(gemini.GeminiKeyError):
        pool.generate(["gemini-3.8-flash"], [], Triage)
    assert not issubclass(gemini.GeminiKeyError, gemini.ExtractionError)  # never recorded as a rejected post


def test_other_request_errors_are_still_a_rejection(pool):
    with_models(pool, {"gemini-3.8-flash": [client_error(400, "Unable to process input image.")]})
    with pytest.raises(gemini.RejectedRequestError):
        pool.generate(["gemini-3.8-flash"], [], Triage)
