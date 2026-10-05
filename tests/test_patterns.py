"""The shapes the admin tools accept (patterns.py) against the examples the admin page's tests check too
(tests/fixtures/patterns.json, admin-web/test/patterns.test.mjs): the two languages can't drift apart."""

import json
import re
from pathlib import Path

import pytest

from pa_bailar import inbox, links, patterns, stories

EXAMPLES = json.loads((Path(__file__).parent / "fixtures" / "patterns.json").read_text(encoding="utf-8"))


def is_event_id(text: str) -> bool:
    return bool(inbox.EVENT_ID.fullmatch(text)) and len(text) <= inbox.EVENT_ID_MAX


ACCEPTS = {
    "account": lambda text: bool(re.fullmatch(patterns.HANDLE, text)),
    "post_link": lambda text: links.post_code(text) is not None,
    "story_id": stories.is_story_id,
    "event_id": is_event_id,
    "upload_id": lambda text: bool(re.fullmatch(patterns.UPLOAD_ID, text)),
}


def examples(verdict: str) -> list[tuple[str, str]]:
    return [(kind, text) for kind in ACCEPTS for text in EXAMPLES[kind].get(verdict, [])]


@pytest.mark.parametrize(("kind", "text"), examples("good") + examples("python_only"))
def test_the_inbox_accepts(kind, text):
    assert ACCEPTS[kind](text)


@pytest.mark.parametrize(("kind", "text"), examples("bad"))
def test_the_inbox_refuses(kind, text):
    assert not ACCEPTS[kind](text)


def test_every_kind_has_examples_of_both():
    assert all(EXAMPLES[kind]["good"] and EXAMPLES[kind]["bad"] for kind in ACCEPTS)
