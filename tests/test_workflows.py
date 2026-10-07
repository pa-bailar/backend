"""The sweep workflow's steps in a safe order (.github/workflows/daily-sweep.yml, read as text: no YAML parser here)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SWEEP = (ROOT / ".github" / "workflows" / "daily-sweep.yml").read_text(encoding="utf-8")


def step(name: str) -> int:
    """Where the step called `name` is in the workflow (it must be there, once)."""
    assert SWEEP.count(f"- name: {name}\n") == 1, name
    return SWEEP.index(f"- name: {name}\n")


def minutes(name: str) -> int:
    """A workflow-level setting in minutes (`env:` NAME: N)."""
    match = re.search(rf"^  {name}: (\d+)", SWEEP, re.MULTILINE)
    assert match, name
    return int(match.group(1))


def test_a_run_waits_for_an_open_data_pr_before_it_copies_the_site():
    """A run right after a scheduled sweep (an owner's request) used to check out the site and the images, then wait
    for that sweep's data PR: its copy lacked the PR's events, so it deleted their flyers from the images repository
    and opened a PR that conflicted with the first one for good (the bug-squash pass, 6 Oct 2026)."""
    wait = step("Make sure the last data PR merged")
    assert wait < step("Check out the site repository")
    assert wait < step("Check out the images repository")
    assert wait < step("Copy the images into the site's data")
    assert wait < step("Run the sweep")


def test_the_sweep_job_has_room_for_its_longest_run():
    """A job timeout cancels the steps after it, the state's save among them: the job's limit must hold the wait for
    an earlier data PR, the sweep step, an owner's request's wait for its own PR, and ~10 minutes for the rest
    (setup, the PR, the state). With the wait moved first (#136) the old 60 minutes didn't (the review pass, 6 Oct)."""
    job = SWEEP[SWEEP.index("\n  sweep:\n") :]
    job_limit = re.search(r"^    timeout-minutes: (\d+)", job, re.MULTILINE)
    sweep_step = job[job.index("- name: Run the sweep\n") :]
    step_limit = re.search(r"^        timeout-minutes: (\d+)", sweep_step, re.MULTILINE)
    assert job_limit and step_limit
    longest = minutes("OPEN_DATA_PR_WAIT_MINUTES") + int(step_limit.group(1)) + minutes("MERGE_TIMEOUT_MINUTES") + 10
    assert int(job_limit.group(1)) >= longest, f"the job's {job_limit.group(1)} minutes < the longest run's {longest}"
