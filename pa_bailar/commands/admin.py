"""admin: tools for running Pa' Bailar day to day (docs/ADMIN.md).

Usage (from the repository root):
    .venv\\Scripts\\python -m pa_bailar admin status            how the sweeps, quotas and accounts are doing
    .venv\\Scripts\\python -m pa_bailar admin status --json     the same as data (for the admin page)

None of these tools uses AI: they read what the sweeps record. On your computer they read the sweeps' latest
state from the sweep-state branch (pa_bailar/sweep_state.py).
"""

import argparse
import io
import json
import sys

from pa_bailar import status, sweep_state


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m pa_bailar admin", description=__doc__.splitlines()[0])
    tools = parser.add_subparsers(dest="tool", required=True)
    status_parser = tools.add_parser("status", help="how the sweeps, quotas and accounts are doing")
    status_parser.add_argument("--json", action="store_true", help="as data, for the admin page")
    status_parser.add_argument(
        "--no-instagram", action="store_true", help="skip the Instagram check (one Graph API call)"
    )
    args = parser.parse_args(argv)

    if args.tool == "status":
        if not sweep_state.refresh():
            print("(No se pudo traer el estado más reciente: se muestra la última copia.)", file=sys.stderr)
        result = status.collect(instagram=None if args.no_instagram else status.check_instagram)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if isinstance(sys.stdout, io.TextIOWrapper):
                sys.stdout.reconfigure(encoding="utf-8")  # emojis and accents on Windows consoles too
            print(status.markdown(result))


if __name__ == "__main__":
    main()
