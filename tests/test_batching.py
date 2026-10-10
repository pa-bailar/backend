"""Batched extraction (the owner, 9 Oct 2026): several posts of one account in one request, each post's answer checked,
and every post the answer leaves out read again alone. Off by default (config.EXTRACTION_BATCH_POSTS = 1)."""

from datetime import UTC, datetime

import pytest
from google.genai import types

from pa_bailar import config, extraction, gemini, storage
from pa_bailar.batching import (
    NO_ANSWER,
    NO_EVENT,
    OTHER_IMAGE,
    STRAY_ANSWER,
    TWO_ANSWERS,
    BatchItem,
    BatchReading,
    batch_contents,
    split_answer,
)
from pa_bailar.gemini import ExtractionError, QuotaExhaustedError, RejectedRequestError, UnreadableAnswerError
from pa_bailar.models import BatchAnalysis, BatchPostAnalysis, PostAnalysis, Triage
from tests.factories import extracted, make_image, stored
from tests.test_sweep import (
    FakeExtractor,
    FakeInstagram,
    event_post,
    post,
    read,
    run,
    two_accounts_and_fake_images,  # noqa: F401  (autouse: two accounts, images offline)
)

CONTEXT = {
    "account": "academia",
    "published": "2026-10-04 Sunday",
    "today": "2026-10-05 Monday",
    "caption": "Social el viernes {no es un campo}",
    "account_rules": "",
}


def answer(*posts: tuple[str, list[int | None]]) -> BatchAnalysis:
    """A batched answer: per post its letter and its events' image_index (one event each)."""
    return BatchAnalysis(
        posts=[
            BatchPostAnalysis(
                post=letter,
                is_event_post=bool(indexes),
                reason=f"post {letter}",
                events=[extracted(title=f"Evento {letter}{n}", image_index=index) for n, index in enumerate(indexes)],
            )
            for letter, indexes in posts
        ]
    )


# ---------- the request ----------


def test_each_post_comes_with_its_own_context_and_images_numbered_across_the_request():
    second = CONTEXT | {"caption": "Taller de bachata", "account_rules": "\n\nThis account is a BAR"}
    contents = batch_contents([(CONTEXT, [make_image(), make_image()]), (second, [make_image()])], "- social | x")
    texts = [part for part in contents if isinstance(part, str)]
    assert texts[0].startswith("POST A (its images: Image 0, Image 1)") and "Social el viernes {no es" in texts[0]
    assert texts[1:3] == ["Image 0 (post A):", "Image 1 (post A):"]
    assert texts[3].startswith("POST B (its images: Image 2)") and "Taller de bachata" in texts[3]
    assert "This account is a BAR" in texts[3] and "BAR" not in texts[0]  # each post its own account's rules
    assert texts[4] == "Image 2 (post B):"
    assert sum(isinstance(part, types.Part) for part in contents) == 3
    prompt = texts[-1]
    assert "This request holds 2 separate Instagram posts (A, B)" in prompt
    assert "- social | x" in prompt and "never another post of this request" in prompt
    assert "never an image of another post" in prompt


def test_a_post_without_images_says_so_and_no_known_events_reads_none():
    contents = batch_contents([(CONTEXT, []), (CONTEXT, [make_image()])], "")
    assert contents[0].startswith("POST A (its images: none)")
    assert contents[1].startswith("POST B (its images: Image 0)")
    assert "(none)" in contents[-1]


def test_the_one_post_prompt_is_unchanged_by_the_batched_one():
    """The batched prompt reuses the extraction's parts: the one-post prompt must stay word for word (the switch off
    is the sweep as before, and the bake-off's cached answers stay current)."""
    import hashlib

    from pa_bailar.prompts import EXTRACTION_PROMPT

    assert hashlib.sha256(EXTRACTION_PROMPT.encode()).hexdigest()[:16] == "b5126a52a0e1a98f"


# ---------- the answer, checked ----------


def test_each_posts_answer_gets_its_own_images_numbered_from_zero_again():
    analyses, left_out = split_answer(answer(("A", [1, None]), ("B", [2, 3])), [2, 2])
    assert left_out == {}
    assert [event.image_index for event in analyses[0].events] == [1, None]
    assert [event.image_index for event in analyses[1].events] == [0, 1]
    assert analyses[1].reason == "post B" and analyses[1].is_event_post


def test_a_post_with_no_answer_or_two_is_left_out():
    analyses, left_out = split_answer(answer(("A", [0]), ("C", [2]), ("C", [2])), [1, 1, 1])
    assert list(analyses) == [0]
    assert left_out == {1: NO_ANSWER, 2: TWO_ANSWERS}


def test_an_event_citing_another_posts_image_leaves_its_post_out():
    """The mix-up the batch could make: a post's event on another post's flyer. Read alone instead."""
    analyses, left_out = split_answer(answer(("A", [0]), ("B", [0])), [1, 1])
    assert list(analyses) == [0] and left_out == {1: OTHER_IMAGE}
    _, left_out = split_answer(answer(("A", [5])), [1])  # an image no post has
    assert left_out == {0: OTHER_IMAGE}


def test_a_post_the_shared_answer_finds_no_event_in_is_confirmed_alone():
    """The test set (9 Oct 2026): the two events batching lost were "no"s, a bar's night beside another account's
    workshops and an academy's closing show. A "no" is final, so it's never taken from a shared answer."""
    analyses, left_out = split_answer(answer(("A", [0]), ("B", [])), [1, 1])
    assert list(analyses) == [0] and left_out == {1: NO_EVENT}


def test_a_shared_no_that_lists_events_is_a_no_confirmed_alone():
    """is_event_post false with events listed: the sweep stores none of them (_store_analysis) and records the post as
    no event, for good. So it's a "no" like any other, confirmed alone (the bug hunt of 9 Oct 2026)."""
    said_no = answer(("A", [0]), ("B", [1]))
    said_no.posts[1].is_event_post = False
    analyses, left_out = split_answer(said_no, [1, 1])
    assert list(analyses) == [0] and left_out == {1: NO_EVENT}


def test_an_answer_for_a_post_the_request_doesnt_hold_leaves_every_post_out():
    analyses, left_out = split_answer(answer(("A", [0]), ("B", [1]), ("D", [])), [1, 1])
    assert analyses == {} and left_out == {0: STRAY_ANSWER, 1: STRAY_ANSWER}


def test_letters_are_read_loosely():
    analyses, left_out = split_answer(answer(("post b", [1]), (" a ", [0])), [1, 1])
    assert left_out == {} and set(analyses) == {0, 1}


@pytest.mark.parametrize(
    ("value", "posts"),
    [(None, 1), ("", 1), ("1", 1), ("2", 2), ("3", 3), ("12", 3), ("0", 1), ("dos", 1), ("-2", 1)],
)
def test_the_switch_is_off_unless_set_and_never_past_three(value, posts):
    assert config._batch_posts(value) == posts


def test_the_switch_is_off_by_default():
    assert config.EXTRACTION_BATCH_POSTS == 1 or config._batch_posts(None) == 1


# ---------- the extractor: one request, counted once ----------


class FakeModels:
    def __init__(self, answers: dict[str, list]):
        self.answers = answers
        self.calls: list[str] = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        outcome = self.answers[model].pop(0)
        if isinstance(outcome, Exception):
            raise outcome

        class Response:
            parsed = outcome

        return Response()


@pytest.fixture
def extractor(monkeypatch):
    monkeypatch.setattr(config, "PACING_MARGIN_SECONDS", 0)
    monkeypatch.setattr(gemini.time, "sleep", lambda seconds: None)
    made = extraction.EventExtractor("unused-key")

    class Client:
        models = FakeModels({})

    made.pool._client = Client()
    return made


def items(count: int = 2) -> list[BatchItem]:
    published = datetime(2026, 10, 4, 15, tzinfo=UTC)
    return [BatchItem(post(f"p{i}"), published, [make_image()]) for i in range(count)]


def test_a_batch_is_one_request_and_counts_once_in_the_days_quota(extractor):
    flash = config.EXTRACTION_MODELS[0]
    extractor.pool._client.models.answers = {flash: [answer(("A", [0]), ("B", [1]))]}
    reading = extractor.extract_batch("academia", items(2), [stored()])
    assert extractor.pool._client.models.calls == [flash]
    assert extractor.requests_this_run() == {flash: 1} and extractor.pool.used(flash) == 1
    assert (reading.model, reading.provisional, reading.left_out) == (flash, False, {})
    assert [analysis.events[0].image_index for analysis in reading.analyses.values()] == [0, 0]


def test_a_batch_with_flash_out_is_read_by_the_provisional_models_and_marked_so(extractor):
    for model in config.EXTRACTION_MODELS:
        extractor.pool._exhaust(model)
    provisional = config.PROVISIONAL_MODELS[0]
    extractor.pool._client.models.answers = {provisional: [answer(("A", [0]), ("B", [1]))]}
    reading = extractor.extract_batch("academia", items(2), [])
    assert (reading.model, reading.provisional) == (provisional, True)


def test_a_shared_no_listing_events_is_read_alone_through_the_sweep(extractor, monkeypatch):
    """End to end, the real extractor (a fake Gemini): the shared answer says post B isn't an event post but lists an
    event; read alone, B's event is found and published, never recorded as "not an event" from the shared answer."""
    monkeypatch.setattr(config, "EXTRACTION_BATCH_POSTS", 2)
    flash = config.EXTRACTION_MODELS[0]
    said_no = answer(("A", [0]), ("B", [1]))
    said_no.posts[1].is_event_post = False
    extractor.pool._client.models.answers = {
        config.TRIAGE_MODELS[0]: [Triage(is_event_post=True, reason="t")] * 2,
        flash: [said_no, PostAnalysis(is_event_post=True, reason="alone", events=[extracted(title="Evento B0")])],
    }
    instagram = FakeInstagram({"academia": [post("p1", days_ago=3), post("p2", days_ago=2)], "otra": []})
    stats = run(instagram, extractor)
    records = storage.load_processed_posts()
    assert extractor.pool._client.models.calls.count(flash) == 2  # the shared request, then B alone
    assert (records["p2"].outcome, records["p2"].reason) == ("event", "alone")
    assert sorted(event["title"] for event in read(config.EVENTS_FILE)) == ["Evento A0", "Evento B0"]
    assert (stats.batched_posts, stats.batch_rereads) == (1, 1)


def test_a_batch_never_reaches_the_last_resort(extractor):
    for model in (*config.EXTRACTION_MODELS, *config.PROVISIONAL_MODELS):
        extractor.pool._exhaust(model)
    asked: list[str] = []
    extractor.external.available = lambda: True
    extractor.external.generate = lambda *args, **kwargs: asked.append("external")
    with pytest.raises(QuotaExhaustedError):
        extractor.extract_batch("academia", items(2), [])
    assert asked == []


# ---------- the sweep ----------


class BatchingExtractor(FakeExtractor):
    """FakeExtractor that also reads batches: per post id its prepared answer (`shared`'s when it has one: what the
    post gets in a shared answer, else the same as alone), unless the post is in `left_out` (the answer leaves it out,
    with why) or the whole batch fails (`batch_error`)."""

    def __init__(self, analyses, left_out=None, batch_error=None, shared=None, **options):
        super().__init__(analyses, **options)
        self.left_out = left_out or {}
        self.batch_error = batch_error
        self.shared = shared or {}
        self.batches: list[list[str]] = []
        self.batch_rules: list[list[str]] = []

    def extract_batch(self, account, items, known_events):
        ids = [item.post["id"] for item in items]
        self.batches.append(ids)
        self.batch_rules.append([item.rules for item in items])
        if self.out_of_quota:
            raise QuotaExhaustedError("no quota")
        if self.batch_error:
            raise self.batch_error
        answers = {index: self.shared.get(pid, self.analyses[pid]) for index, pid in enumerate(ids)}
        analyses = {index: answer for index, answer in answers.items() if ids[index] not in self.left_out}
        left = {index: self.left_out[pid] for index, pid in enumerate(ids) if pid in self.left_out}
        model, provisional = ("fake-flash", False) if self.flash_available else ("fake-lite", True)
        return BatchReading(analyses, left, model, provisional)


@pytest.fixture
def batches_of_two(monkeypatch):
    monkeypatch.setattr(config, "EXTRACTION_BATCH_POSTS", 2)


def three_posts(**options) -> tuple[FakeInstagram, BatchingExtractor]:
    posts = [post("p1", days_ago=3), post("p2", days_ago=2), post("tutorial", days_ago=1.5), post("p3", days_ago=1)]
    instagram = FakeInstagram({"academia": posts, "otra": []})
    analyses = {f"p{n}": event_post(f"p{n}", title=f"Social {n}", start_time=f"2{n}:00") for n in (1, 2, 3)}
    return instagram, BatchingExtractor(analyses, not_events={"tutorial"}, **options)


def test_switch_off_reads_one_post_a_request_as_before():
    instagram, extractor = three_posts()
    stats = run(instagram, extractor)
    assert extractor.batches == [] and extractor.extracted_posts == ["p1", "p2", "p3"]
    assert (stats.batch_requests, stats.batched_posts, stats.batch_rereads) == (0, 0, 0)


def test_an_accounts_event_posts_are_read_two_a_request_and_each_stored_as_its_own(batches_of_two):
    instagram, extractor = three_posts()
    stats = run(instagram, extractor)
    assert extractor.batches == [["p1", "p2"]]  # the triage's "no" never joins a batch
    assert extractor.extracted_posts == ["p3"]  # the last one, alone at the account's end: the one-post way
    assert sorted(event["title"] for event in read(config.EVENTS_FILE)) == ["Social 1", "Social 2", "Social 3"]
    records = storage.load_processed_posts()
    assert {pid: (records[pid].model, records[pid].provisional, records[pid].outcome) for pid in ("p1", "p2")} == {
        "p1": ("fake-flash", False, "event"),
        "p2": ("fake-flash", False, "event"),
    }
    assert records["tutorial"].outcome == "not_event"
    assert (stats.batch_requests, stats.batched_posts, stats.batch_rereads) == (1, 2, 0)
    assert (stats.posts_analyzed, stats.pending, stats.events_new) == (4, 0, 3)


def test_a_batch_read_by_a_lighter_model_is_provisional_for_each_post(batches_of_two):
    instagram, extractor = three_posts(flash_available=False)
    stats = run(instagram, extractor)
    records = storage.load_processed_posts()
    assert all(records[pid].provisional and records[pid].model == "fake-lite" for pid in ("p1", "p2", "p3"))
    assert stats.provisional == 3


def test_a_post_the_answer_leaves_out_is_read_again_alone_never_dropped(batches_of_two):
    instagram, extractor = three_posts(left_out={"p2": OTHER_IMAGE})
    stats = run(instagram, extractor)
    assert extractor.batches == [["p1", "p2"]] and extractor.extracted_posts == ["p2", "p3"]
    assert len(read(config.EVENTS_FILE)) == 3
    assert (stats.batch_requests, stats.batched_posts, stats.batch_rereads) == (1, 1, 1)


@pytest.mark.parametrize(
    "error",
    [ExtractionError("busy"), RejectedRequestError("respuesta demasiado larga"), UnreadableAnswerError("no JSON")],
)
def test_a_batch_no_model_could_read_is_read_post_by_post(batches_of_two, error):
    """A batch's failure is never its posts': refused or cut off, each post is read alone and gets its own result."""
    instagram, extractor = three_posts(batch_error=error, rejected=frozenset({"p2"}))
    stats = run(instagram, extractor)
    assert extractor.attempts == ["p1", "p2", "p3"]
    records = storage.load_processed_posts()
    assert records["p1"].outcome == "event" and records["p3"].outcome == "event"
    assert records["p2"].outcome == "rejected"  # Gemini refused that post alone: only it is recorded so
    assert (stats.batch_requests, stats.batched_posts, stats.batch_rereads) == (0, 0, 2)


def test_a_batch_out_of_quota_leaves_its_posts_pending(batches_of_two):
    instagram, extractor = three_posts()
    extractor.flash_available = True

    def out(account, items, known_events):
        extractor.batches.append([item.post["id"] for item in items])
        extractor.out_of_quota = True  # alone, each post finds no quota either
        raise QuotaExhaustedError("no quota")

    extractor.extract_batch = out
    stats = run(instagram, extractor)
    records = storage.load_processed_posts()
    assert "p1" not in records and "p2" not in records  # read next run
    assert stats.pending >= 2 and stats.by_account["academia"].pending >= 2


def test_a_batch_waiting_when_the_runs_time_is_up_waits_for_the_next_run(batches_of_two, monkeypatch):
    from pa_bailar.pipeline import Sweep

    checks: list[bool] = []

    def out_of_time(self) -> bool:  # the account's turn, p1 and p2 in time; then the batch finds the time up
        checks.append(len(checks) >= 3)
        return checks[-1]

    monkeypatch.setattr(Sweep, "_out_of_time", out_of_time)
    instagram, extractor = three_posts()
    stats = run(instagram, extractor)
    assert extractor.batches == [] and extractor.extracted_posts == []
    assert not {"p1", "p2", "p3"} & set(storage.load_processed_posts())
    assert stats.by_account["academia"].pending == 4  # p1, p2 in the batch; the tutorial and p3 after it


def test_batches_never_mix_accounts(batches_of_two):
    instagram = FakeInstagram({"academia": [post("a1")], "otra": [post("o1")]})
    analyses = {"a1": event_post("a1", title="Uno"), "o1": event_post("o1", title="Dos")}
    extractor = BatchingExtractor(analyses)
    run(instagram, extractor)
    assert extractor.batches == [] and extractor.extracted_posts == ["a1", "o1"]


def test_a_post_whose_images_wouldnt_fit_starts_the_next_batch(batches_of_two, monkeypatch):
    monkeypatch.setattr(config, "EXTRACTION_BATCH_MAX_IMAGES", 1)
    instagram, extractor = three_posts()
    run(instagram, extractor)
    assert extractor.batches == [] and extractor.extracted_posts == ["p1", "p2", "p3"]


def test_three_a_request(monkeypatch):
    monkeypatch.setattr(config, "EXTRACTION_BATCH_POSTS", 3)
    instagram, extractor = three_posts()
    run(instagram, extractor)
    assert extractor.batches == [["p1", "p2", "p3"]] and extractor.extracted_posts == []


def test_edited_posts_read_in_a_batch_count_as_reanalyzed(batches_of_two):
    instagram, extractor = three_posts()
    run(instagram, extractor)
    edited = [{**p, "caption": "Ahora con lugar"} for p in instagram.posts_by_account["academia"]]
    instagram.posts_by_account["academia"] = edited
    second = BatchingExtractor(extractor.analyses, not_events={"tutorial"})
    stats = run(instagram, second)
    assert second.batches == [["p1", "p2"]]  # had events: straight to the extraction, two a request
    assert stats.reanalyzed == 4 and stats.pending == 0  # the tutorial too: triaged again, still no event


def test_each_post_of_a_batch_keeps_its_accounts_rules(batches_of_two):
    config.ACCOUNTS_FILE.write_text("academia  bar\notra\n", encoding="utf-8")
    instagram, extractor = three_posts()
    run(instagram, extractor)
    assert all("BAR or club" in rules for rules in extractor.batch_rules[0])


def test_the_run_record_keeps_what_batching_did(batches_of_two):
    from pa_bailar import health
    from pa_bailar.commands.sweep import summary_markdown

    instagram, extractor = three_posts(left_out={"p2": NO_ANSWER})
    stats = run(instagram, extractor)
    record = health.record_of(stats, [])
    assert (record.batch_requests, record.batched_posts, record.batch_rereads) == (1, 1, 1)
    assert "1 read in 1 shared requests, 1 read again alone" in summary_markdown(stats)


def test_the_one_post_reading_answers_the_same_as_a_batch_of_one():
    """A PostAnalysis from a batch is the one-post schema: the sweep stores it the same way."""
    analyses, _ = split_answer(answer(("A", [0])), [1])
    assert isinstance(analyses[0], PostAnalysis)
