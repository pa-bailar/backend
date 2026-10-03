"""sweep: collect one-time dance events from the accounts in accounts.txt.

Usage (from the repository root):
    .venv\\Scripts\\python -m pa_bailar sweep             # posts from the last 7 days
    .venv\\Scripts\\python -m pa_bailar sweep --days 14   # look further back
"""

import argparse
import logging
import os
from pathlib import Path

from pa_bailar import config, health, links, storage
from pa_bailar.logs import setup_logging
from pa_bailar.pipeline import AddedPost, AddPostError, RunStats, Sweep

log = logging.getLogger(__name__)


def summary_markdown(stats: RunStats) -> str:
    """Markdown tables shown on the GitHub Actions run page."""
    account_rows = [
        f"| @{account}{' (new)' if s.backfill else ''} | {'❌ fetch failed' if s.fetch_failed else s.posts_analyzed} "
        f"| {s.events_new} | {s.events_merged} | {s.pending} | {s.errors} |"
        for account, s in stats.by_account.items()
    ]
    model_rows = [
        f"| {model} | {stats.gemini_requests.get(model, 0)} | {limit.requests_per_day} |"
        for model, limit in config.MODEL_LIMITS.items()
    ]
    return "\n".join(
        [
            "## Daily sweep",
            "",
            f"{stats.posts_analyzed} posts analyzed ({stats.posts_triaged_out} ruled out by triage) · "
            f"{stats.events_new} new events · {stats.events_merged} merged into existing events · "
            f"{stats.events_discarded} discarded (recurring/undated) · {stats.provisional} provisional · "
            f"{stats.upgraded} upgraded · {stats.reanalyzed} re-analyzed (edited captions) · "
            f"{stats.pending} pending for next run · {stats.errors} errors · "
            f"{stats.events_expired} past events and {stats.flyers_removed} flyers cleaned up",
            "",
            "| Account | Posts analyzed | New events | Merged | Pending | Errors |",
            "|---|---|---|---|---|---|",
            *account_rows,
            "",
            "### Gemini requests",
            "",
            "| Model | This run | Daily limit |",
            "|---|---|---|",
            *model_rows,
            "",
        ]
    )


def run_url() -> str | None:
    """This run's page on GitHub Actions (None for local runs)."""
    parts = [os.environ.get(name) for name in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID")]
    return "{}/{}/actions/runs/{}".format(*parts) if all(parts) else None


def check_health(stats: RunStats) -> tuple[list[health.Finding], str]:
    """Compare the run with the previous ones (health.py), add it to the history, and build the report."""
    url = run_url()
    history = health.load_history()
    run = health.record_of(stats, storage.read_accounts(), url)
    today = config.now_bogota().date()
    findings = health.check(run, history, stats, today)
    run.warnings = [finding.key for finding in findings if finding.level == "warning"]
    health.save_history([*history, run])
    review = health.events_to_review(storage.load_events(), today)
    return findings, health.report_markdown(findings, review, url)


def publish_health(findings: list[health.Finding], report: str) -> None:
    """The report in the log, and for the workflow: annotations on the run page, the warning count and
    fingerprint as step outputs, the report file for the health issue and the health-check ping."""
    warnings = [finding for finding in findings if finding.level == "warning"]
    for finding in findings:
        log.log(logging.WARNING if finding.level == "warning" else logging.INFO, "Health: %s", finding.text)
    if os.environ.get("GITHUB_ACTIONS"):
        for finding in warnings:
            print(f"::warning title=Sweep health::{finding.text}", flush=True)
    if output_file := os.environ.get("GITHUB_OUTPUT"):
        with Path(output_file).open("a", encoding="utf-8") as file:
            file.write(f"warnings={len(warnings)}\nfingerprint={health.fingerprint(findings)}\n")
    if report_file := os.environ.get("HEALTH_REPORT_FILE"):
        Path(report_file).write_text(report, encoding="utf-8")


def lookback_days(value: str) -> int:
    """--days: a whole number from 1 to MAX_LOOKBACK_DAYS."""
    try:
        days = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {value!r}") from None
    if not 1 <= days <= config.MAX_LOOKBACK_DAYS:
        raise argparse.ArgumentTypeError(f"must be between 1 and {config.MAX_LOOKBACK_DAYS}, got {days}")
    return days


def added_post_markdown(added: AddedPost) -> str:
    """The admin tools' answer after adding a post by hand, in Spanish."""
    lines: list[str] = []
    if added.public:
        lines.append(
            "📄 La leí desde su página pública: la API de Instagram no la entrega (cuenta personal, colaboración "
            "o límite)."
        )
    if not added.readable:
        lines.append(
            f"ℹ️ La API no puede leer @{added.account} (cuenta personal o privada): no entra en los barridos. "
            "Sus próximos eventos se agregan así, con el enlace."
        )
    if added.account_added:
        lines.append(
            f"➕ @{added.account} no estaba en los barridos: la agregué (sus publicaciones de los últimos "
            f"{config.BACKFILL_DAYS} días se leen en el próximo barrido)."
        )
    light = " Flash-Lite (provisional: se relee con Flash)" if added.provisional else f" {added.model}"
    if added.outcome in ("event", "merged") and added.events:
        verb = "Se unió a" if added.outcome == "merged" else "Publiqué"
        lines.append(f"✅ **{verb} {len(added.events)} evento(s)**, leído con{light}:")
        lines += [f"- [{e.title}]({links.event_url(e.id)}) · {e.date}" for e in added.events]
        lines.append("")
        lines.append("Aparece en el sitio cuando termina de publicarse (unos minutos).")
    elif added.outcome == "discarded":
        lines.append(f"❌ Gemini la leyó como evento, pero no es publicable: {added.reason}")
    else:
        lines.append(f"❌ Gemini dice que no anuncia un evento: “{added.reason}”")
    return "\n".join(lines) + "\n"


def add_post(link: str, account: str | None) -> None:
    """`sweep --post`: publish one post by hand. The answer goes to ADMIN_REPORT_FILE (the workflow comments it
    on the admin issue) and the log; a failure to add it isn't a failed run (the answer says why)."""
    try:
        added = Sweep(lookback_days=config.DEFAULT_LOOKBACK_DAYS).add_post(link, account)
        report = added_post_markdown(added)
    except AddPostError as error:
        report = f"❌ {error}\n"
    logging.info("\n%s", report)
    if report_file := os.environ.get("ADMIN_REPORT_FILE"):
        Path(report_file).write_text(report, encoding="utf-8")


def is_broken(stats: RunStats) -> bool:
    """A run that must show as failed (and alert): no account could be read, and not because Instagram's rate
    limit stopped it. Failed posts are retried next run, and a rate-limited run just waits for the next one;
    the health checks warn when either keeps happening."""
    return bool(stats.accounts) and stats.failed_accounts == stats.accounts and not stats.rate_limited


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m pa_bailar sweep", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--days",
        type=lookback_days,
        default=config.DEFAULT_LOOKBACK_DAYS,
        help=f"only analyze posts published in the last N days (default {config.DEFAULT_LOOKBACK_DAYS}, "
        f"at most {config.MAX_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--all", action="store_true", help="read every account now, not only those whose turn it is (once a day)"
    )
    parser.add_argument("--post", help="add one post by hand instead (its Instagram link): `admin add-post`")
    parser.add_argument("--account", help="with --post: the @account, if the link doesn't say it")
    args = parser.parse_args(argv)
    setup_logging()

    if args.post:
        add_post(args.post, links.account_name(args.account) if args.account else None)
        return

    stats = Sweep(lookback_days=args.days, all_accounts=args.all).run()

    logging.info(
        "\nDone: %s accounts, %s posts analyzed (%s ruled out by triage), %s new events, %s merged, "
        "%s discarded, %s provisional, %s upgraded, %s pending, %s errors. Gemini requests: %s",
        stats.accounts,
        stats.posts_analyzed,
        stats.posts_triaged_out,
        stats.events_new,
        stats.events_merged,
        stats.events_discarded,
        stats.provisional,
        stats.upgraded,
        stats.pending,
        stats.errors,
        stats.gemini_requests or "none",
    )
    findings, report = check_health(stats)
    publish_health(findings, report)
    if summary_file := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary_file).open("a", encoding="utf-8") as file:
            file.write(report + "\n" + summary_markdown(stats))  # health first: what needs a look

    if is_broken(stats):
        raise SystemExit("Every account failed. Check the logs above.")


if __name__ == "__main__":
    main()
