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


# ---------- limits: one number for the inbox, the sweep, the admin page and the sweep workflow ----------

ROOT = Path(__file__).parents[1]


def test_the_limits_are_the_ones_the_admin_pages_tests_check():
    assert EXAMPLES["limits"] == {"max_screenshots": patterns.MAX_SCREENSHOTS, "notes_max": patterns.NOTES_MAX}
    assert inbox.MAX_SCREENSHOTS == stories.MAX_SCREENSHOTS == patterns.MAX_SCREENSHOTS
    assert inbox.NOTES_MAX == patterns.NOTES_MAX


def test_the_sweep_workflow_checks_its_inputs_with_the_same_limits():
    """The workflow's shell can't import patterns.py: its regex for the `story` input and its event id length must
    say the same."""
    workflow = (ROOT / ".github" / "workflows" / "daily-sweep.yml").read_text(encoding="utf-8")
    story = re.compile(re.search(r'\[\[ "\$STORY" =~ (.+?) \]\]', workflow).group(1))
    upload = "0123456789abcdef0123456789abcdef"
    assert re.fullmatch(patterns.UPLOAD_ID, upload)
    assert story.fullmatch(" ".join([upload] * patterns.MAX_SCREENSHOTS))
    assert not story.fullmatch(" ".join([upload] * (patterns.MAX_SCREENSHOTS + 1)))
    assert f"story must be 1 to {patterns.MAX_SCREENSHOTS} upload ids" in workflow
    assert f'"${{#HIDE}}" -le {patterns.EVENT_ID_MAX}' in workflow
