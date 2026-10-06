"""The sweep workflow's steps in a safe order (.github/workflows/daily-sweep.yml, read as text: no YAML parser here)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SWEEP = (ROOT / ".github" / "workflows" / "daily-sweep.yml").read_text(encoding="utf-8")


def step(name: str) -> int:
    """Where the step called `name` is in the workflow (it must be there, once)."""
    assert SWEEP.count(f"- name: {name}\n") == 1, name
    return SWEEP.index(f"- name: {name}\n")


def test_a_run_waits_for_an_open_data_pr_before_it_copies_the_site():
    """A run right after a scheduled sweep (an owner's request) used to check out the site and the images, then wait
    for that sweep's data PR: its copy lacked the PR's events, so it deleted their flyers from the images repository
    and opened a PR that conflicted with the first one for good (the bug-squash pass, 6 Oct 2026)."""
    wait = step("Make sure the last data PR merged")
    assert wait < step("Check out the site repository")
    assert wait < step("Check out the images repository")
    assert wait < step("Copy the images into the site's data")
    assert wait < step("Run the sweep")
