"""`admin bakeoff`: how well models read posts, measured against what Gemini Flash read, or against posts checked by
hand (`--gold`, the test set) (docs/ADMIN.md).

For re-checking the last resort's models (config.EXTERNAL_PROVIDERS) from time to time, or a new model before it's
listed: free models change, get slower or disappear without notice. On your computer only; it spends real requests
(each model, once per post), from the same daily quotas as the sweeps. Models are named as the sweep records them:
a Gemini model ("gemini-3.5-flash-lite") or "<provider>:<model>" ("groq:qwen/qwen3.8-27b").

  1. pick: recent posts Flash read on its own (not provisional, the only post of each of its events, with a stored
     flyer) from the site's events (config.DATA_DIR) and the sweeps' records (the sweep-state branch). A third of
     them, when there are, are workshop series or events over several days, the hardest dates.
  2. run: each model reads each post's caption and its stored flyer (one image) with the sweep's own extraction
     prompt and the account's rules (accounts.txt). Answers are cached in state/bakeoff/ (never committed) with a
     fingerprint of the request, so a rerun spends nothing on what was answered with the same request and asks
     again what failed or what a changed prompt asks differently. Groq waits for its tokens per minute between
     posts (about one a minute); a request its limits keep from being sent isn't cached as an error.
  3. score: each model's events against Flash's, field by field. Agreement with Flash measures similarity, not
     truth, and every model misses what's only on slides it wasn't given (a test limit).
  4. the test set (`--gold`): the same run on posts checked by hand (gold/, its README), scored against the truth,
     so Flash is measured too and a change to the reading (the prompt, `--ocr`, `--thinking`) is judged before it
     ships.
  5. batched (`--gold --batch N`): the test set also read N posts a request (batching.py, as the sweep does with
     config.EXTRACTION_BATCH_POSTS), scored beside the one-post reading with the requests each took; `--take K`
     caches another take apart, to measure how much two runs of the same reading differ.
`--discover` lists OpenRouter's free models now, with image input, and whether they take structured output: the
candidates for the list (no key, no quota).
"""

import hashlib
import io
import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from google.genai import types
from PIL import Image
from pydantic import BaseModel

from . import config, ocr, storage, sweep_state
from .account_options import AccountOptions
from .batching import NO_EVENT, batch_contents, split_answer
from .external import ExternalTier, SkippedError, recorded_name
from .gemini import ExtractionError, ModelPool, QuotaExhaustedError
from .models import BatchAnalysis, PostAnalysis
from .prompts import EXTRACTION_PROMPT, OCR_NOTE, account_rules
from .text import fold, folded_words

CACHE_DIR = config.STATE_DIR / "bakeoff"
DEFAULT_POSTS = 15
SEED = 5  # the same posts each time for the same data
# The readings compared against: this generation's Flash, final (an older Flash's reads are provisional).
FLASH_MODELS = config.FLASH_MODELS
# The baseline (the first Flash-Lite), then every model of the last resort.
DEFAULT_MODELS = (
    config.LITE_MODELS[0],
    *(recorded_name(provider.name, model.name) for provider in config.EXTERNAL_PROVIDERS for model in provider.models),
)
JPEG_QUALITY = 90

Item = dict[str, Any]  # a picked post: its id, account, caption, flyer, dates and Flash's events (plain JSON)
Ask = Callable[[str, list[types.PartUnionDict]], PostAnalysis]  # (model, contents) → its reading


# ---------- 1. pick ----------


def candidates(events: list[dict[str, Any]], processed: dict[str, dict[str, Any]], data_dir: Path) -> list[Item]:
    """Posts Flash read on its own: final (not provisional) Flash records whose events have that post alone, and a
    flyer on disk. Stories aren't posts: left out."""
    by_post: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        for media in event["media"]:
            by_post.setdefault(media["post_id"], []).append(event)
    found = []
    for post_id, its_events in by_post.items():
        record = processed.get(post_id)
        if not record or record.get("model") not in FLASH_MODELS or record.get("provisional"):
            continue
        media = next(m for m in its_events[0]["media"] if m["post_id"] == post_id)
        if media["media_type"] == "STORY" or not media.get("flyer") or not (data_dir / media["flyer"]).exists():
            continue
        if any(len(event["media"]) > 1 for event in its_events):
            continue  # details merged from other posts: not this post's own reading
        found.append(
            {
                "post_id": post_id,
                "account": its_events[0]["account"],
                "caption": media.get("caption"),
                "flyer": media["flyer"],
                "published": media["published"],
                "processed_at": record["processed_at"],
                "events": its_events,
            }
        )
    return sorted(found, key=lambda item: item["post_id"])


def pick(found: list[Item], count: int, seed: int = SEED) -> list[Item]:
    """`count` posts: up to a third with a series or an event over several days, the rest at random."""
    special = [item for item in found if any(e.get("sessions") or e.get("end_date") for e in item["events"])]
    chosen = special[: count // 3]
    rest = [item for item in found if item not in chosen]
    return chosen + random.Random(seed).sample(rest, min(len(rest), count - len(chosen)))


# ---------- 2. run ----------


def _rules(account: str) -> str:
    """The account's own rules, as the sweep adds them (a bar's: only special nights; a style focus): without them,
    a bar's post was read more loosely than in the sweep (until 7 Oct 2026). No accounts.txt: none."""
    try:
        options = storage.read_account_options().get(account, AccountOptions())
    except FileNotFoundError:
        return ""
    return account_rules(options.bar, options.focus)


def _context(item: Item) -> dict[str, str]:
    """The post's context as the sweep formats it (extraction._format_context), on the day Flash read it."""
    published = datetime.fromisoformat(item["published"].replace("+0000", "+00:00"))
    today = datetime.fromisoformat(item["processed_at"]).astimezone(config.BOGOTA_TZ)
    return {
        "account": item["account"],
        "published": published.astimezone(config.BOGOTA_TZ).strftime("%Y-%m-%d %A"),
        "today": today.strftime("%Y-%m-%d %A"),
        "caption": item["caption"] or "(sin texto)",
        "account_rules": _rules(item["account"]),
    }


def _flyer(item: Item, data_dir: Path) -> bytes:
    """The post's stored flyer as a JPEG, as the sweep sends images. Raises OSError when it can't be read."""
    buffer = io.BytesIO()
    Image.open(data_dir / item["flyer"]).convert("RGB").save(buffer, "JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


def contents_for(item: Item, data_dir: Path, with_ocr: bool = False) -> list[types.PartUnionDict]:
    """What the sweep sends for an extraction, as on the day Flash read the post: its flyer, then the prompt.
    `with_ocr`: the flyer's OCR text right after it (prompts.OCR_NOTE), the change being measured."""
    prompt = EXTRACTION_PROMPT.format(**_context(item), known_events="(none)")
    image = _flyer(item, data_dir)
    contents: list[types.PartUnionDict] = ["Image 0:", types.Part.from_bytes(data=image, mime_type="image/jpeg")]
    if with_ocr:
        contents.append(OCR_NOTE.format(index=0, rows="\n".join(ocr.rows(image)) or "(no text found)"))
    return [*contents, prompt]


def batch_contents_for(items: list[Item], data_dir: Path) -> list[types.PartUnionDict]:
    """What the sweep sends for a batched extraction of these posts (batching.batch_contents), each with its own
    context and flyer, as on the day it was read."""
    return batch_contents([(_context(item), [_flyer(item, data_dir)]) for item in items], "")


class Asker:
    """Reads with a Gemini model (config.MODEL_LIMITS) or a "<provider>:<model>" one, each client made when first
    needed (Gemini's key too; the providers' keys come from the environment), one Gemini pool for every request of
    the run, one post or a batch, so the day's usage is counted once. `thinking`: a Gemini model's thinking level, the
    model's default otherwise (as the sweep's extraction)."""

    def __init__(
        self,
        gemini_key: Callable[[], str],
        external: ExternalTier | None = None,
        thinking: types.ThinkingLevel | None = None,
    ):
        self._gemini_key = gemini_key
        self._gemini: ModelPool | None = None
        self._external = external
        self._thinking = thinking

    def __call__(self, model: str, contents: list[types.PartUnionDict]) -> PostAnalysis:
        """One post's reading."""
        return self.read(model, contents, PostAnalysis)

    def read[T: BaseModel](self, model: str, contents: list[types.PartUnionDict], schema: type[T]) -> T:
        if model in config.MODEL_LIMITS:
            self._gemini = self._gemini or ModelPool(self._gemini_key())
            return self._gemini.generate((model,), contents, schema, thinking=self._thinking)[0]
        provider, _, name = model.partition(":")
        self._external = self._external or ExternalTier()
        return self._external.generate_with(provider, name, contents, schema)[0]


def asker(
    gemini_key: Callable[[], str], external: ExternalTier | None = None, thinking: types.ThinkingLevel | None = None
) -> Asker:
    """An Asker: called with a model and a post's contents, its reading (Ask)."""
    return Asker(gemini_key, external, thinking)


def cache_file(model: str, cache_dir: Path = CACHE_DIR) -> Path:
    return cache_dir / f"answers-{model.replace('/', '_').replace(':', '_')}.json"


def load_cache(path: Path) -> dict[str, Any]:
    cached: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return cached


def request_fingerprint(contents: list[types.PartUnionDict]) -> str:
    """What a request asked, in 16 hex digits: its text (the prompt with the account's rules, the caption, the OCR
    text) and its images. A cached answer counts only for the same request: answers were cached by post alone, so
    after the prompt changed (#149) the test set kept scoring the old prompt's answers (review, 7 Oct 2026)."""
    digest = hashlib.sha256()
    for part in contents:
        if isinstance(part, str):
            digest.update(part.encode("utf-8"))
        elif isinstance(part, types.Part) and part.inline_data and part.inline_data.data:
            digest.update(part.inline_data.data)
    return digest.hexdigest()[:16]


def stale_answers(picks: list[Item], cache: dict[str, Any], data_dir: Path, with_ocr: bool = False) -> int:
    """How many cached answers were read with another request than the one asked today. A post whose flyer can't be
    read anymore (removed with its event) can't be asked again, so its answer isn't stale: it crashed `--score` (the
    code-quality pass of 8 Oct 2026)."""

    def stale(item: Item) -> bool:
        cached = cache.get(item["post_id"], {})
        if "answer" not in cached:
            return False
        try:
            contents = contents_for(item, data_dir, with_ocr)
        except OSError:
            return False
        return bool(cached.get("request") != request_fingerprint(contents))

    return sum(1 for item in picks if stale(item))


def run_model(
    model: str,
    picks: list[Item],
    ask: Ask,
    data_dir: Path,
    cache_dir: Path = CACHE_DIR,
    say: Callable[[str], None] = print,
    with_ocr: bool = False,
    label: str | None = None,
) -> None:
    """One model on every picked post it hasn't answered with today's request yet (request_fingerprint): one request
    each, the answer or the error cached under `label` (by default the model, "<model>+ocr" with the OCR text)."""
    path = cache_file(label or model + ("+ocr" if with_ocr else ""), cache_dir)
    cache = load_cache(path)
    for item in picks:
        try:
            contents = contents_for(item, data_dir, with_ocr)
        except OSError as error:  # the flyer can't be read: nothing to ask; an answer cached before stays
            if "answer" not in cache.get(item["post_id"], {}):
                cache[item["post_id"]] = {"error": str(error)[:300]}
            say(f"  {item['post_id']}: error: {str(error)[:120]}")
            continue
        request = request_fingerprint(contents)
        if "answer" in cache.get(item["post_id"], {}) and cache[item["post_id"]].get("request") == request:
            continue
        started = time.monotonic()
        try:
            answer = ask(model, contents)
        except QuotaExhaustedError as error:
            say(f"  no quota left today: {error}. The rest waits for another day.")
            break
        except SkippedError as error:  # its limits kept it from being asked: not an answer, nor a failure
            say(f"  {item['post_id']}: not asked ({str(error)[:120]}): tried again on the next run")
            continue
        except (ExtractionError, OSError) as error:
            cache[item["post_id"]] = {"error": str(error)[:300], "request": request}
            say(f"  {item['post_id']}: error: {str(error)[:120]}")
        else:
            seconds = round(time.monotonic() - started, 1)
            entry = {"answer": answer.model_dump(mode="json"), "seconds": seconds, "request": request}
            cache[item["post_id"]] = entry
            say(f"  {item['post_id']}: {len(answer.events)} events ({seconds} s)")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------- 3. score ----------


def _words(text: str | None) -> set[str]:
    """Letters and digits only ("Tributo." is "tributo"), words of three or more."""
    return {word for word in folded_words(text) if len(word) > 2}


def compare(reference: dict[str, Any], answer: dict[str, Any]) -> dict[str, bool]:
    """Field by field, one of Flash's events against the model's event on the same date: the same or not. A title
    matches when it has at least half of Flash's words; a venue, when they share one."""
    ref_title, title = _words(reference.get("title")), _words(answer.get("title"))
    ref_venue, venue = _words(reference.get("venue")), _words(answer.get("venue"))
    return {
        "date": answer.get("date") == reference.get("date"),
        "end_date": (answer.get("end_date") or None) == (reference.get("end_date") or None),
        "start_time": (answer.get("start_time") or "")[:5] == (reference.get("start_time") or "")[:5],
        "event_type": answer.get("event_type") == reference.get("event_type"),
        "title": bool(ref_title) and len(ref_title & title) / len(ref_title) >= 0.5,
        "styles": set(answer.get("styles") or []) == set(reference.get("styles") or []),
        "prices": {p.get("amount_cop") for p in answer.get("prices") or []}
        == {p.get("amount_cop") for p in reference.get("prices") or []},
        "venue": (not ref_venue and not venue) or bool(ref_venue & venue),
        "sessions": [s.get("date") for s in answer.get("sessions") or []]
        == [s.get("date") for s in reference.get("sessions") or []],
    }


@dataclass
class Score:
    found: int = 0  # Flash's events the model also found (on the same date)
    missed: int = 0
    extra: int = 0  # events the model found that Flash didn't
    errors: int = 0  # posts without an answer (failed or not run)
    seconds: list[float] = field(default_factory=list)
    fields: dict[str, list[int]] = field(default_factory=dict)  # field → [same, compared]
    notes: list[str] = field(default_factory=list)

    @property
    def average_seconds(self) -> float:
        return sum(self.seconds) / len(self.seconds) if self.seconds else 0.0

    @property
    def f1(self) -> float:
        """Events found against missed and extra in one number: 1.0 finds every event and adds none."""
        total = 2 * self.found + self.missed + self.extra
        return 2 * self.found / total if total else 0.0

    @property
    def fields_right(self) -> tuple[int, int]:
        """The fields read right, of those compared, over every event found."""
        return sum(same for same, _ in self.fields.values()), sum(compared for _, compared in self.fields.values())


def score(picks: list[Item], cache: dict[str, Any]) -> Score:
    """A model's cached answers against Flash's events, over every picked post."""
    result = Score()
    for item in picks:
        entry = cache.get(item["post_id"]) or {}
        if "answer" not in entry:
            result.errors += 1
            continue
        result.seconds.append(entry["seconds"])
        answered = [event for event in entry["answer"]["events"] if not event.get("is_recurring")]
        for reference in item["events"]:
            same_day = [event for event in answered if event.get("date") == reference["date"]]
            if not same_day:
                result.missed += 1
                result.notes.append(f"missed {reference['id']}")
                continue
            result.found += 1
            best = max(same_day, key=lambda event: len(_words(event.get("title")) & _words(reference.get("title"))))
            for name, same in compare(reference, best).items():
                counts = result.fields.setdefault(name, [0, 0])
                counts[0] += same
                counts[1] += 1
                if not same and name in ("start_time", "prices", "sessions", "end_date"):
                    result.notes.append(f"{reference['id']} {name}: Flash {reference.get(name)} vs {best.get(name)}")
        result.extra += max(0, len(answered) - len(item["events"]))
    return result


def score_text(model: str, result: Score, notes: int = 12) -> str:
    """One model's score for people: the totals, each field's agreement and the first differences."""
    fields = " · ".join(f"{name} {same}/{compared}" for name, (same, compared) in result.fields.items())
    right, compared = result.fields_right
    lines = [
        f"== {model}: found {result.found}, missed {result.missed}, extra {result.extra}, "
        f"errors {result.errors}, F1 {result.f1:.3f}, fields right {right}/{compared}, "
        f"avg {result.average_seconds:.0f} s",
        f"   {fields or '(nothing to compare)'}",
        *(f"   - {note[:170]}" for note in result.notes[:notes]),
    ]
    return "\n".join(lines)


# ---------- 4. the test set (gold/) ----------
# Posts checked by hand against their flyers (gold/posts.json; gold/README.md): scoring against the truth, not against
# Flash, so Flash is measured too and a change to the reading (a prompt, OCR, a second look) can be judged before it
# ships. An expected event names only the fields its flyer settles; a list means any of those values is right.

GOLD_DIR = config.ROOT_DIR / "gold"
GOLD_CACHE_DIR = CACHE_DIR / "gold"
GOLD_MODELS = (config.LITE_MODELS[0],)


def load_gold(gold_dir: Path = GOLD_DIR) -> list[Item]:
    posts: list[Item] = json.loads((gold_dir / "posts.json").read_text(encoding="utf-8"))["posts"]
    return posts


def _options(expected: Any) -> list[Any]:
    return expected if isinstance(expected, list) else [expected]


def _title_ok(expected: dict[str, Any], title: str | None) -> bool:
    """At least half the words of one of the right titles, and none of the words that make it wrong ("Salsoteca")."""
    words = _words(title)
    if words & {fold(word) for word in expected.get("title_wrong", [])}:
        return False
    return any(
        _words(right) and len(_words(right) & words) / len(_words(right)) >= 0.5
        for right in _options(expected["title"])
    )


def compare_gold(expected: dict[str, Any], answer: dict[str, Any]) -> dict[str, bool]:
    """Field by field, an expected event against the model's: only the fields the flyer settles."""
    checks: dict[str, bool] = {
        "title": _title_ok(expected, answer.get("title")),
        "date": answer.get("date") == expected["date"],
    }
    checks["event_type"] = answer.get("event_type") in _options(expected["event_type"])
    for name in ("end_date", "start_time", "end_time"):
        if name in expected:
            value = (answer.get(name) or "")[: 10 if name == "end_date" else 5] or None
            checks[name] = value in _options(expected[name])
    if "sessions" in expected:
        checks["sessions"] = [s.get("date") for s in answer.get("sessions") or []] == (expected["sessions"] or [])
    if "venue" in expected:
        venue = _words(answer.get("venue"))
        rights = _options(expected["venue"])  # None among them: no venue is right too (a logo, an address only)
        checks["venue"] = None in rights if not venue else any(_words(right) & venue for right in rights if right)
    if "prices" in expected:
        checks["prices"] = {p.get("amount_cop") for p in answer.get("prices") or []} == set(expected["prices"])
    if "styles" in expected:
        styles = set(answer.get("styles") or [])
        checks["styles"] = set(expected["styles"]) <= styles <= {*expected["styles"], *expected.get("styles_ok", [])}
    return checks


def _closeness(expected: dict[str, Any], answer: dict[str, Any]) -> tuple[bool, bool, int]:
    """Which answer on the expected event's date is it: the right title, then the right start, then shared words."""
    start = (answer.get("start_time") or "")[:5] or None
    shared = max(len(_words(right) & _words(answer.get("title"))) for right in _options(expected["title"]))
    return _title_ok(expected, answer.get("title")), start in _options(expected.get("start_time")), shared


def score_gold(posts: list[Item], cache: dict[str, Any]) -> Score:
    """A model's cached answers against the test set: each expected event matched to one answer on its date (an
    optional one, like a meet & greet only in a VIP pack, is neither missed nor extra)."""
    result = Score()
    for post in posts:
        entry = cache.get(post["post_id"]) or {}
        if "answer" not in entry:
            result.errors += 1
            continue
        result.seconds.append(entry["seconds"])
        left = [event for event in entry["answer"]["events"] if not event.get("is_recurring")]
        for expected in sorted(post["events"], key=lambda event: bool(event.get("optional"))):
            same_day = [event for event in left if event.get("date") == expected["date"]]
            if not same_day:
                if not expected.get("optional"):
                    result.missed += 1
                    result.notes.append(f"{post['post_id']}/{expected['id']}: missed ({expected['date']})")
                continue
            best = max(same_day, key=lambda event: _closeness(expected, event))
            left.remove(best)
            result.found += 1
            for name, same in compare_gold(expected, best).items():
                counts = result.fields.setdefault(name, [0, 0])
                counts[0] += same
                counts[1] += 1
                if not same:
                    where = f"{post['post_id']}/{expected['id']}"
                    result.notes.append(f"{where} {name}: expected {expected.get(name)}, read {best.get(name)}")
        result.extra += len(left)
        result.notes += [f"{post['post_id']}: extra {event.get('date')} {event.get('title')}" for event in left]
    return result


def run_gold(
    models: list[str],
    score_only: bool = False,
    with_ocr: bool = False,
    thinking: str | None = None,
    batch: int | None = None,
    take: int = 1,
    say: Callable[[str], None] = print,
) -> None:
    """`admin bakeoff --gold`: each model on the test set's posts it hasn't answered (unless `score_only`), scored
    against the truth; `--ocr`, with the flyer's OCR text; `--thinking`, at that thinking level (each variant cached
    apart: "<model>+ocr", "<model>+think-low"). `--batch N`: each model one post a request and N posts a request
    (batching.py, as the sweep does with config.EXTRACTION_BATCH_POSTS), scored side by side; `--take K`: another take
    of the same reading, cached apart ("+take2"), to measure how much two runs differ. A Flash model takes 20 a day:
    the rest waits in the cache for the next day."""
    if with_ocr and not ocr.available():
        say("--ocr needs the OCR engine, not in requirements.txt: pip install rapidocr onnxruntime")
        return
    posts = load_gold()
    say(f"{len(posts)} posts checked by hand ({GOLD_DIR}); answers cached in {GOLD_CACHE_DIR}")
    level_suffix = f"+think-{thinking}" if thinking else ""
    take_suffix = f"+take{take}" if take > 1 else ""
    suffix = ("+ocr" if with_ocr else "") + level_suffix + take_suffix
    batched = f"{level_suffix}+batch{batch}{take_suffix}" if batch and batch > 1 else None
    if not score_only:
        level = types.ThinkingLevel[thinking.upper()] if thinking else None
        ask = asker(lambda: config.require_env("GEMINI_API_KEY"), thinking=level)
        for model in models:
            say(f"\n{model}{suffix}:")
            run_model(
                model, posts, ask, GOLD_DIR, cache_dir=GOLD_CACHE_DIR, say=say, with_ocr=with_ocr, label=model + suffix
            )
            if batch and batched:
                say(f"\n{model}{batched}:")
                run_batched(model, posts, ask, GOLD_DIR, batch, GOLD_CACHE_DIR, say, label=model + batched)
    for model in models:
        label = model + suffix
        cache = load_cache(cache_file(label, GOLD_CACHE_DIR))
        say("\n" + score_text(label, score_gold(posts, cache), notes=40))
        _say_stale(stale_answers(posts, cache, GOLD_DIR, with_ocr), say)
        if batch and batched:
            batched_cache = load_cache(cache_file(model + batched, GOLD_CACHE_DIR))
            say("\n" + batch_score_text(model + batched, posts, batch, cache, batched_cache))
            _say_stale(stale_batched(posts, batch, batched_cache, GOLD_DIR), say)


# ---------- 5. batched extraction on the test set (batching.py, config.EXTRACTION_BATCH_POSTS) ----------
# The same posts read N to a request, scored against the truth beside the one-post reading. The sweep batches one
# account's posts, but the test set has only four accounts with two posts: those are batched together, and the rest
# with posts of other accounts, in the file's order (harder than the sweep's batches: each post carries its own
# account, dates and rules). The two kinds are scored apart too. As in the sweep, a post the shared answer leaves out
# (batching.split_answer), or every post of a request that failed, is read again alone, and counted.


def gold_batches(posts: list[Item], size: int) -> list[list[Item]]:
    """The test set in batches of `size`: each account's posts together first, then the rest `size` at a time in the
    file's order (posts of different accounts). A post left alone is read alone, as the sweep reads it."""
    by_account: dict[str, list[Item]] = {}
    for post in posts:
        by_account.setdefault(post["account"], []).append(post)
    batches: list[list[Item]] = []
    rest: list[Item] = []
    for items in by_account.values():
        for start in range(0, len(items), size):
            chunk = items[start : start + size]
            if len(chunk) > 1:
                batches.append(chunk)
            else:
                rest += chunk
    return batches + [rest[start : start + size] for start in range(0, len(rest), size)]


def _read_alone(model: str, item: Item, ask: Ask, data_dir: Path) -> dict[str, Any]:
    """One post read alone (a batch's fallback, or a post alone in its batch): its answer or error, for the cache.
    No quota left raises QuotaExhaustedError: the rest waits."""
    started = time.monotonic()
    try:
        answer = ask(model, contents_for(item, data_dir))
    except QuotaExhaustedError:
        raise
    except (ExtractionError, OSError) as error:
        return {"error": str(error)[:300]}
    return {"answer": answer.model_dump(mode="json"), "seconds": round(time.monotonic() - started, 1)}


def _confirm_no_events(
    model: str, batch: list[Item], cache: dict[str, Any], ask: Ask, data_dir: Path, say: Callable[[str], None]
) -> bool:
    """A batch answered before a shared "no event" was confirmed alone (batching.NO_EVENT, 9 Oct 2026): its posts with
    no event in the shared answer are read alone now, as the sweep would. False when no quota is left."""
    for item in batch if len(batch) > 1 else []:
        entry = cache[item["post_id"]]
        if "alone" in entry or (entry["answer"]["events"] and entry["answer"]["is_event_post"]):
            continue
        try:
            alone = _read_alone(model, item, ask, data_dir)
            cache[item["post_id"]] = {"request": entry["request"], "batch": entry["batch"], "alone": NO_EVENT, **alone}
        except QuotaExhaustedError as error:
            say(f"  no quota left today: {error}. The rest waits for another day.")
            return False
        say(f"  {item['post_id']}: no event in the shared answer, read alone")
    return True


def run_batched(
    model: str,
    posts: list[Item],
    ask: Asker,
    data_dir: Path,
    size: int,
    cache_dir: Path = GOLD_CACHE_DIR,
    say: Callable[[str], None] = print,
    label: str | None = None,
) -> None:
    """One model on the test set, `size` posts a request (gold_batches), each batch not answered yet with today's
    request: each post's answer checked as the sweep checks it, and a post left out read again alone. Each post's
    cache entry names its batch (`batch`), the shared request (`request`) and, when it was read alone, why (`alone`)."""
    path = cache_file(label or f"{model}+batch{size}", cache_dir)
    cache = load_cache(path)
    for batch in gold_batches(posts, size):
        ids = [item["post_id"] for item in batch]
        try:
            contents = batch_contents_for(batch, data_dir) if len(batch) > 1 else contents_for(batch[0], data_dir)
        except OSError as error:
            say(f"  {'+'.join(ids)}: error: {str(error)[:120]}")
            continue
        request = request_fingerprint(contents)
        if all("answer" in cache.get(i, {}) and cache[i].get("request") == request for i in ids):
            if not _confirm_no_events(model, batch, cache, ask, data_dir, say):
                break
            path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            continue
        started = time.monotonic()
        try:
            if len(batch) == 1:
                cache[ids[0]] = {"request": request, "batch": ids, **_read_alone(model, batch[0], ask, data_dir)}
                say(f"  {ids[0]}: alone")
            else:
                try:
                    answer = ask.read(model, contents, BatchAnalysis)
                    analyses, left_out = split_answer(answer, [1] * len(batch))
                except QuotaExhaustedError:
                    raise
                except (ExtractionError, OSError) as error:
                    analyses, left_out = {}, dict.fromkeys(range(len(batch)), f"falló: {str(error)[:200]}")
                seconds = round(time.monotonic() - started, 1)
                for index, item in enumerate(batch):
                    entry: dict[str, Any] = {"request": request, "batch": ids}
                    if index in analyses:
                        entry |= {"answer": analyses[index].model_dump(mode="json"), "seconds": seconds}
                    else:
                        entry |= {"alone": left_out[index], **_read_alone(model, item, ask, data_dir)}
                    cache[item["post_id"]] = entry
                alone = "".join(f", {ids[index]} read alone ({why})" for index, why in left_out.items())
                say(f"  {'+'.join(ids)}: {len(analyses)} of {len(batch)} from one request ({seconds} s){alone}")
        except QuotaExhaustedError as error:
            say(f"  no quota left today: {error}. The rest waits for another day.")
            break
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def requests_used(posts: list[Item], cache: dict[str, Any]) -> tuple[int, int, int]:
    """The requests a batched run of these posts took: (in all, shared ones, posts read alone)."""
    entries = [cache[post["post_id"]] for post in posts if post["post_id"] in cache]
    shared = {tuple(entry["batch"]) for entry in entries if len(entry.get("batch", [])) > 1}
    alone = sum(1 for entry in entries if "alone" in entry or len(entry.get("batch", [])) == 1)
    return len(shared) + alone, len(shared), alone


def batch_score_text(label: str, posts: list[Item], size: int, single: dict[str, Any], batched: dict[str, Any]) -> str:
    """The batched reading's score, its requests against one a post, and both readings on each kind of batch: posts
    of one account together (as the sweep batches them) and of different accounts."""
    in_all, shared, alone = requests_used(posts, batched)
    why = [entry["alone"] for entry in batched.values() if "alone" in entry]
    lines = [
        score_text(label, score_gold(posts, batched), notes=40),
        f"   requests: {in_all} for {len(posts)} posts ({shared} shared, {alone} read alone"
        + (f"; left out of an answer: {', '.join(sorted(set(why)))}" if why else "")
        + ")",
    ]
    batches = [batch for batch in gold_batches(posts, size) if len(batch) > 1]
    for kind, same in (("one account", True), ("different accounts", False)):
        subset = [item for batch in batches if (len({i["account"] for i in batch}) == 1) == same for item in batch]
        if subset:
            for name, cache in (("one post a request", single), (f"{size} a request", batched)):
                result = score_gold(subset, cache)
                right, compared = result.fields_right
                lines.append(
                    f"   {kind} ({len(subset)} posts), {name}: found {result.found}, missed {result.missed}, "
                    f"extra {result.extra}, F1 {result.f1:.3f}, fields right {right}/{compared}"
                )
    return "\n".join(lines)


def stale_batched(posts: list[Item], size: int, cache: dict[str, Any], data_dir: Path) -> int:
    """How many posts' cached batched answers were read with another request than today's (stale_answers' kind)."""
    stale = 0
    for batch in gold_batches(posts, size):
        try:
            contents = batch_contents_for(batch, data_dir) if len(batch) > 1 else contents_for(batch[0], data_dir)
        except OSError:
            continue
        request = request_fingerprint(contents)
        stale += sum(
            1
            for item in batch
            if "answer" in cache.get(item["post_id"], {}) and cache[item["post_id"]].get("request") != request
        )
    return stale


def _say_stale(count: int, say: Callable[[str], None]) -> None:
    if count:
        say(f"   ! {count} answers were read with another request (the prompt, the rules, a caption or the OCR text")
        say("     changed since): this score mixes readings; run without --score to ask them again")


# ---------- the command ----------


def load_picks(count: int, repick: bool, cache_dir: Path = CACHE_DIR) -> list[Item]:
    """The posts of the last bake-off, or new ones (`repick`, or another `count`): from the site's events and the
    sweeps' records."""
    path = cache_dir / "picks.json"
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not repick and saved.get("posts") == count:
        picks: list[Item] = saved["picks"]
        return picks
    events = storage.read_json(config.EVENTS_FILE, [])
    processed = sweep_state.read(config.PROCESSED_POSTS_FILE.name, {})
    picks = pick(candidates(events, processed, config.DATA_DIR), count)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"posts": count, "picks": picks}, ensure_ascii=False, indent=1), encoding="utf-8")
    return picks


def run(
    count: int, models: list[str], repick: bool = False, score_only: bool = False, say: Callable[[str], None] = print
) -> None:
    """`admin bakeoff`: pick the posts, run each model on the ones it hasn't answered (unless `score_only`), score."""
    picks = load_picks(count, repick)
    say(f"{len(picks)} posts read by Flash ({config.DATA_DIR}); answers cached in {CACHE_DIR}")
    if not score_only:
        ask = asker(lambda: config.require_env("GEMINI_API_KEY"))
        for model in models:
            say(f"\n{model}:")
            run_model(model, picks, ask, config.DATA_DIR, say=say)
    for model in models:
        cache = load_cache(cache_file(model))
        say("\n" + score_text(model, score(picks, cache)))
        _say_stale(stale_answers(picks, cache, config.DATA_DIR), say)


def discover(say: Callable[[str], None] = print) -> None:
    """`admin bakeoff --discover`: OpenRouter's free vision models now (one request, no key)."""
    reply = httpx.get(config.OPENROUTER_MODELS_URL, timeout=config.EXTERNAL_TIMEOUT_SECONDS)
    reply.raise_for_status()
    say(discover_text(free_vision_models(reply.json())))


# ---------- discover ----------


def free_vision_models(listing: dict[str, Any]) -> list[dict[str, Any]]:
    """From OpenRouter's model list (GET config.OPENROUTER_MODELS_URL): the free ones that take images, with whether
    they take structured output (`structured`, json_schema with require_parameters) and their context length."""
    found = []
    for model in listing.get("data") or []:
        pricing = model.get("pricing") or {}
        free = str(model.get("id", "")).endswith(":free") or (
            pricing.get("prompt") in ("0", 0) and pricing.get("completion") in ("0", 0)
        )
        architecture = model.get("architecture") or {}
        inputs = architecture.get("input_modalities") or []
        outputs = architecture.get("output_modalities") or ["text"]
        # Text answers only: Lyria's music models list a zero token price but are paid per clip, and answer in audio.
        if not free or "image" not in inputs or outputs != ["text"]:
            continue
        parameters = model.get("supported_parameters") or []
        found.append(
            {
                "id": model["id"],
                "structured": "structured_outputs" in parameters,
                "json_mode": "response_format" in parameters,
                "context": model.get("context_length"),
            }
        )
    return sorted(found, key=lambda item: (not item["structured"], item["id"]))


def discover_text(models: list[dict[str, Any]]) -> str:
    """The free vision models for people, marking the ones already in the list (config.EXTERNAL_PROVIDERS)."""
    listed = {model.name for provider in config.EXTERNAL_PROVIDERS for model in provider.models}
    if not models:
        return "No free model with image input on OpenRouter right now."
    lines = [f"{len(models)} free models with image input on OpenRouter (* = in config.EXTERNAL_PROVIDERS):"]
    for model in models:
        mode = "structured" if model["structured"] else "json_object" if model["json_mode"] else "no JSON mode"
        mark = "*" if model["id"] in listed else " "
        lines.append(f" {mark} {model['id']}  ({mode}, context {model['context']})")
    return "\n".join(lines)
