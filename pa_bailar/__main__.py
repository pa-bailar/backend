"""Command line: python -m pa_bailar <command> [options]

Commands:
  sweep           collect new events from the accounts in accounts.txt (what the daily workflow runs)
  discover        find dance academies among the accounts you follow (from your Instagram export)
  refresh-token   turn a Graph API Explorer token into a Page token that doesn't expire

`python -m pa_bailar <command> --help` shows each command's options.
"""

import sys

from .commands import discover, refresh_token, sweep

COMMANDS = {"sweep": sweep.main, "discover": discover.main, "refresh-token": refresh_token.main}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(0 if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help") else 2)
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
