"""The sweeps' latest state, wherever this runs.

On GitHub Actions, the workflows copy the sweep-state branch into state/ before running, so the files in
config.STATE_DIR are current. On your computer, state/ only has what local runs wrote: the sweeps' state is
read from the branch itself instead (`git fetch origin sweep-state`, then each file with `git show`), falling
back to state/ when that isn't possible (offline, or no remote).
"""

import json
import os
import subprocess
from typing import Any

from . import config, storage

BRANCH = "sweep-state"


def _on_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(config.ROOT_DIR), *args], capture_output=True, text=True, encoding="utf-8", check=False
    )


def refresh() -> bool:
    """Bring the branch up to date (on your computer). False when it couldn't: the last fetched copy is used."""
    return _on_ci() or _git("fetch", "-q", "origin", BRANCH).returncode == 0


def read(name: str, default: Any) -> Any:
    """state/<name> (e.g. "gemini_usage.json") as the latest sweep left it."""
    local = config.STATE_DIR / name
    if _on_ci():
        return storage.read_json(local, default)
    shown = _git("show", f"origin/{BRANCH}:{name}")
    if shown.returncode != 0:
        return storage.read_json(local, default)
    try:
        return json.loads(shown.stdout)
    except json.JSONDecodeError:
        return storage.read_json(local, default)
