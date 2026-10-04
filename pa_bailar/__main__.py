"""Command line: python -m pa_bailar <command> [options]

Commands:
  sweep           collect new events from the accounts in accounts.txt (what the daily workflow runs)
  discover        find dance academies among the accounts you follow (from your Instagram export)
  refresh-token   turn a Graph API Explorer token into a Page token that doesn't expire
  admin           tools for running it day to day: status, why, add-account, inbox (docs/ADMIN.md)

`python -m pa_bailar <command> --help` shows each command's options.
"""

import importlib
import sys

# Command -> module in pa_bailar.commands. Imported only when run: each command needs different secrets.
COMMANDS = {"sweep": "sweep", "discover": "discover", "refresh-token": "refresh_token", "admin": "admin"}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(0 if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help") else 2)
    command = importlib.import_module(f"pa_bailar.commands.{COMMANDS[sys.argv[1]]}")
    command.main(sys.argv[2:])


if __name__ == "__main__":
    main()
