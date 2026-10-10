"""`admin bakeoff`: picking posts, running models on them (fake), scoring against Flash, OpenRouter's free list."""

from datetime import datetime
from typing import get_args

import httpx
import pytest

from pa_bailar import bakeoff, config, external, health, status, why
from pa_bailar.external import ExternalReport, ExternalTier
from pa_bailar.models import STYLES, EventType, PostAnalysis
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


# ---------- the test set (gold/) ----------

CALENDAR_NIGHT = {
    "id": "acere",
    "title": "Acere",
    "title_wrong": ["salsoteca"],
    "date": "2026-10-10",
    "event_type": ["concert", "party"],
    "start_time": ["18:00", None],
    "venue": "El Goce Pagano",
    "prices": [],
    "styles": ["salsa"],
}


def test_gold_checks_only_what_the_flyer_settles_and_takes_any_right_value():
    read = {
        "title": "Acere en vivo",
        "date": "2026-10-10",
        "event_type": "party",
        "start_time": None,
        "venue": "Goce Pagano",
        "prices": [],
        "styles": ["salsa"],
        "end_time": "03:00",
    }
    assert all(bakeoff.compare_gold(CALENDAR_NIGHT, read).values())
    assert "end_time" not in bakeoff.compare_gold(CALENDAR_NIGHT, read)  # not on the flyer: not checked
    wrong = {**read, "title": "Salsoteca DC - Acere", "start_time": "23:30:00", "styles": ["salsa", "bachata"]}
    assert {name for name, ok in bakeoff.compare_gold(CALENDAR_NIGHT, wrong).items() if not ok} == {
        "title",
        "start_time",
        "styles",
    }
    range_read = bakeoff.compare_gold({**CALENDAR_NIGHT, "end_date": "2026-11-01"}, read)
    assert range_read["end_date"] is False  # "11 OCT — 01 NOV" read as one day


def test_gold_scoring_matches_each_expected_event_once_and_skips_optional_ones():
    workshops = [
        {
            "id": "regueton",
            "title": ["Reguetón", "María Mutante"],
            "date": "2026-10-11",
            "event_type": "workshop",
            "start_time": "15:00",
        },
        {"id": "sabroseo", "title": "Sabroseo", "date": "2026-10-11", "event_type": "workshop", "start_time": "16:00"},
        {"id": "meet", "title": "Meet & Greet", "date": "2026-10-11", "event_type": "other", "optional": True},
    ]
    read = [
        {
            "title": "Workshop Pro Fondos: Sabroseo",
            "date": "2026-10-11",
            "event_type": "workshop",
            "start_time": "16:00",
        },
        {"title": "Workshops Pro Fondos", "date": "2026-10-11", "event_type": "workshop", "start_time": "15:00"},
    ]
    posts = [{"post_id": "pud", "events": workshops}, {"post_id": "gone", "events": workshops[:1]}]
    result = bakeoff.score_gold(posts, {"pud": {"answer": {"events": read}, "seconds": 4}})
    assert (result.found, result.missed, result.extra, result.errors) == (2, 0, 0, 1)
    assert result.fields["title"] == [1, 2] and result.fields["start_time"] == [2, 2]
    assert any("regueton title" in note for note in result.notes)


def test_the_test_set_is_well_formed():
    """gold/posts.json: every post has its flyer and dates; every expected event a title, a date and only known
    types and styles (a typo would make a check fail for every model)."""
    posts = bakeoff.load_gold()
    assert len(posts) >= 40 and len({post["post_id"] for post in posts}) == len(posts)
    for post in posts:
        assert (bakeoff.GOLD_DIR / post["flyer"]).exists(), post["flyer"]
        datetime.fromisoformat(post["processed_at"])
        assert post["events"] and post["why"]
        ids = [event["id"] for event in post["events"]]
        assert len(set(ids)) == len(ids)
        for event in post["events"]:
            datetime.fromisoformat(event["date"])
            assert set(bakeoff._options(event["event_type"])) <= set(get_args(EventType))
            assert set(event.get("styles", [])) | set(event.get("styles_ok", [])) <= set(STYLES)
            known = {"id", "title", "title_wrong", "date", "end_date", "sessions", "start_time", "end_time"}
            assert set(event) <= known | {"event_type", "venue", "prices", "styles", "styles_ok", "optional"}


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


def test_a_post_is_read_with_its_accounts_rules_as_in_the_sweep(tmp_path):
    """Until #149 the bake-off asked without the account's rules (accounts.txt): a bar's post was read more loosely
    than the sweep reads it, so the test set measured another reading than the site's."""
    (tmp_path / "flyers").mkdir()
    (tmp_path / "flyers" / "a-0.webp").write_bytes(make_image())
    item = {"post_id": "a", "account": "salsabar", "caption": "Aniversario", "flyer": "flyers/a-0.webp", "events": []}
    item |= {"published": "2026-10-01T12:00:00+0000", "processed_at": "2026-10-01T10:00:00-05:00"}
    assert "BAR or club" not in bakeoff.contents_for(item, tmp_path)[-1]  # no accounts.txt: no rules
    config.ACCOUNTS_FILE.write_text("academia\nsalsabar  bar\n", encoding="utf-8")
    assert "BAR or club" in bakeoff.contents_for(item, tmp_path)[-1]
    assert "BAR or club" not in bakeoff.contents_for({**item, "account": "academia"}, tmp_path)[-1]


def test_an_answer_to_another_prompt_is_asked_again(tmp_path, monkeypatch):
    """Review of 7 Oct 2026: answers were cached by post alone, so after the prompt changed (#149) the test set kept
    scoring the old prompt's answers as if they were the new one's."""
    (tmp_path / "flyers").mkdir()
    (tmp_path / "flyers" / "a-0.webp").write_bytes(make_image())
    item = {"post_id": "a", "account": "academia", "caption": "Social", "flyer": "flyers/a-0.webp", "events": []}
    item |= {"published": "2026-10-01T12:00:00+0000", "processed_at": "2026-10-01T10:00:00-05:00"}
    asked: list[str] = []

    def answering(model, contents):
        asked.append(model)
        return PostAnalysis(is_event_post=True, reason="ok", events=[])

    bakeoff.run_model("m", [item], answering, tmp_path, cache_dir=tmp_path, say=lambda text: None)
    bakeoff.run_model("m", [item], answering, tmp_path, cache_dir=tmp_path, say=lambda text: None)  # same request
    monkeypatch.setattr(bakeoff, "EXTRACTION_PROMPT", bakeoff.EXTRACTION_PROMPT + "\nA new rule.")
    bakeoff.run_model("m", [item], answering, tmp_path, cache_dir=tmp_path, say=lambda text: None)
    assert asked == ["m", "m"]
    stale = bakeoff.stale_answers([item], bakeoff.load_cache(bakeoff.cache_file("m", tmp_path)), tmp_path)
    assert stale == 0
    monkeypatch.setattr(bakeoff, "EXTRACTION_PROMPT", bakeoff.EXTRACTION_PROMPT + "\nYet another.")
    assert bakeoff.stale_answers([item], bakeoff.load_cache(bakeoff.cache_file("m", tmp_path)), tmp_path) == 1


def test_a_flyer_gone_since_keeps_its_answer_and_counts_as_current(tmp_path):
    """The code-quality pass of 8 Oct 2026: once a picked post's flyer was gone (its event archived), `--score`
    crashed counting stale answers, and the next run replaced the cached answer with the error."""
    (tmp_path / "flyers").mkdir()
    flyer = tmp_path / "flyers" / "a-0.webp"
    flyer.write_bytes(make_image())
    item = {"post_id": "a", "account": "academia", "caption": "Social", "flyer": "flyers/a-0.webp", "events": []}
    item |= {"published": "2026-10-01T12:00:00+0000", "processed_at": "2026-10-01T10:00:00-05:00"}

    def answering(model, contents):
        return PostAnalysis(is_event_post=True, reason="ok", events=[])

    bakeoff.run_model("m", [item], answering, tmp_path, cache_dir=tmp_path, say=lambda text: None)
    flyer.unlink()
    cache = bakeoff.load_cache(bakeoff.cache_file("m", tmp_path))
    assert bakeoff.stale_answers([item], cache, tmp_path) == 0
    bakeoff.run_model("m", [item], answering, tmp_path, cache_dir=tmp_path, say=lambda text: None)
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
    assert bakeoff.DEFAULT_MODELS[0] == config.LITE_MODELS[0]
    assert bakeoff.FLASH_MODELS == config.FLASH_MODELS  # not 3 Flash, whose reads are provisional
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


def test_the_test_sets_options_need_the_test_set(capsys):
    """Review of 7 Oct 2026: `--ocr` without `--gold` was silently ignored (the Flash comparison ran without it)."""
    from pa_bailar.commands import admin

    for options in (["--ocr"], ["--thinking", "low"]):
        with pytest.raises(SystemExit):
            admin.main(["bakeoff", *options])
        assert "go with --gold" in capsys.readouterr().err


def test_each_mode_runs_its_default_models_or_the_ones_named(monkeypatch):
    """Flash-Lite alone on the test set, Flash-Lite and the last resort's models against Flash; `--models` names the
    ones run, even the other mode's defaults (they were taken for "no --models" and swapped)."""
    from pa_bailar.commands import admin

    monkeypatch.setattr(admin.sweep_state, "refresh", lambda: True)
    ran: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(bakeoff, "run_gold", lambda models, **options: ran.append(("gold", models)))
    monkeypatch.setattr(bakeoff, "run", lambda posts, models, **options: ran.append(("flash", models)))
    defaults = list(bakeoff.DEFAULT_MODELS)
    admin.main(["bakeoff", "--gold", "--score"])
    admin.main(["bakeoff", "--score"])
    admin.main(["bakeoff", "--gold", "--score", "--models", *defaults])
    assert ran == [("gold", list(bakeoff.GOLD_MODELS)), ("flash", defaults), ("gold", defaults)]


def test_the_ocr_variant_says_what_it_needs_without_the_engine(monkeypatch):
    monkeypatch.setattr(bakeoff.ocr, "available", lambda: False)
    said: list[str] = []
    bakeoff.run_gold(["gemini-3.5-flash-lite"], with_ocr=True, say=said.append)
    assert said and "pip install rapidocr onnxruntime" in said[0]


# ---------- batched extraction on the test set (--batch) ----------


def gold_item(post_id: str, account: str, title: str = "Social") -> dict:
    expected = {"id": f"{post_id}-e", "title": title, "date": "2026-11-13", "event_type": "social"}
    return {
        "post_id": post_id,
        "account": account,
        "caption": f"{title} el 13 de noviembre",
        "flyer": f"flyers/{post_id}-0.webp",
        "published": "2026-10-01T12:00:00+0000",
        "processed_at": "2026-10-01T10:00:00-05:00",
        "events": [expected],
    }


def test_the_test_set_is_batched_by_account_first_then_across_accounts():
    posts = [gold_item("a1", "a"), gold_item("b1", "b"), gold_item("a2", "a"), gold_item("c1", "c")]
    posts += [gold_item("d1", "d"), gold_item("a3", "a")]
    batches = [[item["post_id"] for item in batch] for batch in bakeoff.gold_batches(posts, 2)]
    assert batches == [["a1", "a2"], ["a3", "b1"], ["c1", "d1"]]
    batches = [[item["post_id"] for item in batch] for batch in bakeoff.gold_batches(posts, 3)]
    assert batches == [["a1", "a2", "a3"], ["b1", "c1", "d1"]]
    real = bakeoff.load_gold()
    for size in (2, 3):  # every post of the real test set exactly once
        ids = [item["post_id"] for batch in bakeoff.gold_batches(real, size) for item in batch]
        assert sorted(ids) == sorted(item["post_id"] for item in real)


class FakeAsker:
    """Answers one post with its expected title, and a batch per `batch_answer` (letters and image indexes)."""

    def __init__(self, posts: list[dict], batch_answer=None, batch_error: Exception | None = None):
        self.titles = {item["caption"]: item["events"][0]["title"] for item in posts}
        self.batch_answer = batch_answer
        self.batch_error = batch_error
        self.asked: list[str] = []

    def __call__(self, model, contents):
        self.asked.append("one")
        title = next(t for caption, t in self.titles.items() if caption in contents[-1])
        return PostAnalysis(is_event_post=True, reason="ok", events=[extracted_event(title)])

    def read(self, model, contents, schema):
        self.asked.append("batch")
        if self.batch_error:
            raise self.batch_error
        return self.batch_answer.pop(0) if isinstance(self.batch_answer, list) else self.batch_answer


def extracted_event(title: str):
    from tests.factories import extracted

    return extracted(title=title, date="2026-11-13", event_type="social")


def batch_of(*posts: tuple[str, str, int | None]):
    from pa_bailar.models import BatchAnalysis, BatchPostAnalysis

    return BatchAnalysis(
        posts=[
            BatchPostAnalysis(
                post=letter,
                is_event_post=True,
                reason="ok",
                events=[extracted_event(title).model_copy(update={"image_index": index})],
            )
            for letter, title, index in posts
        ]
    )


def with_flyers(tmp_path, posts):
    (tmp_path / "flyers").mkdir(exist_ok=True)
    for item in posts:
        (tmp_path / item["flyer"]).write_bytes(make_image())


def test_a_batched_run_reads_two_posts_a_request_and_a_post_left_out_alone(tmp_path):
    posts = [gold_item("a1", "a", "Uno"), gold_item("a2", "a", "Dos"), gold_item("b1", "b", "Tres")]
    with_flyers(tmp_path, posts)
    asker = FakeAsker(posts, batch_answer=batch_of(("A", "Uno", 0), ("B", "Dos", 0)))  # B cites A's image
    bakeoff.run_batched("m", posts, asker, tmp_path, 2, cache_dir=tmp_path, say=lambda text: None)
    assert asker.asked == ["batch", "one", "one"]  # a2 read again alone; b1 alone in its batch
    cache = bakeoff.load_cache(bakeoff.cache_file("m+batch2", tmp_path))
    assert cache["a1"]["batch"] == ["a1", "a2"] and "alone" not in cache["a1"]
    assert cache["a2"]["alone"] == "un evento cita una imagen de otra publicación"
    assert cache["a2"]["answer"]["events"][0]["title"] == "Dos"
    assert bakeoff.requests_used(posts, cache) == (3, 1, 2)
    result = bakeoff.score_gold(posts, cache)
    assert (result.found, result.missed, result.extra) == (3, 0, 0)

    bakeoff.run_batched("m", posts, asker, tmp_path, 2, cache_dir=tmp_path, say=lambda text: None)
    assert len(asker.asked) == 3  # answered with the same requests: nothing asked again
    assert bakeoff.stale_batched(posts, 2, cache, tmp_path) == 0


def test_a_batched_request_that_fails_reads_each_post_alone(tmp_path):
    posts = [gold_item("a1", "a", "Uno"), gold_item("a2", "a", "Dos")]
    with_flyers(tmp_path, posts)
    asker = FakeAsker(posts, batch_error=bakeoff.ExtractionError("busy"))
    bakeoff.run_batched("m", posts, asker, tmp_path, 2, cache_dir=tmp_path, say=lambda text: None)
    cache = bakeoff.load_cache(bakeoff.cache_file("m+batch2", tmp_path))
    assert asker.asked == ["batch", "one", "one"]
    assert all(cache[pid]["alone"].startswith("falló") and "answer" in cache[pid] for pid in ("a1", "a2"))
    assert bakeoff.requests_used(posts, cache) == (3, 1, 2)  # the failed request counts too


def test_the_batched_score_sets_the_two_readings_side_by_side_per_kind_of_batch(tmp_path):
    posts = [gold_item("a1", "a", "Uno"), gold_item("a2", "a", "Dos"), gold_item("b1", "b", "Tres")]
    posts.append(gold_item("c1", "c", "Cuatro"))
    with_flyers(tmp_path, posts)
    single = {
        item["post_id"]: {
            "answer": {"events": [extracted_event(item["events"][0]["title"]).model_dump()]},
            "seconds": 1,
        }
        for item in posts
    }
    answers = [batch_of(("A", "Uno", 0), ("B", "Dos", 1)), batch_of(("A", "Tres", 0), ("B", "Cuatro", 1))]
    asker = FakeAsker(posts, batch_answer=answers)
    bakeoff.run_batched("m", posts, asker, tmp_path, 2, cache_dir=tmp_path, say=lambda text: None)
    batched = bakeoff.load_cache(bakeoff.cache_file("m+batch2", tmp_path))
    text = bakeoff.batch_score_text("m+batch2", posts, 2, single, batched)
    assert "F1 1.000" in text and "requests: 2 for 4 posts (2 shared, 0 read alone)" in text
    assert "one account (2 posts), one post a request: found 2" in text
    assert "different accounts (2 posts), 2 a request: found 2" in text


def test_batch_and_take_go_with_the_test_set(capsys, monkeypatch):
    from pa_bailar.commands import admin

    for options in (["--batch", "2"], ["--take", "2"]):
        with pytest.raises(SystemExit):
            admin.main(["bakeoff", *options])
        assert "go with --gold" in capsys.readouterr().err
    monkeypatch.setattr(admin.sweep_state, "refresh", lambda: True)
    ran: list[dict] = []
    monkeypatch.setattr(bakeoff, "run_gold", lambda models, **options: ran.append(options))
    admin.main(["bakeoff", "--gold", "--batch", "2", "--take", "2", "--score"])
    assert ran[0]["batch"] == 2 and ran[0]["take"] == 2
