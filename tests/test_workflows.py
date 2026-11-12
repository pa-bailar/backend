"""The sweep workflow's steps in a safe order (.github/workflows/daily-sweep.yml, read as text: no YAML parser here)."""

import re
from pathlib import Path

from pa_bailar import config

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


def test_the_wait_lists_the_site_s_open_prs_without_a_search():
    """`gh pr list --label` is a search, and the workflow's token searches only its own repository: the wait saw no
    data PR, so sweeps ran on past five unmerged ones and their events never reached the site (10–17 Oct 2026)."""
    job = SWEEP[step("Make sure the last data PR merged") :]
    lines = job[: job.index("\n      - ", 1)].splitlines()
    wait = "\n".join(line for line in lines if not line.lstrip().startswith("#"))  # the commands, not the comments
    assert "gh pr list" not in wait and "search/" not in wait
    assert 'gh api "repos/$SITE_OWNER/$SITE_REPO/pulls?state=open' in wait


def test_the_steps_that_keep_progress_need_the_wait_to_have_passed():
    """When the wait for an earlier data PR fails, nothing was checked out: a step that runs unless cancelled (to keep
    a failed sweep's progress) would fail in turn on folders that aren't there (the review pass, 7 Oct)."""
    job = SWEEP[SWEEP.index("\n  sweep:\n") :]
    after_wait = job[job.index("- name: Make sure the last data PR merged\n") :]
    assert "        id: wait\n" in after_wait
    conditions = re.findall(r"^        if: \$\{\{ !cancelled\(\)(.*)\}\}", after_wait, re.MULTILINE)
    assert conditions, "no step runs unless cancelled?"
    for condition in conditions:
        assert condition.startswith(" && steps.wait.outcome == 'success'"), condition


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


def test_no_workflow_pushes_to_main_accounts_go_through_the_bots_pr():
    """main's ruleset takes changes only through a pull request with `ci` (enforced since the backend went public, 6 Oct
    2026). Both workflows that add an account pushed accounts.txt to main, were refused, and every account added with
    the admin tools since then was lost (the admin inbox's /cuenta, 23 Oct). They save it through save-accounts now,
    whose PR the bot opens (one opened with the workflow's own token would start no `ci`, so it could never merge)."""
    workflows = ROOT / ".github" / "workflows"
    for workflow, save in (
        (workflows / "admin.yml", "Save the added account"),
        (workflows / "daily-sweep.yml", "Save an account added by hand"),
    ):
        text = workflow.read_text(encoding="utf-8")
        steps = re.split(r"\n      - (?=name: )", text)
        pushes_to_main = [s.split("\n")[0] for s in steps if re.search(r"git push\b[^\n]*\bmain\b", s)]
        # The images go to main of their own repository, which has no ruleset (backend ARCHITECTURE §10.2).
        assert set(pushes_to_main) <= {"name: Save the images to their repository"}, (workflow.name, pushes_to_main)
        step_ = next(s for s in steps if s.startswith(f"name: {save}\n"))
        assert "uses: ./.github/actions/save-accounts\n" in step_, workflow.name
    action = (ROOT / ".github" / "actions" / "save-accounts" / "action.yml").read_text(encoding="utf-8")
    opened = action[action.index("- name: Open the pull request") :]
    assert "GH_TOKEN: ${{ steps.app.outputs.token }}" in opened and "github.token" not in opened
    assert "gh pr merge" in opened and "--auto" in opened
    assert not re.search(r"git push\b[^\n]*\bmain\b", action)


def test_cron_job_org_starts_every_sweep_and_github_schedules_none():
    """Every sweep, 3:00 included, is started by cron-job.org (the owner, 9 Oct 2026: GitHub's own schedule never fired
    here while the repository was private, and it starts late or drops runs). A `schedule:` trigger next to a
    cron-job.org job would run that sweep twice."""
    assert "schedule:" not in SWEEP
    assert config.SWEEP_TRIGGER == "cron-job.org"
    assert config.SWEEP_TIMES == ("03:00", "06:30", "21:00")


def wait_step_script() -> str:
    """The wait's commands, as the runner gets them (bash -e), with no pause between its checks."""
    job = SWEEP[step("Make sure the last data PR merged") :]
    job = job[: job.index("\n      - ", 1)]
    lines = job[job.index("run: |\n") + len("run: |\n") :].splitlines()
    script = []
    for line in lines:
        if line and not line.startswith(" " * 10):  # past the block: the next step's comments
            break
        script.append(line[10:])
    return "\n".join(script).replace("sleep 30", "sleep 0")


def bash() -> str:
    """The runner's shell: bash; on Windows, Git's (`bash` there can be WSL's)."""
    import os
    import shutil

    git = shutil.which("git")
    if os.name == "nt" and git:
        found = [folder / "bin" / "bash.exe" for folder in Path(git).resolve().parents]
        return str(next(path for path in found if path.exists()))
    return "bash"


def run_wait(tmp_path: Path, gh_answers: list[str], minutes: int) -> tuple[int, str]:
    """Run the wait with a fake `gh` that gives these answers in turn ("fail" for an error; the last repeats)."""
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    answers = tmp_path / "answers"
    answers.write_text("\n".join(gh_answers) + "\n", encoding="utf-8", newline="\n")
    fake = bin_dir / "gh"
    count, given = (tmp_path / "count").as_posix(), answers.as_posix()
    fake.write_text(
        "#!/bin/bash\n"
        f'n=$(cat "{count}" 2>/dev/null || echo 0); echo $((n + 1)) > "{count}"\n'
        f'answer=$(sed -n "$((n + 1))p" "{given}"); [ -n "$answer" ] || answer=$(tail -n 1 "{given}")\n'
        'if [ "$answer" = fail ]; then echo "HTTP 502" >&2; exit 1; fi\n'
        'if [ "$answer" != none ]; then echo "$answer"; fi\n',
        encoding="utf-8",
        newline="\n",
    )
    fake.chmod(0o755)
    script = tmp_path / "wait.sh"
    script.write_text(wait_step_script(), encoding="utf-8", newline="\n")
    report = tmp_path / "health.md"
    env = {
        "PATH": f"{bin_dir.as_posix()}:/usr/bin:/bin",
        "SITE_OWNER": "pa-bailar",
        "SITE_REPO": "pa-bailar.github.io",
        "OPEN_DATA_PR_WAIT_MINUTES": str(minutes),
        "HEALTH_REPORT_FILE": report.as_posix(),
    }
    done = subprocess.run([bash(), "-e", script.as_posix()], env=env, capture_output=True, text=True, check=False)
    return done.returncode, report.read_text(encoding="utf-8") if report.exists() else ""


def test_the_wait_tries_again_when_githubs_api_fails(tmp_path):
    """12 Nov 2026: the step runs under bash -e, so one failed call to GitHub's API ended it, and with it the whole
    sweep (lost sweeps aren't made up)."""
    code, report = run_wait(tmp_path, ["fail", "fail", "none"], minutes=20)
    assert code == 0 and report == ""
    assert (tmp_path / "count").read_text().strip() == "3"


def test_the_wait_tells_an_api_that_never_answers_from_an_open_pr(tmp_path):
    code, report = run_wait(tmp_path / "api", ["fail"], minutes=0)
    assert code == 1 and "didn't list the site repository's pull requests" in report
    code, report = run_wait(tmp_path / "pr", ["https://github.com/pa-bailar/pa-bailar.github.io/pull/1"], minutes=0)
    assert code == 1 and "A data PR has not merged" in report and "/pull/1" in report


def test_an_added_account_goes_on_main_as_it_is_after_an_earlier_accounts_pr(tmp_path):
    """12 Nov 2026: every admin addition goes at the same spot of accounts.txt, so a second accounts PR opened before
    the first merged, or from a copy older than main (a sweep's, taken when it started), conflicted and never merged,
    while its answer said "Agregué". The PR now waits for an earlier one and is built on main as it is."""
    import os
    import subprocess

    no_crlf = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.autocrlf", "GIT_CONFIG_VALUE_0": "false"}

    def git(*args: str, cwd: Path) -> str:  # as on the runner: no line-ending conversion (Windows' default)
        done = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, env=os.environ | no_crlf
        )
        return done.stdout

    seed = tmp_path / "seed"
    seed.mkdir()
    git("init", "-q", "-b", "main", cwd=seed)
    (seed / "accounts.txt").write_text("vieja\n# Added with the admin tools\n", encoding="utf-8", newline="\n")
    git("add", "accounts.txt", cwd=seed)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed", cwd=seed)
    origin = tmp_path / "origin.git"
    git("clone", "-q", "--bare", seed.as_posix(), origin.as_posix(), cwd=tmp_path)
    run_copy = tmp_path / "run"  # the run's copy, shallow like actions/checkout's
    git("clone", "-q", "--depth=1", origin.as_uri(), run_copy.as_posix(), cwd=tmp_path)

    other = tmp_path / "other"  # meanwhile an earlier accounts PR merges: "uno" at the section's end
    git("clone", "-q", origin.as_posix(), other.as_posix(), cwd=tmp_path)
    with (other / "accounts.txt").open("a", encoding="utf-8", newline="\n") as file:
        file.write("uno\n")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "add uno", cwd=other)
    git("push", "-q", "origin", "main", cwd=other)

    with (run_copy / "accounts.txt").open("a", encoding="utf-8", newline="\n") as file:
        file.write("dos\n")  # this run's addition, at the same spot

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    log = calls.as_posix()
    (bin_dir / "gh").write_text(  # an earlier accounts PR open at first, then merged
        f'#!/bin/bash\necho x >> "{log}"\n[ "$(wc -l < "{log}")" -ge 2 ] && echo 0 || echo 1\n',
        encoding="utf-8",
        newline="\n",
    )
    (bin_dir / "gh").chmod(0o755)
    script = ROOT / ".github" / "actions" / "save-accounts" / "on-main.sh"
    pr_copy = tmp_path / "pr"
    env = {
        "PATH": f"{bin_dir.as_posix()}:/usr/bin:/bin:/mingw64/bin",
        "GITHUB_REPOSITORY": "pa-bailar/backend",
        "SAVE_ACCOUNTS_PAUSE_SECONDS": "0",
        "HOME": tmp_path.as_posix(),
    } | no_crlf
    done = subprocess.run(
        [bash(), script.as_posix(), "accounts/run-1-1", pr_copy.as_posix()],
        cwd=run_copy,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert len(calls.read_text().splitlines()) == 2  # it waited for the earlier PR
    assert (pr_copy / "accounts.txt").read_text(encoding="utf-8").splitlines() == [
        "vieja",
        "# Added with the admin tools",
        "uno",
        "dos",
    ]
    added = [line for line in git("diff", "-U0", "HEAD", cwd=pr_copy).splitlines() if line.startswith("+")]
    assert added == ["+++ b/accounts.txt", "+dos"]  # only this run's line: no conflict with main
