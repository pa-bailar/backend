"""sweep_state: the sweeps' state from the sweep-state branch on your computer, from state/ on GitHub Actions. Git
runs only against repositories made in a temporary folder (no network)."""

import json
import subprocess

import pytest

from pa_bailar import config, sweep_state


@pytest.fixture(autouse=True)
def local_state(isolated_files, monkeypatch):
    """state/ in the temporary folder, and not on GitHub Actions unless a test says so."""
    monkeypatch.setattr(config, "STATE_DIR", isolated_files / "state")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    (isolated_files / "state").mkdir()
    return isolated_files / "state"


def shown(returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["git"], returncode=returncode, stdout=stdout, stderr="")


def no_git(*args: str) -> subprocess.CompletedProcess[str]:
    raise AssertionError(f"git {' '.join(args)} on GitHub Actions")


def test_on_github_actions_the_local_copy_is_current(local_state, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(sweep_state, "_git", no_git)
    (local_state / "gemini_usage.json").write_text('{"day": "2026-10-04"}', encoding="utf-8")

    assert sweep_state.refresh()
    assert sweep_state.read("gemini_usage.json", {}) == {"day": "2026-10-04"}
    assert sweep_state.read("run_history.json", []) == []


def test_on_your_computer_the_branch_wins_over_the_local_copy(local_state, monkeypatch):
    calls = []

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return shown(0, '{"from": "branch"}')

    monkeypatch.setattr(sweep_state, "_git", git)
    (local_state / "accounts.json").write_text('{"from": "local"}', encoding="utf-8")

    assert sweep_state.read("accounts.json", {}) == {"from": "branch"}
    assert calls == [("show", "origin/sweep-state:accounts.json")]


@pytest.mark.parametrize("answer", [shown(128), shown(0, "not json")], ids=["no branch", "not json"])
def test_without_a_readable_branch_the_local_copy_is_used(answer, local_state, monkeypatch):
    monkeypatch.setattr(sweep_state, "_git", lambda *args: answer)
    (local_state / "accounts.json").write_text('{"from": "local"}', encoding="utf-8")

    assert sweep_state.read("accounts.json", {}) == {"from": "local"}
    assert sweep_state.read("run_history.json", ["default"]) == ["default"]  # nor a local copy


@pytest.mark.parametrize(("returncode", "fresh"), [(0, True), (1, False)])
def test_refresh_says_whether_the_branch_could_be_fetched(returncode, fresh, monkeypatch):
    calls = []
    monkeypatch.setattr(sweep_state, "_git", lambda *args: calls.append(args) or shown(returncode))

    assert sweep_state.refresh() is fresh
    assert calls == [("fetch", "-q", "origin", "sweep-state")]


def git(*args: str, cwd) -> None:
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_it_reads_a_real_branch_after_fetching_it(tmp_path, monkeypatch):
    """A clone whose origin got a newer sweep-state after it was made: refresh, then read the new state."""
    origin, clone = tmp_path / "origin", tmp_path / "clone"
    origin.mkdir()
    git("init", "-q", "-b", "main", cwd=origin)
    git("commit", "-q", "--allow-empty", "-m", "start", cwd=origin)
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    git("switch", "-q", "--orphan", "sweep-state", cwd=origin)
    (origin / "run_history.json").write_text(json.dumps([{"events_new": 3}]), encoding="utf-8")
    git("add", "run_history.json", cwd=origin)
    git("commit", "-q", "-m", "state", cwd=origin)
    monkeypatch.setattr(config, "ROOT_DIR", clone)

    assert sweep_state.read("run_history.json", []) == []  # not fetched yet: no branch, no local copy
    assert sweep_state.refresh()
    assert sweep_state.read("run_history.json", []) == [{"events_new": 3}]
