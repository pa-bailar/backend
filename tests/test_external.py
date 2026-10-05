"""The last resort (external.py) and its place after Gemini (extraction.py), with fake HTTP: no network, no quota."""

import json
from datetime import UTC, datetime

import httpx
import pytest
from google.genai import types

from pa_bailar import config, external, gemini, storage
from pa_bailar.external import ExternalTier, parse_answer, request_parts
from pa_bailar.extraction import EventExtractor
from pa_bailar.models import PostAnalysis, Triage
from pa_bailar.pipeline import Sweep
from pa_bailar.prompts import EXTRACTION_PROMPT
from tests.factories import make_image
from tests.test_model_pool import FakeClient, client_error
from tests.test_sweep import FakeInstagram, post

GROQ = "qwen/qwen3.8-27b"
QWEN = "qwen/qwen3.8-27b:free"
GEMMA = "google/gemma-4-31b-it:free"
ANALYSIS = {"is_event_post": True, "reason": "un social", "events": []}
TRIAGE = {"is_event_post": True, "reason": "un social"}
BOTH_KEYS = {"groq": "groq-test-key", "openrouter": "openrouter-test-key"}


def chat(answer, model: str, tokens: int | None = None) -> httpx.Response:
    """A chat/completions answer whose message is `answer` (a dict as JSON, or text as it is)."""
    content = answer if isinstance(answer, str) else json.dumps(answer)
    payload = {"model": model, "choices": [{"message": {"content": content}}]}
    if tokens is not None:
        payload["usage"] = {"total_tokens": tokens}
    return httpx.Response(200, json=payload)


class FakeAPI:
    """Both providers' endpoint: answers per model in turn (a dict or text: a chat answer; a Response or an
    exception: as it is), and records every request's body."""

    def __init__(self, answers: dict[str, list]):
        self.answers = answers
        self.bodies: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        body["_host"] = request.url.host
        self.bodies.append(body)
        outcome = self.answers[body["model"]].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, httpx.Response):
            return outcome
        return chat(outcome, body["model"])

    @property
    def models(self) -> list[str]:
        return [body["model"] for body in self.bodies]


@pytest.fixture(autouse=True)
def fixed_models(monkeypatch):
    """The tests' own model lists, so changing config.EXTERNAL_PROVIDERS's models (free models come and go) doesn't
    change them: OpenRouter with a structured model then a JSON-mode one."""
    groq, openrouter = config.EXTERNAL_PROVIDERS
    pinned = openrouter.__class__(
        **{**openrouter.__dict__, "models": (config.ExternalModel(QWEN, structured=True), config.ExternalModel(GEMMA))}
    )
    monkeypatch.setattr(config, "EXTERNAL_PROVIDERS", (groq, pinned))


@pytest.fixture
def sleeps(monkeypatch):
    """Every pause the tier takes (none for real), with pacing margins off."""
    taken: list[float] = []
    monkeypatch.setattr(config, "PACING_MARGIN_SECONDS", 0)
    monkeypatch.setattr(external.time, "sleep", taken.append)
    monkeypatch.setattr(gemini.time, "sleep", lambda seconds: None)
    return taken


def tier(api: FakeAPI, keys=BOTH_KEYS) -> ExternalTier:
    return ExternalTier(keys=dict(keys), http=httpx.Client(transport=httpx.MockTransport(api)))


def contents(images: int = 1, text: str = "Lee el post") -> list[types.PartUnionDict]:
    parts: list[types.PartUnionDict] = []
    for index in range(images):
        parts += [f"Image {index}:", types.Part.from_bytes(data=make_image(), mime_type="image/jpeg")]
    return [*parts, text]


# ---------- the order of providers and models ----------


def test_groq_first_then_openrouter_and_the_model_is_recorded_with_its_provider(sleeps):
    api = FakeAPI({GROQ: [ANALYSIS]})
    answer, model = tier(api).generate(contents(), PostAnalysis)
    assert answer.reason == "un social" and model == f"groq:{GROQ}"
    assert api.bodies[0]["_host"] == "api.groq.com"


def test_a_provider_without_its_key_is_skipped_and_without_any_key_nothing_is_called(sleeps):
    api = FakeAPI({QWEN: [ANALYSIS]})
    _, model = tier(api, {"groq": None, "openrouter": "k"}).generate(contents(), PostAnalysis)
    assert model == f"openrouter:{QWEN}" and api.models == [QWEN]

    nothing = FakeAPI({})
    no_keys = tier(nothing, {"groq": None, "openrouter": None})
    assert not no_keys.available()
    with pytest.raises(gemini.QuotaExhaustedError):
        no_keys.generate(contents(), PostAnalysis)
    assert nothing.bodies == []


def test_the_keys_come_from_the_environment(monkeypatch):
    assert not ExternalTier().available()  # conftest removes any local key
    monkeypatch.setenv("GROQ_API_KEY", "from-env")
    assert ExternalTier().available()


def test_a_busy_model_goes_on_to_the_next_without_waiting_and_then_gives_up(sleeps):
    upstream = httpx.Response(429, json={"error": {"message": "qwen is temporarily rate-limited upstream"}})
    api = FakeAPI(
        {
            GROQ: [httpx.Response(503, text="over capacity")],
            QWEN: [upstream],
            GEMMA: [httpx.ReadTimeout("slow")],
        }
    )
    with pytest.raises(gemini.ExtractionError) as caught:
        tier(api).generate(contents(), PostAnalysis)
    assert not isinstance(caught.value, gemini.QuotaExhaustedError)  # failed, not out of quota
    assert api.models == [GROQ, QWEN, GEMMA] and sleeps == []


def test_an_answer_that_isnt_the_schemas_json_is_the_next_models_turn(sleeps):
    api = FakeAPI({GROQ: ["Claro, aquí tienes el evento"], QWEN: [{"is_event_post": "maybe"}], GEMMA: [ANALYSIS]})
    _, model = tier(api).generate(contents(), PostAnalysis)
    assert model == f"openrouter:{GEMMA}"


def test_answers_in_fences_after_thinking_are_read():
    text = '<think>{"not": "this"}</think>\n```json\n{"is_event_post": false, "reason": "no"}\n```'
    assert parse_answer(text, Triage) == Triage(is_event_post=False, reason="no")
    with pytest.raises(external.NoAnswerError) as caught:
        parse_answer("[1, 2]", Triage)
    assert caught.value.kind == "invalid"


# ---------- OpenRouter's request ----------


def test_openrouter_asks_structured_models_with_the_schema_and_require_parameters(sleeps):
    api = FakeAPI({QWEN: [httpx.Response(500)], GEMMA: [ANALYSIS]})
    tier(api, {"groq": None, "openrouter": "k"}).generate(contents(), PostAnalysis)
    structured, plain = api.bodies
    assert structured["response_format"]["type"] == "json_schema"
    assert structured["response_format"]["json_schema"]["strict"] is True
    assert structured["provider"] == {"require_parameters": True}
    assert plain["response_format"] == {"type": "json_object"} and "provider" not in plain
    assert "JSON schema" in plain["messages"][0]["content"][-1]["text"]  # the schema goes in the prompt
    assert "JSON schema" not in structured["messages"][0]["content"][-1]["text"]


def test_openrouter_names_models_of_the_same_mode_in_one_request(sleeps, monkeypatch):
    models = (config.ExternalModel("a:free"), config.ExternalModel("b:free"), config.ExternalModel("c:free"))
    provider = config.EXTERNAL_PROVIDERS[1]
    monkeypatch.setattr(config, "EXTERNAL_PROVIDERS", (provider.__class__(**{**provider.__dict__, "models": models}),))
    api = FakeAPI({"a:free": [chat(ANALYSIS, "b:free")]})  # OpenRouter's own fallback answered with b
    _, model = ExternalTier(keys={"openrouter": "k"}, http=httpx.Client(transport=httpx.MockTransport(api))).generate(
        contents(), PostAnalysis
    )
    assert api.bodies[0]["models"] == ["a:free", "b:free", "c:free"]
    assert model == "openrouter:b:free"


# ---------- Groq's limits ----------


def test_groq_takes_at_most_three_images_with_their_labels():
    groq = config.EXTERNAL_PROVIDERS[0]
    roomy = groq.__class__(**{**groq.__dict__, "tokens_per_minute": 100_000})
    parts, estimate = request_parts(contents(images=5), Triage, False, roomy)
    assert [part["type"] for part in parts].count("image_url") == 3
    assert [part["text"] for part in parts if part["type"] == "text"][:3] == ["Image 0:", "Image 1:", "Image 2:"]
    assert not any(part.get("text") in ("Image 3:", "Image 4:") for part in parts)
    assert estimate >= 3 * config.EXTERNAL_IMAGE_TOKENS + config.EXTERNAL_ANSWER_TOKENS


def test_groq_sends_only_the_images_that_fit_in_a_minutes_tokens():
    groq = config.EXTERNAL_PROVIDERS[0]
    long_prompt = "x" * 12_000  # 3,000 tokens, and the schema's: with the answer, room for one image of 2,048
    parts, estimate = request_parts(contents(images=3, text=long_prompt), PostAnalysis, False, groq)
    assert [part["type"] for part in parts].count("image_url") == 1
    assert estimate <= groq.tokens_per_minute
    with pytest.raises(external.NoAnswerError) as caught:
        request_parts(contents(images=1, text="x" * 40_000), PostAnalysis, False, groq)
    assert caught.value.kind == "skipped"


@pytest.fixture
def clock(sleeps, monkeypatch):
    """A fake time.monotonic() that the tier's pauses move forward (for every module: they share `time`)."""
    now = [1000.0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(external.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(external.time, "sleep", sleep)
    return now


def test_groq_waits_for_its_minute_of_tokens_when_the_post_has_time_for_it(clock, sleeps):
    api = FakeAPI({GROQ: [chat(TRIAGE, GROQ, tokens=7_000), TRIAGE], QWEN: [TRIAGE]})
    pool = tier(api)
    assert pool.generate(contents(), Triage)[1] == f"groq:{GROQ}"
    clock[0] += 5  # 7,000 of Groq's 8,000 tokens used 5 s ago: the next request fits in 55 s
    assert pool.generate(contents(), Triage)[1] == f"groq:{GROQ}"
    assert sleeps == [55.0] and api.models == [GROQ, GROQ]


def test_no_request_or_wait_that_wouldnt_end_before_the_deadline(clock, sleeps):
    api = FakeAPI({GROQ: [chat(TRIAGE, GROQ, tokens=7_000)], QWEN: [TRIAGE]})
    pool = tier(api)
    pool.generate(contents(), Triage)
    clock[0] += 5
    # 55 s for Groq's tokens and a whole timeout (60 s) don't fit in 100 s: OpenRouter, which needs no wait.
    assert pool.generate(contents(), Triage, deadline=clock[0] + 100)[1] == f"openrouter:{QWEN}"
    assert pool.outcomes[f"groq:{GROQ}"] == {"answered": 1, "skipped": 1} and sleeps == []
    with pytest.raises(gemini.QuotaExhaustedError):  # not even OpenRouter's timeout fits: nothing is asked
        pool.generate(contents(), Triage, deadline=clock[0] + 30)
    assert api.models == [GROQ, QWEN]


def test_one_post_spends_at_most_its_share_of_time_on_the_last_resort(clock, sleeps, monkeypatch):
    monkeypatch.setattr(config, "EXTERNAL_MAX_SECONDS_PER_POST", 100)
    api = FakeAPI({GROQ: [chat(TRIAGE, GROQ, tokens=7_000)], QWEN: [TRIAGE]})
    pool = tier(api)
    pool.generate(contents(), Triage)
    clock[0] += 5
    assert pool.generate(contents(), Triage)[1] == f"openrouter:{QWEN}"  # Groq's 55 + 60 s are over the 100


def test_a_provider_without_tokens_for_a_request_today_isnt_available(sleeps):
    groq = config.EXTERNAL_PROVIDERS[0]
    assert groq.daily_tokens is not None
    nearly = groq.daily_tokens - config.EXTERNAL_MIN_REQUEST_TOKENS + 1
    storage.save_external_usage({"day": external.usage_day(), "providers": {"groq": {"tokens": nearly}}})
    pool = tier(FakeAPI({}), {"groq": "k", "openrouter": None})
    assert not pool.has_budget(groq) and not pool.available()  # no download for a post it would skip


def test_the_minimum_request_is_below_any_extraction_the_sweep_sends():
    """EXTERNAL_MIN_REQUEST_TOKENS stays a floor: an extraction without images and with an empty caption."""
    prompt = EXTRACTION_PROMPT.format(
        account="a", published="2026-10-01", today="2026-10-01", caption="", account_rules="", known_events="(none)"
    )
    for provider in config.EXTERNAL_PROVIDERS:
        for model in provider.models if provider.daily_tokens is not None else ():
            _, estimate = request_parts([prompt], PostAnalysis, model.structured, provider)
            assert estimate >= config.EXTERNAL_MIN_REQUEST_TOKENS


def test_a_429_for_groqs_tokens_skips_without_counting_as_a_failure(sleeps, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(external.time, "monotonic", lambda: clock[0])
    tpm = httpx.Response(429, json={"error": {"message": "Rate limit reached on tokens per minute (TPM)"}})
    api = FakeAPI({GROQ: [tpm, tpm, tpm], QWEN: [TRIAGE, TRIAGE, TRIAGE]})
    pool = tier(api)
    for _ in range(3):
        pool.generate(contents(), Triage)
        clock[0] += 61
    assert f"groq:{GROQ}" not in pool.quarantined and api.models.count(GROQ) == 3


# ---------- per run: quarantine and turning off ----------


def test_a_model_failing_twice_is_set_aside_for_the_run(sleeps):
    api = FakeAPI({GROQ: [httpx.Response(502), "not json"], QWEN: [TRIAGE, TRIAGE, TRIAGE]})
    pool = tier(api)
    for _ in range(3):
        assert pool.generate(contents(), Triage)[1] == f"openrouter:{QWEN}"
    assert api.models == [GROQ, QWEN, GROQ, QWEN, QWEN]  # the third post doesn't ask Groq
    assert pool.report().quarantined == [f"groq:{GROQ}"]
    assert pool.report().outcomes[f"groq:{GROQ}"] == {"busy": 1, "invalid": 1}


def test_a_model_no_longer_free_is_set_aside_at_once(sleeps):
    gone = httpx.Response(404, json={"error": {"message": "This model is unavailable for free.", "code": 404}})
    api = FakeAPI({QWEN: [gone], GEMMA: [TRIAGE, TRIAGE]})
    pool = tier(api, {"groq": None, "openrouter": "k"})
    pool.generate(contents(), Triage)
    pool.generate(contents(), Triage)
    assert api.models == [QWEN, GEMMA, GEMMA]
    assert pool.report().outcomes[f"openrouter:{QWEN}"] == {"unavailable": 1}


@pytest.mark.parametrize("status", [401, 402, 403])
def test_a_refused_key_or_missing_credit_turns_the_provider_off_for_the_run(sleeps, status):
    api = FakeAPI({GROQ: [httpx.Response(status, text="no")], QWEN: [TRIAGE, TRIAGE]})
    pool = tier(api)
    pool.generate(contents(), Triage)
    pool.generate(contents(), Triage)
    assert api.models == [GROQ, QWEN, QWEN]
    assert str(status) in pool.report().problems["groq"]


# ---------- daily budgets ----------


def test_the_daily_budget_is_shared_by_the_days_runs_and_spent_means_not_asked(sleeps):
    openrouter = config.EXTERNAL_PROVIDERS[1]
    storage.save_external_usage(
        {"day": external.usage_day(), "providers": {"openrouter": {"requests": openrouter.daily_requests}}}
    )
    api = FakeAPI({})
    pool = tier(api, {"groq": None, "openrouter": "k"})
    assert not pool.available()
    with pytest.raises(gemini.QuotaExhaustedError):
        pool.generate(contents(), Triage)
    assert api.bodies == []


def test_requests_and_answers_are_saved_for_the_next_run(sleeps):
    api = FakeAPI({GROQ: [chat(TRIAGE, GROQ, tokens=3_000)]})
    tier(api).generate(contents(), Triage)
    saved = storage.load_external_usage()
    assert saved["day"] == external.usage_day()
    assert saved["providers"]["groq"] == {"requests": 1, "tokens": 3_000, "answered": {GROQ: 1}}
    assert ExternalTier(keys=BOTH_KEYS).usage("groq").requests == 1  # a later run on the same day


def test_the_providers_own_daily_limit_spends_it_for_the_day(sleeps):
    daily = httpx.Response(429, json={"error": {"message": "Rate limit exceeded: free-models-per-day"}})
    api = FakeAPI({QWEN: [daily]})
    pool = tier(api, {"groq": None, "openrouter": "k"})
    with pytest.raises(gemini.QuotaExhaustedError):
        pool.generate(contents(), Triage)
    assert api.models == [QWEN]  # gemma isn't asked: the limit is the account's
    assert not pool.available()


# ---------- after Gemini (extraction.py) ----------


QUOTA = client_error(429, "Quota exceeded: requests per day")
POST = {"id": "p1", "timestamp": "2026-10-01T12:00:00+0000", "permalink": "x", "media_type": "IMAGE", "caption": "c"}
PUBLISHED = datetime(2026, 10, 1, 12, tzinfo=UTC)


def extractor(gemini_answers: dict[str, list], api: FakeAPI, keys=BOTH_KEYS) -> EventExtractor:
    client = FakeClient()
    client.models.behaviour = gemini_answers
    made = EventExtractor("unused-key", external=tier(api, keys))
    made.pool = gemini.ModelPool("unused-key", client=client)
    made.pool.deadline = made.deadline
    return made


def flash_out() -> dict[str, list]:
    return {"gemini-3.8-flash": [QUOTA], "gemini-3.5-flash": [QUOTA]}


def test_flash_out_then_lite_then_the_last_resort_all_provisional(sleeps):
    lite = PostAnalysis.model_validate(ANALYSIS)
    with_lite = extractor(flash_out() | {"gemini-3.5-flash-lite": [lite]}, FakeAPI({}))
    assert with_lite.extract("academia", POST, PUBLISHED, [make_image()], [])[1:] == ("gemini-3.5-flash-lite", True)

    api = FakeAPI({GROQ: [ANALYSIS]})
    lite_out = extractor(flash_out() | {"gemini-3.5-flash-lite": [QUOTA]}, api)
    analysis, model, provisional = lite_out.extract("academia", POST, PUBLISHED, [make_image()], [])
    assert (model, provisional) == (f"groq:{GROQ}", True)
    assert lite_out.requests_this_run()["groq"] == 1


def test_an_upgrade_never_goes_to_the_last_resort(sleeps):
    api = FakeAPI({})
    upgrading = extractor(flash_out(), api)
    with pytest.raises(gemini.QuotaExhaustedError):
        upgrading.extract("academia", POST, PUBLISHED, [make_image()], [], allow_provisional=False)
    assert api.bodies == []


def test_when_the_last_resort_fails_too_the_post_waits_as_without_it(sleeps):
    api = FakeAPI({GROQ: [httpx.Response(500)], QWEN: [httpx.Response(500)], GEMMA: [httpx.Response(500)]})
    out = extractor(flash_out() | {"gemini-3.5-flash-lite": [QUOTA]}, api)
    with pytest.raises(gemini.QuotaExhaustedError):  # Gemini's error: the post waits, it isn't an error
        out.extract("academia", POST, PUBLISHED, [make_image()], [])


def test_without_keys_gemini_running_out_is_as_before(sleeps):
    api = FakeAPI({})
    out = extractor(flash_out() | {"gemini-3.5-flash-lite": [QUOTA]}, api, keys={"groq": None, "openrouter": None})
    with pytest.raises(gemini.QuotaExhaustedError):
        out.extract("academia", POST, PUBLISHED, [make_image()], [])
    assert api.bodies == [] and not out.can_analyze()


def test_the_triage_never_goes_to_the_last_resort(sleeps):
    """A Groq triage and a Groq extraction of the same post don't fit in Groq's 8,000 tokens a minute, and a weaker
    model's "no" would be final: with Flash-Lite out, the sweep sends the post to the extraction (test_sweep.py)."""
    api = FakeAPI({})
    out = extractor({"gemini-3.5-flash-lite": [QUOTA]}, api)
    with pytest.raises(gemini.QuotaExhaustedError):
        out.triage("academia", POST, PUBLISHED, [make_image()])
    assert api.bodies == []


BUSY = gemini.errors.ServerError(503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}})


@pytest.mark.parametrize(
    "flash_error",
    [BUSY, client_error(400, "Request contains an invalid argument")],
    ids=["busy", "rejected"],
)
def test_only_flash_out_of_quota_reaches_the_last_resort(sleeps, flash_error):
    api = FakeAPI({GROQ: [ANALYSIS]})
    failing = [flash_error] * gemini.ATTEMPTS_PER_MODEL
    out = extractor(
        {"gemini-3.8-flash": list(failing), "gemini-3.5-flash": list(failing), "gemini-3.5-flash-lite": [QUOTA]}, api
    )
    with pytest.raises(gemini.QuotaExhaustedError):  # Flash-Lite out: the post waits for Gemini, as before
        out.extract("academia", POST, PUBLISHED, [make_image()], [])
    assert api.bodies == []


def test_no_request_starts_after_the_runs_time_budget(clock, sleeps):
    api = FakeAPI({GROQ: [ANALYSIS]})
    out = extractor(flash_out() | {"gemini-3.5-flash-lite": [QUOTA]}, api)
    assert out.deadline == clock[0] + config.MAX_RUN_MINUTES * 60
    clock[0] = out.deadline
    with pytest.raises(gemini.OutOfTimeError):  # a kind of QuotaExhaustedError: the post waits, not an error
        out.extract("academia", POST, PUBLISHED, [make_image()], [])
    assert out.pool._client.models.calls == [] and api.bodies == []


def test_the_last_resort_doesnt_start_past_the_deadline_either(clock, sleeps):
    api = FakeAPI({GROQ: [ANALYSIS]})
    out = extractor(flash_out() | {"gemini-3.5-flash-lite": [QUOTA]}, api)
    out.deadline = out.pool.deadline = clock[0] + 30  # Gemini may start, a last-resort request wouldn't end in time
    with pytest.raises(gemini.QuotaExhaustedError):
        out.extract("academia", POST, PUBLISHED, [make_image()], [])
    assert api.bodies == [] and out.external.outcomes[f"groq:{GROQ}"] == {"skipped": 1}


def test_with_gemini_out_the_sweep_extracts_with_groq_one_post_a_minute_and_flash_lite_screens_its_no_later(
    clock, sleeps, monkeypatch
):
    """Review finding: Groq's triage (~4,100 tokens) and extraction (~7,250) of the same post didn't fit in its
    8,000 tokens a minute, so nothing was ever extracted. Now the extraction alone, waiting for the minute's tokens;
    its "no" is provisional, and Flash-Lite's triage screens it before Flash is spent on it."""
    config.ACCOUNTS_FILE.write_text("academia\n", encoding="utf-8")
    monkeypatch.setattr("pa_bailar.pipeline.common.download_image", lambda url: make_image())
    posts = [{**post("p1", days_ago=2), "caption": "Social de salsa"}, {**post("p2", days_ago=1), "caption": "Hoy"}]
    instagram = FakeInstagram({"academia": posts})
    no_event = {"is_event_post": False, "reason": "un meme", "events": []}
    api = FakeAPI({GROQ: [no_event, no_event]})
    spent = {model: limit.requests_per_day for model, limit in config.MODEL_LIMITS.items()}
    storage.save_gemini_usage({"day": gemini.quota_day(), "requests": spent})  # today's Gemini quotas are used
    out = extractor({}, api, keys={"groq": "k", "openrouter": None})
    Sweep(lookback_days=7, instagram=instagram, extractor=out, all_accounts=True).run()

    records = storage.load_processed_posts()
    assert [(records[p].model, records[p].provisional) for p in ("p1", "p2")] == [(f"groq:{GROQ}", True)] * 2
    assert len(api.bodies) == 2 and all("Image 0:" in str(body) for body in api.bodies)  # extractions, no triage
    assert any(pause > 50 for pause in sleeps)  # the second waited for the first to leave Groq's minute

    storage.save_gemini_usage({})  # the next quota day: Flash-Lite screens Groq's "no" first
    lite = gemini.ModelPool("unused-key", client=FakeClient())
    lite._client.models.behaviour = {
        "gemini-3.5-flash-lite": [Triage(is_event_post=True, reason="social"), Triage(is_event_post=False, reason="x")],
        "gemini-3.8-flash": [PostAnalysis.model_validate(ANALYSIS)],
    }
    again = extractor({}, FakeAPI({}))
    again.pool = lite
    Sweep(lookback_days=7, instagram=instagram, extractor=again, all_accounts=True).run()
    records = storage.load_processed_posts()
    assert (records["p1"].model, records["p1"].provisional) == ("gemini-3.8-flash", False)
    assert (records["p2"].model, records["p2"].provisional) == ("gemini-3.5-flash-lite", False)
    assert lite._client.models.calls.count("gemini-3.8-flash") == 1  # Flash only for the post Flash-Lite let through


def test_lite_only_mode_keeps_the_last_resort_after_flash_lite(sleeps, monkeypatch):
    monkeypatch.setattr(config, "EXTRACTION_MODELS", ("gemini-3.5-flash-lite",))
    monkeypatch.setattr(config, "PROVISIONAL_MODELS", ())
    api = FakeAPI({GROQ: [ANALYSIS]})
    out = extractor({"gemini-3.5-flash-lite": [QUOTA]}, api)
    assert out.extract("academia", POST, PUBLISHED, [make_image()], [])[1:] == (f"groq:{GROQ}", True)


def test_a_story_never_goes_to_the_last_resort(sleeps):
    api = FakeAPI({})
    out = extractor(flash_out() | {"gemini-3.5-flash-lite": [QUOTA]}, api)
    with pytest.raises(gemini.QuotaExhaustedError):
        out.extract_story([make_image()], PUBLISHED, "academia", None, [])
    assert api.bodies == []  # a story is never read again: a last-resort reading would stay
