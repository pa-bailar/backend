"""The command line: each command starts without needing the other commands' secrets.

On GitHub only the sweep's secrets exist (the Meta app's id and secret are only in the local .env, for
refresh-token), so importing a command must never read another command's secrets.
"""

import importlib
import sys

import pytest

from pa_bailar import config


@pytest.mark.parametrize("module", ["sweep", "discover", "refresh_token"])
def test_commands_read_no_secrets_at_import(monkeypatch, module):
    def forbidden(name: str) -> str:
        raise AssertionError(f"{name} read at import time")

    monkeypatch.setattr(config, "require_env", forbidden)
    monkeypatch.delitem(sys.modules, f"pa_bailar.commands.{module}", raising=False)
    importlib.import_module(f"pa_bailar.commands.{module}")


def test_the_entry_point_imports_only_the_command_it_runs(monkeypatch):
    for name in [n for n in sys.modules if n.startswith("pa_bailar.commands.") or n == "pa_bailar.__main__"]:
        monkeypatch.delitem(sys.modules, name)
    importlib.import_module("pa_bailar.__main__")
    assert not any(name.startswith("pa_bailar.commands.") and name != "pa_bailar.commands" for name in sys.modules)
