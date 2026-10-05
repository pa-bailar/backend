"""`admin bakeoff`: picking posts, running models on them (fake), scoring against Flash, OpenRouter's free list."""

from datetime import datetime

import httpx

from pa_bailar import bakeoff, config, external, health, status, why
from pa_bailar.external import ExternalReport, ExternalTier
from pa_bailar.models import PostAnalysis
from pa_bailar.pipeline import RunStats
from tests.factories import DETAILS, make_image
from tests.test_admin_tools import LINK, record, state
from tests.test_external import ANALYSIS, GROQ, FakeAPI, chat
from tests.test_health import TODAY, recent, stats_with
from tests.test_health import check as health_check
from tests.test_health import record as run_record


def flash_event(event_id: str, post_id: str, **details) -> dict:
    media = {"post_id": post_id, "media_type": "IMAGE", "flyer": f"flyers/{post_id}-0.webp", "caption": "c"}
    media |= {"permalink": f"https://www.instagram.com/p/{post_id}/", "published": "2026-10-01T12:00:00+0000"}
    return {**DETAILS, "date": "2026-11-13", "id": event_id, "account": "academia", "media": [media], **details}


def test_candidates_are_posts_flash_read_alone_with_a_flyer(tmp_path):
    (tmp_path / "flyers").mkdir()
    for post_id in ("a", "b", "c", "d"):
        (tmp_path / "flyers" / f"{post_id}-0.webp").write_bytes(b"x")
    merged = flash_event("e3", "c")
    merged["media"].append({**merged["media"][0], "post_id": "other"})
    events = [flash_event("e1", "a"), flash_event("e2", "b"), merged, flash_event("e4", "d"), flash_event("e5", "z")]
    processed = {
        "a": {"model": "gemini-3.8-flash", "processed_at": "2026-10-01T10:00:00-05:00"},
        "b": {"model": "gemini-3.5-flash-lite", "provisional": True, "processed_at": "2026-10-01T10:00:00-05:00"},
        "c": {"model": "gemini-3.8-flash", "processed_at": "2026-10-01T10:00:00-05:00"},
        "d": {"model": "groq:qwen/qwen3.8-27b", "provisional": True, "processed_at": "2026-10-01T10:00:00-05:00"},
        "z": {"model": "gemini-3.8-flash", "processed_at": "2026-10-01T10:00:00-05:00"},  # no flyer on disk
    }
    found = bakeoff.candidates(events, processed, tmp_path)
    assert [item["post_id"] for item in found] == ["a"]
    assert found[0]["events"][0]["id"] == "e1"


def test_a_third_of_the_picks_have_hard_dates_and_the_same_data_gives_the_same_picks():
    items = [{"post_id": str(n), "events": [{"end_date": "x" if n < 4 else None}]} for n in range(20)]
    picked = bakeoff.pick(items, 9)
    assert len(picked) == 9 and [item["post_id"] for item in picked[:3]] == ["0", "1", "2"]
    assert bakeoff.pick(items, 9) == picked


def test_comparing_field_by_field():
    flash = {**DETAILS, "title": "Gran social de salsa", "venue": "Casa Latina", "start_time": "20:00", "date": "d"}
    flash["prices"] = [{"amount_cop": 20000}]
    same = {**flash, "title": "Social de salsa", "venue": "La Casa Latina", "start_time": "20:00:00"}
    other = {**flash, "title": "Fiesta", "venue": None, "start_time": "21:00", "prices": [], "styles": ["bachata"]}
    assert all(bakeoff.compare(flash, same).values())
    differences = {name for name, ok in bakeoff.compare(flash, other).items() if not ok}
    assert differences == {"title", "venue", "start_time", "prices", "styles"}


def test_scoring_counts_found_missed_extra_and_errors():
    picks = [
        {"post_id": "a", "events": [flash_event("e1", "a"), flash_event("e2", "a", date="2026-11-20")]},
        {"post_id": "b", "events": [flash_event("e3", "b")]},
    ]
    answer = {"events": [flash_event("x", "a"), flash_event("y", "a", date="2026-12-01")]}
    cache = {"a": {"answer": answer, "seconds": 10}, "b": {"error": "busy"}}
    result = bakeoff.score(picks, cache)
    assert (result.found, result.missed, result.extra, result.errors) == (1, 1, 0, 1)
    assert result.fields["date"] == [1, 1] and result.average_seconds == 10
    assert "found 1, missed 1" in bakeoff.score_text("groq:qwen/qwen3.8-27b", result)


def test_running_a_model_caches_answers_and_retries_only_failures(tmp_path):
    (tmp_path / "flyers").mkdir()
    (tmp_path / "flyers" / "a-0.webp").write_bytes(make_image())
    item = {
        "post_id": "a",
        "account": "academia",
        "caption": "Social el viernes",
        "flyer": "flyers/a-0.webp",
        "published": "2026-10-01T12:00:00+0000",
        "processed_at": "2026-10-01T10:00:00-05:00",
        "events": [],
    }
    asked: list[str] = []

    def failing(model, contents):
        asked.append(model)
        raise bakeoff.ExtractionError("busy")

    def answering(model, contents):
        asked.append(model)
        assert contents[0] == "Image 0:" and "Social el viernes" in contents[-1]
        return PostAnalysis(is_event_post=True, reason="ok", events=[])

    bakeoff.run_model("m", [item], failing, tmp_path, cache_dir=tmp_path, say=lambda text: None)
    bakeoff.run_model("m", [item], answering, tmp_path, cache_dir=tmp_path, say=lambda text: None)
    bakeoff.run_model("m", [item], answering, tmp_path, cache_dir=tmp_path, say=lambda text: None)  # cached
    assert asked == ["m", "m"]
    assert bakeoff.load_cache(bakeoff.cache_file("m", tmp_path))["a"]["answer"]["reason"] == "ok"


def test_groq_answers_every_post_waiting_for_its_tokens_and_a_skip_isnt_cached(tmp_path, monkeypatch):
    """Review finding: the second post was refused "tokens for this minute are used" and cached as an error."""
    now = [1000.0]
    pauses: list[float] = []

    def sleep(seconds: float) -> None:
        pauses.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(external.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(external.time, "sleep", sleep)
    tpm = httpx.Response(429, json={"error": {"message": "Rate limit reached on tokens per minute (TPM)"}})
    answers = [chat(ANALYSIS, GROQ) for _ in range(3)] + [tpm]
    api = FakeAPI({GROQ: answers})
    tier = ExternalTier(keys={"groq": "k"}, http=httpx.Client(transport=httpx.MockTransport(api)))
    (tmp_path / "flyers").mkdir()
    (tmp_path / "flyers" / "f-0.webp").write_bytes(make_image())
    picks = [
        {
            "post_id": f"p{n}",
            "account": "academia",
            "caption": "Social de salsa",
            "flyer": "flyers/f-0.webp",
            "published": "2026-10-01T12:00:00+0000",
            "processed_at": "2026-10-01T10:00:00-05:00",
            "events": [],
        }
        for n in range(4)
    ]
    said: list[str] = []
    model = f"groq:{GROQ}"
    bakeoff.run_model(model, picks, bakeoff.asker(lambda: "x", external=tier), tmp_path, tmp_path, said.append)
    cache = bakeoff.load_cache(bakeoff.cache_file(model, tmp_path))
    assert all("answer" in cache[f"p{n}"] for n in range(3))
    assert "p3" not in cache and "not asked" in said[-1]  # Groq's own token 429: tried again on the next run
    assert sum(pause > 30 for pause in pauses) == 3  # each post waited for the one before to leave the minute


def test_discover_lists_free_models_with_image_input_and_text_answers():
    listing = {
        "data": [
            {
                "id": "google/gemma-4-31b-it:free",  # in config.EXTERNAL_PROVIDERS: starred
                "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                "supported_parameters": ["response_format", "structured_outputs"],
                "context_length": 131072,
            },
            {
                "id": "new/vision:free",
                "architecture": {"input_modalities": ["image", "text"]},
                "supported_parameters": ["response_format"],
            },
            {"id": "text/only:free", "architecture": {"input_modalities": ["text"]}},
            {"id": "paid/vision", "architecture": {"input_modalities": ["image"]}, "pricing": {"prompt": "0.1"}},
            # Lyria: a zero token price, but paid per clip and answering in audio: never a reader of posts.
            {
                "id": "google/lyria-3-clip-preview",
                "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text", "audio"]},
                "pricing": {"prompt": "0", "completion": "0"},
            },
        ]
    }
    found = bakeoff.free_vision_models(listing)
    assert [(model["id"], model["structured"]) for model in found] == [
        ("google/gemma-4-31b-it:free", True),
        ("new/vision:free", False),
    ]
    text = bakeoff.discover_text(found)
    assert " * google/gemma-4-31b-it:free  (structured" in text and "   new/vision:free  (json_object" in text


def test_the_default_models_are_flash_lite_and_every_external_one():
    assert bakeoff.DEFAULT_MODELS[0] == "gemini-3.5-flash-lite"
    assert "groq:qwen/qwen3.8-27b" in bakeoff.DEFAULT_MODELS
    assert "openrouter:google/gemma-4-31b-it:free" in bakeoff.DEFAULT_MODELS


# ---------- where the last resort shows: health, status, admin why ----------


def test_health_notes_when_the_last_resort_was_used_and_warns_when_a_provider_keeps_refusing():
    used = run_record(
        gemini_requests={"gemini-3.8-flash": 18, "groq": 2},
        external_outcomes={"groq:qwen/qwen3.8-27b": {"answered": 1, "busy": 1}},
    )
    [finding] = health_check(used)
    assert finding.key == "external" and "2 groq requests" in finding.text and "busy 1" in finding.text

    refused = run_record(external_problems={"openrouter": "402: the account needs credit"})
    keys = {f.key: f.level for f in health.check(refused, [refused, refused], stats_with(a=recent()), TODAY)}
    assert keys == {"external-off:openrouter": "warning"}


def test_the_run_record_keeps_the_last_resorts_report():
    stats = RunStats()
    stats.external = ExternalReport(outcomes={"groq:m": {"answered": 1}}, quarantined=["groq:m"])
    run = health.record_of(stats, [])
    assert run.external_outcomes == {"groq:m": {"answered": 1}} and run.external_quarantined == ["groq:m"]


def test_status_shows_the_last_resorts_use_today():
    now = datetime(2026, 10, 2, 20, 15, tzinfo=config.BOGOTA_TZ)
    usage = {"day": "2026-10-03", "providers": {"groq": {"requests": 3, "tokens": 21000, "answered": {"q": 2}}}}

    def read(name, default):
        return usage if name == config.EXTERNAL_USAGE_FILE.name else default

    config.ACCOUNTS_FILE.write_text("academia\n", encoding="utf-8")
    result = status.collect(now=now, instagram=None, read=read)
    groq, openrouter = result["external"]["providers"]
    assert (groq["name"], groq["used"], groq["tokens"], groq["answered"]) == ("groq", 3, 21000, {"q": 2})
    assert (openrouter["used"], openrouter["tokens"]) == (0, None)
    assert result["external"]["resets_at"].startswith("2026-10-03T19:00")  # the next midnight UTC
    assert "⚠️ groq (último recurso, Gemini sin cuota): 3 de 900 solicitudes hoy" in status.markdown(result)


def test_why_names_the_last_resorts_model():
    fields = {"model": "groq:qwen/qwen3.8-27b", "provisional": True, "outcome": "event", "event_ids": ["gone"]}
    config.ACCOUNTS_FILE.write_text("academia\n", encoding="utf-8")
    result = why.diagnose(LINK, read=state({"1": record(**fields)}))
    text = " ".join(text for _, text in result.checks)
    assert "groq:qwen/qwen3.8-27b (último recurso fuera de Gemini" in text
