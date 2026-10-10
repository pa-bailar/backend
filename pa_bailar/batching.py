"""Batched extraction: several posts in one Gemini request, each post's answer checked apart (the owner, 9 Oct 2026).

Flash's requests per day (20 per model) are the binding limit, not its tokens, and each post that announces events
takes one. With config.EXTRACTION_BATCH_POSTS over 1, the sweep reads the posts of one account that the triage
passed up to that many per request (pipeline/batches.py). Here, what doesn't depend on the sweep, which the bake-off
shares (bakeoff.py):

- `batch_contents`: the request. Each post is labeled with a letter (A, B, C) and comes with its own context (the
  one-post prompt's: account, dates, caption, the account's rules) and its own images, numbered across the request
  and labeled with the post ("Image 2 (post B)"); then the instructions (prompts.BATCH_EXTRACTION_PROMPT).
- `split_answer`: each post's answer as the one-post extraction would give it (a PostAnalysis, its images numbered
  from 0 again), or why it can't be trusted: no answer for it, two answers, an event citing an image that isn't its
  post's own, or no event (none listed, or is_event_post false: a "no" is final, so it's confirmed alone). An
  answer for a post the request doesn't hold makes the whole answer untrustworthy. The sweep reads each post left
  out again alone: a batch never loses a post.
"""

from dataclasses import dataclass
from datetime import datetime

from google.genai import types

from .instagram import Post
from .models import BatchAnalysis, PostAnalysis
from .prompts import BATCH_EXTRACTION_PROMPT, BATCH_POST

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Why a post's part of a batched answer isn't used (in the log and the bake-off's cache): it's read again alone.
NO_ANSWER = "sin respuesta para esta publicación"
TWO_ANSWERS = "dos respuestas para esta publicación"
OTHER_IMAGE = "un evento cita una imagen de otra publicación"
STRAY_ANSWER = "respuesta para una publicación que no está en la solicitud"
# A post the triage passed and the shared answer finds no event in: a "no" is final (the post is never read again unless
# its caption changes), so it's confirmed alone. On the test set (9 Oct 2026, Flash-Lite, two a request), the only two
# events lost by batching were such "no"s: a bar's special night read beside another account's workshops, and an
# academy's closing show; each post read alone found its event. An answer that says it isn't an event post
# (is_event_post false) is such a "no" even when it lists events: the sweep stores none of them (_store_analysis).
NO_EVENT = "sin eventos en la respuesta compartida: se confirma sola"


@dataclass(frozen=True)
class BatchItem:
    """One post of a batch, as the sweep holds it between its triage and the shared request."""

    post: Post
    published: datetime
    images: list[bytes]
    rules: str = ""  # the account's own (prompts.account_rules)
    reread: bool = False  # read before (an edited caption, the style filter's words): counted as re-analyzed


@dataclass
class BatchReading:
    """A batched extraction's result: the posts' answers by their place in the batch, the posts left out (with why),
    and the model that read them (provisional: a lighter one, as for one post)."""

    analyses: dict[int, PostAnalysis]
    left_out: dict[int, str]
    model: str
    provisional: bool


def letter(index: int) -> str:
    return LETTERS[index]


def image_ranges(image_counts: list[int]) -> list[range]:
    """Each post's images, numbered across the request: [2, 1] → range(0, 2), range(2, 3)."""
    ranges, start = [], 0
    for count in image_counts:
        ranges.append(range(start, start + count))
        start += count
    return ranges


def _numbers(images: range) -> str:
    return ", ".join(f"Image {number}" for number in images) or "none"


def batch_contents(posts: list[tuple[dict[str, str], list[bytes]]], known_events: str) -> list[types.PartUnionDict]:
    """The request for several posts: each post's context (the one-post prompt's: account, published, today, caption,
    account_rules) and its images, labeled with its letter, then the instructions. `known_events` as the one-post
    prompt lists them ("" for none)."""
    ranges = image_ranges([len(images) for _, images in posts])
    contents: list[types.PartUnionDict] = []
    for index, ((context, images), numbers) in enumerate(zip(posts, ranges, strict=True)):
        contents.append(BATCH_POST.format(letter=letter(index), images=_numbers(numbers), **context))
        for number, image in zip(numbers, images, strict=True):
            contents += [
                f"Image {number} (post {letter(index)}):",
                types.Part.from_bytes(data=image, mime_type="image/jpeg"),
            ]
    letters = ", ".join(letter(index) for index in range(len(posts)))
    contents.append(
        BATCH_EXTRACTION_PROMPT.format(count=len(posts), letters=letters, known_events=known_events or "(none)")
    )
    return contents


def split_answer(answer: BatchAnalysis, image_counts: list[int]) -> tuple[dict[int, PostAnalysis], dict[int, str]]:
    """Each post's answer, as a one-post extraction's (its own images numbered from 0), by its place in the batch; and
    the posts left out, with why: no answer, two answers, no event (none listed, or is_event_post false: confirmed
    alone, NO_EVENT), or an event citing an
    image that isn't its post's (a mix-up). Each is read again alone. An answer for a letter the request doesn't hold
    leaves every post out: the model lost track of which post is which."""
    count = len(image_counts)
    known = {letter(index): index for index in range(count)}
    found: dict[int, list[PostAnalysis]] = {}
    for entry in answer.posts:
        index = known.get(entry.post.strip().upper().removeprefix("POST ").strip())
        if index is None:
            return {}, dict.fromkeys(range(count), STRAY_ANSWER)
        found.setdefault(index, []).append(
            PostAnalysis(is_event_post=entry.is_event_post, reason=entry.reason, events=entry.events)
        )
    ranges = image_ranges(image_counts)
    analyses: dict[int, PostAnalysis] = {}
    left_out: dict[int, str] = {}
    for index in range(count):
        answers = found.get(index, [])
        if len(answers) != 1:
            left_out[index] = TWO_ANSWERS if answers else NO_ANSWER
            continue
        own = ranges[index]
        events = answers[0].events
        if not events or not answers[0].is_event_post:  # a "no" listing events is a "no" all the same (stored so)
            left_out[index] = NO_EVENT
            continue
        if any(event.image_index is not None and event.image_index not in own for event in events):
            left_out[index] = OTHER_IMAGE
            continue
        local = [
            event
            if event.image_index is None
            else event.model_copy(update={"image_index": event.image_index - own.start})
            for event in events
        ]
        analyses[index] = answers[0].model_copy(update={"events": local})
    return analyses, left_out
