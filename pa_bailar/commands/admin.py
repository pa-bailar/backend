"""admin: tools for running Pa' Bailar day to day (docs/ADMIN.md).

Usage (from the repository root):
    .venv\\Scripts\\python -m pa_bailar admin status            how the sweeps, quotas and accounts are doing
    .venv\\Scripts\\python -m pa_bailar admin status --json     the same as data (for the admin page)
    .venv\\Scripts\\python -m pa_bailar admin why <link>        why a post's event is, or isn't, on the site
    .venv\\Scripts\\python -m pa_bailar admin add-account @x    add an account to the sweeps
    .venv\\Scripts\\python -m pa_bailar admin inbox             answer an admin issue (the admin workflow)
Adding a post is `python -m pa_bailar sweep --post <link>`: it needs Gemini and writes the site's data.

None of these tools uses AI: they read what the sweeps record. On your computer they read the sweeps' latest
state from the sweep-state branch (pa_bailar/sweep_state.py).
"""

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pa_bailar import config, inbox, links, public_post, status, storage, sweep_state, why

if TYPE_CHECKING:
    from pa_bailar.instagram import InstagramClient


def _instagram() -> "InstagramClient":
    from pa_bailar.instagram import InstagramClient  # only when needed: it reads the Meta secrets

    return InstagramClient.from_env()


def run_why(link: str, account: str | None) -> why.Diagnosis:
    client = None
    with contextlib.suppress(SystemExit):  # no Meta secrets: the answer skips the Instagram check
        client = _instagram()
    fetch = (lambda name: client.fetch_recent_posts(name, limit=config.ADMIN_POST_SEARCH)) if client else None
    return why.diagnose(link, account, fetch_posts=fetch, author_of=public_author)


def public_author(code: str) -> str | None:
    """Who published a post, from its public page (public_post.py); None if it can't be read."""
    try:
        return public_post.fetch_public_post(code)[0]
    except public_post.PublicPostError:
        return None


def run_add_account(account: str) -> str:
    """Add an account after checking Instagram can read it. The answer, in Spanish."""
    from pa_bailar.instagram import InstagramError

    if account in storage.read_accounts():
        return f"@{account} ya está en los barridos."
    try:
        profile = _instagram().fetch_profile(account, recent_posts=1)
    except InstagramError as error:
        return (
            f"No pude leer @{account} en Instagram ({error}). La API solo ve cuentas de empresa o creador: si es "
            "personal o privada, no se puede barrer."
        )
    storage.add_account(account)
    name = profile.get("name") or account
    return (
        f"✅ Agregué @{account} ({name}) a los barridos. En el próximo barrido se leen sus publicaciones de los "
        f"últimos {config.BACKFILL_DAYS} días."
    )


def answer(request: inbox.Request) -> tuple[str, bool]:
    """(reply in Markdown, done?) for an inbox request. Not done: add-post continues in the sweep workflow."""
    if request.action == "status":
        return status.markdown(status.collect()), True
    if request.action == "why" and request.link:
        return why.markdown(run_why(request.link, request.account)), True
    if request.action == "add-account" and request.account:
        return run_add_account(request.account), True
    if request.action == "add-post" and request.link:
        target = f" de @{request.account}" if request.account else ""
        verb = "volver a leer" if request.again else "leer"
        return (
            f"⏳ Voy a {verb} la publicación{target} para publicarla: te respondo aquí en unos minutos (si hay un "
            "barrido en curso, espera a que termine).",
            False,
        )
    return inbox.HELP, True


def _write_outputs(**values: str) -> None:
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as file:
            for name, value in values.items():
                file.write(f"{name}={(value.splitlines() or [''])[0]}\n")  # one line: no injected outputs


def _utf8_stdout() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")  # emojis and accents on Windows consoles too


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m pa_bailar admin", description=__doc__.splitlines()[0])
    tools = parser.add_subparsers(dest="tool", required=True)
    status_parser = tools.add_parser("status", help="how the sweeps, quotas and accounts are doing")
    status_parser.add_argument("--json", action="store_true", help="as data, for the admin page")
    status_parser.add_argument(
        "--no-instagram", action="store_true", help="skip the Instagram check (one Graph API call)"
    )
    why_parser = tools.add_parser("why", help="why a post's event is, or isn't, on the site")
    why_parser.add_argument("link", help="the post's Instagram link")
    why_parser.add_argument("--account", help="the @account, if the link doesn't say it")
    why_parser.add_argument("--json", action="store_true", help="as data")
    account_parser = tools.add_parser("add-account", help="add an account to the sweeps")
    account_parser.add_argument("account", help="@account or its profile link")
    tools.add_parser("inbox", help="answer the admin issue in INBOX_TEXT (the admin workflow)")
    args = parser.parse_args(argv)
    _utf8_stdout()
    if not sweep_state.refresh():
        print("(No se pudo traer el estado más reciente: se usa la última copia.)", file=sys.stderr)

    if args.tool == "status":
        result = status.collect(instagram=None if args.no_instagram else status.check_instagram)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else status.markdown(result))
    elif args.tool == "why":
        account = links.account_name(args.account) if args.account else None
        diagnosis = run_why(args.link, account)
        print(json.dumps(diagnosis.to_dict(), ensure_ascii=False, indent=2) if args.json else why.markdown(diagnosis))
    elif args.tool == "add-account":
        account = links.account_name(args.account)
        print(run_add_account(account) if account else f"“{args.account}” no es un nombre de cuenta válido.")
    elif args.tool == "inbox":
        # A comment, or a new issue's title and body (the admin workflow passes them as environment variables).
        issue = f"{os.environ.get('ISSUE_TITLE', '')}\n\n{os.environ.get('ISSUE_BODY', '')}"
        text = os.environ.get("COMMENT_BODY") or issue
        request = inbox.parse(text)
        reply, done = answer(request)
        Path(os.environ.get("INBOX_REPLY", "reply.md")).write_text(reply, encoding="utf-8")
        _write_outputs(
            action=request.action,
            link=request.link or "",
            account=request.account or "",
            again=str(request.again).lower(),
            done=str(done).lower(),
        )
        print(reply)


if __name__ == "__main__":
    main()
