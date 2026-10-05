"""sweep: collect one-time dance events from the accounts in accounts.txt.

Usage (from the repository root):
    .venv\\Scripts\\python -m pa_bailar sweep             # posts from the last 7 days
    .venv\\Scripts\\python -m pa_bailar sweep --days 14   # look further back (at most 30)
    .venv\\Scripts\\python -m pa_bailar sweep --all       # every account now, not only those whose turn it is
Adding one post by hand (the admin tools' Agregar, docs/ADMIN.md) is `sweep --post <link> [--account @x] [--again]`.
A story from its screenshots ("Agregar historia") is `sweep --story <id> [<id>…] [--story-dir stories]
[--account @x] [--notes "…"]`: the sweep workflow downloads them from the admin page first, as <id>.jpg and
<id>.json in --story-dir. `sweep --hide-story story-<hash>` takes one off the site again ("Ocultar historia").
"""

import argparse
import json
import logging
import os
from datetime import date
from pathlib import Path

from pa_bailar import config, health, links, storage, stories
from pa_bailar.logs import setup_logging
from pa_bailar.models import StoredEvent
from pa_bailar.pipeline import AddedPost, AddedStory, AddPostError, HiddenStory, RunStats, Sweep
from pa_bailar.status import moment_label
from pa_bailar.text import MONTHS, WEEKDAYS, clock, event_dates_label

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


def _event_line(event: StoredEvent) -> str:
    return f"- [{event.title}]({links.event_url(event.id)}) · {_dates(event)}"


def _dates(event: StoredEvent) -> str:
    """ "2026-11-13", "13–15 nov 2026", or a workshop series' sessions: "4 sesiones: 8, 22, 29 nov y 6 dic"."""
    return event_dates_label(event.date, event.end_date, event.session_dates)


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
    # Provisional reads are upgraded to Flash by the sweeps, which only see accounts the API can read.
    upgrade = "provisional: se relee con Flash" if added.readable and not added.public else "Flash no tenía cuota"
    light = f" Flash-Lite ({upgrade})" if added.provisional else f" {added.model}"
    if added.unchanged:
        lines.append(
            "ℹ️ Ya la había leído y no ha cambiado: no la leí de nuevo (no gasté cuota de Gemini). Para leerla "
            "otra vez (por ejemplo, si quedó con datos equivocados): **Volver a leer**."
        )
    if added.unchanged and added.outcome in ("event", "merged"):
        if added.events:
            lines.append(f"✅ **Ya está en el sitio** ({len(added.events)} evento(s)):")
            lines += [_event_line(e) for e in added.events]
        else:
            lines.append("✅ Su evento ya pasó: sale del sitio después de su fecha.")
    elif added.outcome in ("event", "merged") and added.events:
        verb = "Se unió a" if added.outcome == "merged" else "Publiqué"
        lines.append(f"✅ **{verb} {len(added.events)} evento(s)**, leído con{light}:")
        lines += [_event_line(e) for e in added.events]
        lines.append("")
        lines.append("Aparece en el sitio cuando termina de publicarse (unos minutos).")
    elif added.outcome == "discarded":
        lines.append(f"❌ Gemini la leyó como evento, pero no es publicable: {added.reason}")
    else:
        lines.append(f"❌ Gemini dice que no anuncia un evento: “{added.reason}”")
    return "\n".join(lines) + "\n"


def add_post(link: str, account: str | None, again: bool = False) -> None:
    """`sweep --post`: publish one post by hand (`--again`: read it again even if it hasn't changed). The answer
    goes to ADMIN_REPORT_FILE (the workflow comments it on the admin issue) and the log; a failure to add it
    isn't a failed run (the answer says why)."""
    try:
        added = Sweep(lookback_days=config.DEFAULT_LOOKBACK_DAYS).add_post(link, account, again=again)
        report = added_post_markdown(added)
    except AddPostError as error:
        report = f"❌ {error}\n"
    logging.info("\n%s", report)
    if report_file := os.environ.get("ADMIN_REPORT_FILE"):
        Path(report_file).write_text(report, encoding="utf-8")


# ---------- a story (stories.py): the receipt, and hiding it ----------


def _day(event: StoredEvent) -> str:
    """ "sábado 10 oct 2026", or the range of an event over several days, or a workshop series' sessions."""
    if event.end_date or not event.date:
        return _dates(event)
    day = date.fromisoformat(event.date)
    return f"{WEEKDAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]} {day.year}"


def _story_event_line(event: StoredEvent) -> str:
    parts = [_day(event)]
    if event.start_time:
        hour, minute = (int(part) for part in event.start_time.split(":"))
        parts.append(clock(config.now_bogota().replace(hour=hour, minute=minute)))
    if event.venue:
        parts.append(event.venue)
    return f"- [{event.title}]({links.event_url(event.id)}) · {' · '.join(parts)}"


def added_story_markdown(added: AddedStory) -> str:
    """The answer to "Agregar historia": what was published and a receipt of what was read and where each part
    came from (inferred parts flagged), the flyer's crop, and how to undo it (/ocultar)."""
    lines: list[str] = []
    again = added.unchanged or added.duplicate_of
    if added.unchanged:
        lines.append("ℹ️ Ya había publicado estas mismas capturas: no las leí de nuevo (no gasté cuota de Gemini).")
    if added.duplicate_of:
        lines.append(
            f"ℹ️ Es otra captura de una historia que ya publiqué (`{added.duplicate_of}`): no la leí de nuevo. Si es "
            "una historia distinta, compártela otra vez con una nota (Notas) y la leo."
        )
    published = added.outcome in ("event", "merged") and added.events
    if published and again:
        lines.append(f"✅ **Ya está en el sitio** ({len(added.events)} evento(s)):")
        lines += [_story_event_line(event) for event in added.events]
    elif published:
        verb = "Se unió a" if added.outcome == "merged" else "Publiqué"
        light = " Flash-Lite (Flash no tenía cuota)" if added.provisional else f" {added.model}"
        lines.append(f"✅ **{verb} {len(added.events)} evento(s)** desde la historia, leída con{light}:")
        lines += [_story_event_line(event) for event in added.events]
        lines += ["", "**Lo que leí:**"]
        checked = "" if added.account_checked else " ⚠️"
        lines.append(f"- Cuenta: @{added.account} ({added.account_source}){checked}")
        for event in added.events:
            notes = added.date_notes.get(event.title)
            if notes:
                lines.append(f"- Fecha de “{event.title}”: {_day(event)} ({'; '.join(notes)})")
        if added.location:
            lines.append(f"- Lugar: {added.location} (del sticker de ubicación)")
        if added.mentions:
            mentions = ", ".join(f"@{name}" for name in added.mentions)
            lines.append(f"- Menciones: {mentions} (no son la cuenta del evento)")
        lines.append(f"- Captura: {moment_label(added.taken.isoformat(), config.now_bogota())} ({added.taken_source})")
        if not added.gemini_crop:
            lines.append("- Recorte: fijo (Gemini no marcó bien el flyer): revisa que se vea completo")
        if added.past:
            lines.append(f"- No publiqué, porque ya pasaron: {', '.join(added.past)}")
    elif added.past:
        lines.append(f"❌ Su fecha ya pasó: {', '.join(added.past)}. No publiqué nada.")
    elif added.outcome == "discarded":
        lines.append(f"❌ Gemini la leyó como evento, pero no es publicable (recurrente o sin fecha): {added.reason}")
    else:
        lines.append(f"❌ Gemini dice que no anuncia un evento: “{added.reason}”")
    if added.account_added:
        lines.append(
            f"➕ @{added.account} no estaba en los barridos: la agregué (sus publicaciones de los últimos "
            f"{config.BACKFILL_DAYS} días se leen en el próximo barrido)."
        )
    if published:
        flyers = [
            media.flyer
            for event in added.events
            for media in event.media
            if media.post_id == added.story_id and media.flyer
        ]
        if flyers:
            lines += ["", f"![Recorte publicado]({config.SITE_URL}/{flyers[0]})"]
        if not again:
            lines += ["", "Aparece en el sitio cuando termina de publicarse (unos minutos)."]
        lines.append(
            f"¿Algo está mal? Ocultar: `/ocultar {added.story_id}` (o el botón en la página). Después puedes "
            "compartirla otra vez con la @cuenta o una nota."
        )
    else:
        lines.append(
            "Para intentarlo de nuevo, comparte las capturas otra vez (con la @cuenta o una nota si ayuda): las que "
            "subiste siguen guardadas hasta 7 días."
        )
    return "\n".join(lines) + "\n"


def hidden_story_markdown(hidden: HiddenStory) -> str:
    if hidden.already:
        return f"ℹ️ La historia `{hidden.story_id}` ya estaba oculta.\n"
    lines = [f"🙈 Oculté la historia `{hidden.story_id}` (@{hidden.account})."]
    lines += [f"- Quité del sitio: {event.title} · {_day(event)}" for event in hidden.removed]
    lines += [
        f"- Sigue en el sitio, porque otras publicaciones lo anuncian: [{event.title}]({links.event_url(event.id)})"
        for event in hidden.kept
    ]
    if not hidden.removed and not hidden.kept:
        lines.append("No tenía eventos en el sitio.")
    else:
        lines.append("")
        lines.append("Sale del sitio cuando termina de publicarse (unos minutos).")
    lines.append("Para publicarla de nuevo, comparte las capturas otra vez.")
    return "\n".join(lines) + "\n"


def _write_report(report: str) -> None:
    logging.info("\n%s", report)
    if report_file := os.environ.get("ADMIN_REPORT_FILE"):
        Path(report_file).write_text(report, encoding="utf-8")


def load_screenshots(ids: list[str], folder: Path) -> list[stories.Screenshot]:
    """The screenshots the workflow downloaded: <id>.jpg, and <id>.json with the file's name and dates."""
    shots = []
    for upload in ids:
        meta_file = folder / f"{upload}.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        name, modified, uploaded = meta.get("name"), meta.get("modified"), meta.get("uploaded")
        shots.append(
            stories.Screenshot(
                (folder / f"{upload}.jpg").read_bytes(),
                name if isinstance(name, str) else "",
                modified if isinstance(modified, int) else None,
                uploaded if isinstance(uploaded, int) else None,
            )
        )
    return shots


def add_story(ids: list[str], folder: Path, account: str | None, notes: str | None) -> None:
    """`sweep --story`: publish a story's events from its screenshots. The answer goes to ADMIN_REPORT_FILE, and
    `story_done=true` to the workflow when the screenshots aren't needed any more (it then deletes them)."""
    done = False
    try:
        sweep = Sweep(lookback_days=config.DEFAULT_LOOKBACK_DAYS)
        added = sweep.add_story(load_screenshots(ids, folder), account, notes)
        report, done = added_story_markdown(added), added.done
    except AddPostError as error:
        report = f"❌ {error}\n"
    _write_report(report)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as file:
            file.write(f"story_done={str(done).lower()}\n")


def hide_story(story_id: str) -> None:
    """`sweep --hide-story`: take a story added by hand off the site."""
    try:
        report = hidden_story_markdown(Sweep(lookback_days=config.DEFAULT_LOOKBACK_DAYS).hide_story(story_id))
    except AddPostError as error:
        report = f"❌ {error}\n"
    _write_report(report)


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
    parser.add_argument("--post", help="add one post by hand instead (its Instagram link): the admin tools' Agregar")
    parser.add_argument("--account", help="with --post: the @account, if the link doesn't say it")
    parser.add_argument(
        "--again",
        action="store_true",
        help="with --post: read it again even if it was read before and hasn't changed (one Gemini request)",
    )
    parser.add_argument(
        "--story",
        nargs="+",
        metavar="ID",
        help="add a story by hand instead, from its screenshots (the admin page's upload ids, at most 4)",
    )
    parser.add_argument(
        "--story-dir", type=Path, default=Path("stories"), help="with --story: where <id>.jpg and <id>.json are"
    )
    parser.add_argument("--notes", help="with --story: the admin's notes (hints for Gemini, never published)")
    parser.add_argument("--hide-story", metavar="STORY", help="take a story added by hand off the site (story-…)")
    args = parser.parse_args(argv)
    setup_logging()

    if args.story:
        account = links.account_name(args.account) if args.account else None
        add_story(args.story[: stories.MAX_SCREENSHOTS], args.story_dir, account, args.notes)
        return
    if args.hide_story:
        hide_story(args.hide_story)
        return
    if args.post:
        add_post(args.post, links.account_name(args.account) if args.account else None, again=args.again)
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
