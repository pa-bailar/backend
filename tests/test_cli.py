"""The command line: each command starts without needing the other commands' secrets.

On GitHub only the sweep's secrets exist (the Meta app's id and secret are only in the local .env, for
refresh-token), so importing a command must never read another command's secrets.
"""

import argparse
import importlib
import sys

import pytest

from pa_bailar import config
from pa_bailar.commands.sweep import lookback_days


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


@pytest.mark.parametrize("value", ["0", "31", "-3", "abc", "7.5"])
def test_sweep_rejects_lookbacks_outside_the_limit(value):
    with pytest.raises(argparse.ArgumentTypeError):
        lookback_days(value)


def test_sweep_accepts_lookbacks_up_to_the_limit():
    assert lookback_days("1") == 1 and lookback_days(str(config.MAX_LOOKBACK_DAYS)) == config.MAX_LOOKBACK_DAYS
