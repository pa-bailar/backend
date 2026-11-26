"""Backup models (config.BACKUP_MODEL_TIMEOUTS): used when they answer at once, never in a sweep's way when they
don't (the owner, 26 Nov 2026). Fake clients: no network, no quota."""

import httpx
import pytest
from google.genai import errors

from pa_bailar import config, external, gemini
from pa_bailar.models import PostAnalysis, Triage
from tests.factories import make_image
from tests.test_external import ANALYSIS, GROQ, POST, PUBLISHED, QUOTA, FakeAPI, extractor, flash_out
from tests.test_model_pool import ANSWER, FakeClient, client_error, with_models

BACKUP = "gemini-4-hydrogen"
LITE = "gemini-3.5-flash-lite"
BUSY = errors.ServerError(503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}})


@pytest.fixture
def sleeps(tmp_path, monkeypatch):
    """Every sleep the pool takes (none for real): a backup must never add one."""
    taken: list[float] = []
    monkeypatch.setattr(config, "GEMINI_USAGE_FILE", tmp_path / "usage.json")
    monkeypatch.setattr(config, "PACING_MARGIN_SECONDS", 0)
    monkeypatch.setattr(gemini.time, "sleep", taken.append)
    monkeypatch.setattr(external.time, "sleep", lambda seconds: None)  # the external providers' own pacing
    return taken


@pytest.fixture
def pool(sleeps):
    return gemini.ModelPool("unused-key", client=FakeClient())


def test_a_backup_that_answers_is_used(pool):
    fake = with_models(pool, {BACKUP: [ANSWER]})
    assert pool.generate((BACKUP, LITE), [], Triage) == (ANSWER, BACKUP)
    assert fake.calls == [BACKUP]


@pytest.mark.parametrize(
    "failure",
    [BUSY, httpx.ReadTimeout("timed out"), client_error(400, "unsupported field"), "not json"],
    ids=["busy", "timeout", "refused", "unreadable"],
)
def test_a_failing_backup_costs_one_request_then_is_left_alone_for_the_run(pool, sleeps, failure):
    fake = with_models(pool, {BACKUP: [failure], LITE: [ANSWER, ANSWER, ANSWER]})
    for _ in range(3):
        assert pool.generate((BACKUP, LITE), [], Triage) == (ANSWER, LITE)
    assert fake.calls == [BACKUP, LITE, LITE, LITE]  # one try, then skipped on every later post
    assert sleeps == []  # no backoff, no wait
    assert pool.has_budget(BACKUP)  # its day stays for the next run


def test_a_per_minute_limit_isnt_waited_for(pool, sleeps):
    fake = with_models(pool, {BACKUP: [client_error(429, "requests per minute"), ANSWER], LITE: [ANSWER]})
    assert pool.generate((BACKUP, LITE), [], Triage) == (ANSWER, LITE)
    assert sleeps == [] and fake.calls == [BACKUP, LITE]
    pool._paused_until[BACKUP] = 0.0  # the minute is over
    pool._last_call[BACKUP] = 0.0
    assert pool.generate((BACKUP, LITE), [], Triage) == (ANSWER, BACKUP)


def test_a_backup_not_free_yet_is_passed_over_not_waited_for(pool, sleeps):
    """Its pacing (5 a minute for hydrogen) would sleep 12 s: the next model answers instead."""
    fake = with_models(pool, {BACKUP: [ANSWER, ANSWER], LITE: [ANSWER]})
    assert pool.generate((BACKUP, LITE), [], Triage) == (ANSWER, BACKUP)
    assert pool.generate((BACKUP, LITE), [], Triage) == (ANSWER, LITE)
    assert sleeps == [] and fake.calls == [BACKUP, LITE]


def test_a_backup_gets_its_own_timeout(pool):
    seen = []
    fake = with_models(pool, {BACKUP: [ANSWER]})
    generate = fake.generate_content
    fake.generate_content = lambda model, contents, config: (
        seen.append(config.http_options) or generate(model, contents, config)
    )
    pool.generate((BACKUP,), [], Triage)
    assert seen[0].timeout == config.BACKUP_MODEL_TIMEOUTS[BACKUP] * 1000


def test_a_failed_backup_doesnt_change_what_the_others_decide(pool):
    """The others all out of quota: still "no quota left", not "busy", so the extraction can go on to the external
    providers; and a busy model's error stays busy (the post is retried), not "no quota"."""
    with_models(pool, {LITE: [QUOTA], BACKUP: [BUSY]})
    with pytest.raises(gemini.QuotaExhaustedError):
        pool.generate((LITE, BACKUP), [], Triage)
    with pytest.raises(gemini.QuotaExhaustedError):  # paused for the run: no request, the same answer
        pool.generate((LITE, BACKUP), [], Triage)


def test_a_key_that_doesnt_work_still_stops_everything(pool):
    with_models(pool, {BACKUP: [client_error(400, "API key not valid. [reason: API_KEY_INVALID]")]})
    with pytest.raises(gemini.GeminiKeyError):
        pool.generate((BACKUP, LITE), [], Triage)


def test_the_bake_off_measures_a_backup_as_it_is(sleeps):
    """backups=False: the usual retries, so a busy moment isn't scored as the model's failure."""
    measured = gemini.ModelPool("unused-key", client=FakeClient(), backups=False)
    fake = with_models(measured, {BACKUP: [BUSY, ANSWER]})
    assert measured.generate((BACKUP,), [], Triage) == (ANSWER, BACKUP)
    assert fake.calls == [BACKUP, BACKUP]


def test_lite_out_and_gemma_overloaded_still_reaches_the_external_providers(sleeps, monkeypatch):
    """The real chain's tail: both Flash-Lites out of quota, Google's Gemma busy, the post goes to Groq/OpenRouter
    as it did before Gemma was in the pool."""
    monkeypatch.setattr(config, "PROVISIONAL_MODELS", (LITE, "gemma-4-26b-a4b-it", "gemma-4-31b-it"))
    api = FakeAPI({GROQ: [ANALYSIS]})
    out = extractor(
        flash_out() | {LITE: [QUOTA], "gemma-4-26b-a4b-it": [BUSY], "gemma-4-31b-it": [httpx.ReadTimeout("slow")]}, api
    )
    _, model, provisional = out.extract("academia", POST, PUBLISHED, [make_image()], [])
    assert (model, provisional) == (f"groq:{GROQ}", True)


def test_a_backup_that_answers_is_a_provisional_read(sleeps, monkeypatch):
    monkeypatch.setattr(config, "PROVISIONAL_MODELS", (BACKUP, LITE))
    out = extractor(flash_out() | {BACKUP: [PostAnalysis.model_validate(ANALYSIS)]}, FakeAPI({}))
    assert out.extract("academia", POST, PUBLISHED, [make_image()], [])[1:] == (BACKUP, True)


def test_a_backup_skipped_for_the_run_doesnt_keep_the_sweep_reading(sleeps, monkeypatch):
    """With every other model out and no external key, Gemma's big daily budget alone mustn't say "quota left"."""
    monkeypatch.setattr(config, "PROVISIONAL_MODELS", (LITE, "gemma-4-26b-a4b-it"))
    out = extractor({}, FakeAPI({}), keys={"groq": None, "openrouter": None})
    for model in (*config.TRIAGE_MODELS, *config.EXTRACTION_MODELS, LITE):
        out.pool._used[model] = gemini.daily_budget(model)
    assert out.can_analyze()  # Gemma may still answer
    out.pool._paused_until["gemma-4-26b-a4b-it"] = float("inf")  # it failed this run
    assert not out.can_analyze()


@pytest.mark.skipif(config.LITE_ONLY, reason="lite-only mode has no provisional models")
def test_backups_are_provisional_only_and_have_limits():
    """Never a final read (their reads are re-read by Flash) nor the triage, and each one is in a role."""
    for model in config.BACKUP_MODEL_TIMEOUTS:
        assert model in config.MODEL_LIMITS and model in config.PROVISIONAL_MODELS
        assert model not in config.EXTRACTION_MODELS and model not in config.TRIAGE_MODELS
