"""How Pa' Bailar is doing, in one place: the data behind `admin status` and the admin page (docs/ADMIN.md).

Plain reading of what the sweeps record (no AI, no Gemini requests):
  - the latest sweeps and the next ones (run_history.json, config.SWEEP_TIMES);
  - today's Gemini usage per model against its daily budget, and when the quota resets (gemini_usage.json);
  - today's use of the last resort, the providers outside Gemini (Groq, OpenRouter: external_usage.json);
  - Instagram: whether the token works (one call, optional), and the last sweep's highest reading of its quota
    (run_history.json: the token check's own reading is another counter);
  - what Flash changed when it re-read events only lighter models had read, over the recorded runs (run_history.json);
  - the history: what the latest sweeps and admin requests did to which event (run_history.json, admin_runs.json:
    changes.py);
  - accounts followed, those still in their first, deeper sweep (accounts.txt, accounts.json);
  - analyzed posts, provisional ones waiting for Flash, upcoming events (processed_posts.json, events.json);
  - new workshop series to look at, each with a one-tap "Ocultar" (new_series);
  - discovery progress, on your computer (private/discovery.json).
`collect` gathers it as plain data (JSON for the admin page); `markdown` writes it for people, in Spanish.
"""

from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from . import config, discovery, links, storage, sweep_state
from .changes import FIELD_NAMES
from .external import usage_day, usage_reset
from .gemini import daily_budget, quota_day, quota_reset
from .models import AccountState, GeminiUsage, StoredEvent, had_events
from .pipeline import overdue_by_account
from .text import WEEKDAYS, clock, parse_hhmm, sessions_label

RECENT_RUNS = 5
HISTORY_ITEMS = 10  # runs in the history (status["history"]): sweeps and admin requests, newest first
# A sweep that ends within this long after one of config.SWEEP_TIMES is that scheduled one (it can wait for a data PR
# or a request before it, then runs up to config.MAX_RUN_MINUTES); else it's an extra one, started by hand.
SCHEDULED_SWEEP_MINUTES = 90


def next_sweeps(now: datetime, count: int = 2) -> list[datetime]:
    """The next scheduled sweeps (config.SWEEP_TIMES, Bogotá time) after `now`."""
    upcoming: list[datetime] = []
    day = now.date()
    while len(upcoming) < count:
        for hhmm in sorted(config.SWEEP_TIMES):
            moment = datetime.combine(day, parse_hhmm(hhmm), config.BOGOTA_TZ)
            if moment > now and len(upcoming) < count:
                upcoming.append(moment)
        day += timedelta(days=1)
    return upcoming


def sweep_slot(finished_at: str) -> str | None:
    """The scheduled sweep (config.SWEEP_TIMES: "06:30", "21:00") a run that ended then was, or None (an extra one)."""
    moment = datetime.fromisoformat(finished_at).astimezone(config.BOGOTA_TZ)
    for hhmm in config.SWEEP_TIMES:
        start = datetime.combine(moment.date(), parse_hhmm(hhmm), config.BOGOTA_TZ)
        if timedelta(0) <= moment - start <= timedelta(minutes=SCHEDULED_SWEEP_MINUTES):
            return hhmm
    return None


def _history_item(run: dict[str, Any], kind: str) -> dict[str, Any]:
    """One run in the history: what kind (a sweep, which one, or an admin request), when, and what it did to which
    event. `changes` is None for a run recorded before they were kept: its counts only ("sin detalle")."""
    changes = run.get("changes")
    counted = run.get("change_counts") or {}
    if changes is None and not counted:  # a sweep recorded before the changes were: its own counts
        counted = {name: run[key] for name, key in (("new", "events_new"), ("merged", "events_merged")) if run.get(key)}
    return {
        "kind": kind,
        "slot": sweep_slot(run["finished_at"]) if kind == "sweep" else None,
        "finished_at": run["finished_at"],
        "run_url": run.get("run_url"),
        "target": run.get("target"),
        "error": run.get("error"),
        "changes": None if changes is None else [{**item, "url": links.event_url(item["id"])} for item in changes],
        "left_out": run.get("changes_left_out", 0),
        "counts": counted,
    }


def history_of(runs: list[dict[str, Any]], admin_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The admin page's "Historial": the latest sweeps (run_history.json) and admin requests (admin_runs.json),
    newest first, each with what it did to which event (changes.py)."""
    items = [_history_item(run, "sweep") for run in runs[-HISTORY_ITEMS:]]
    items += [_history_item(run, run["action"]) for run in admin_runs[-HISTORY_ITEMS:]]
    items.sort(key=lambda item: datetime.fromisoformat(item["finished_at"]), reverse=True)
    return items[:HISTORY_ITEMS]


def _role(model: str) -> str:
    roles = [
        name
        for name, models in (
            ("triage", config.TRIAGE_MODELS),
            ("extraction", config.EXTRACTION_MODELS),
            ("provisional", config.PROVISIONAL_MODELS),
        )
        if model in models
    ]
    return ", ".join(roles) or "none"


def _external_usage(provider: config.ExternalProvider, used: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": provider.name,
        "models": [model.name for model in provider.models],
        "used": used.get("requests", 0),
        "budget": provider.daily_requests,
        "tokens": used.get("tokens", 0) if provider.daily_tokens else None,
        "token_budget": provider.daily_tokens,
        "answered": used.get("answered", {}),
    }


def check_instagram() -> dict[str, Any]:
    """One Graph API call: does the token work. Not the quota: this call's reading is another counter than the
    accounts' (1% at the end of a sweep stopped at 90%, 7 Oct 2026); the sweeps record theirs (instagram_quota)."""
    from .instagram import InstagramClient, InstagramError  # only when asked: needs the Meta secrets

    try:
        InstagramClient.from_env().check_token()
    except (InstagramError, OSError, SystemExit) as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "error": None}


def _instagram_quota(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The last sweep's highest reading of Instagram's quota, its measures, and where the sweep stops."""
    last = next((run for run in reversed(history) if run.get("instagram_usage") is not None), None)
    if last is None:
        return None
    return {
        "usage": last["instagram_usage"],
        "detail": last.get("instagram_usage_detail") or {},
        "stopped": bool(last.get("rate_limited")),
        "finished_at": last["finished_at"],
        "stop_at": config.INSTAGRAM_USAGE_STOP,
    }


def _lighter_reads(history: list[dict[str, Any]]) -> dict[str, int] | None:
    """What Flash changed in lighter models' readings over the recorded runs (upgrade_changes, summed); None until
    one was compared."""
    total: Counter[str] = Counter()
    for run in history:
        total.update(run.get("upgrade_changes") or {})
    return dict(total) if total.get("compared") else None


def lighter_reads_line(changes: dict[str, int]) -> str:
    """ "Flash releyó 12 eventos que solo había leído un modelo más liviano: cambió la hora en 2, los ritmos en 3." """
    compared = changes["compared"]
    parts = [f"{name} en {changes[key]}" for key, name in FIELD_NAMES.items() if changes.get(key)]
    if changes.get("dropped"):
        parts.append(f"no mantuvo {changes['dropped']}")
    found = ": " + ", ".join(parts) if parts else ": no cambió nada"
    plural = "evento" if compared == 1 else "eventos"
    return f"Flash releyó {compared} {plural} que solo había leído un modelo más liviano{found}."


# Meta's measures, as the owner reads them.
_MEASURE_NAMES = {"call_count": "llamadas", "total_cputime": "CPU", "total_time": "tiempo"}


def quota_line(quota: dict[str, Any], now: datetime) -> str:
    """ "Cuota de Instagram en el último barrido (hoy 9:09 p. m.): 90% (CPU 90%, llamadas 31%, tiempo 77%). Se
    detuvo ahí: las cuentas que faltaron van primero en el siguiente." """
    measures = ", ".join(
        f"{_MEASURE_NAMES.get(key, key)} {value}%"
        for key, value in sorted(quota["detail"].items(), key=lambda item: -item[1])
    )
    text = f"Cuota de Instagram en el último barrido ({moment_label(quota['finished_at'], now)}): {quota['usage']}%"
    text += f" ({measures})." if measures else "."
    if quota["stopped"] and quota["usage"] >= quota["stop_at"]:
        text += " Se detuvo ahí: las cuentas que faltaron van primero en el siguiente."
    elif quota["stopped"]:  # Meta's own rate-limit error, below our limit
        text += " Meta lo frenó antes, con su propio límite: las cuentas que faltaron van primero en el siguiente."
    else:
        text += f" El barrido se detiene en {quota['stop_at']}%."
    return text


def _first_published(event: StoredEvent, processed: dict[str, dict[str, Any]]) -> datetime | None:
    """When the event was first published: the earliest analysis of a post that became or joined it, else (records
    forgotten) its earliest post's date. The records stay plain data: the counts read only part of them."""
    times = [
        datetime.fromisoformat(record["processed_at"])
        for record in processed.values()
        if event.id in (record.get("event_ids") or []) and record.get("processed_at")
    ]
    if not times:
        times = [datetime.fromisoformat(media.published) for media in event.media if media.published]
    return min(times) if times else None


def new_series(events: list[StoredEvent], processed: dict[str, dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Workshop series (events with `sessions`) first published in the last NEW_SERIES_DAYS and not over yet,
    newest first: a new kind of event, worth a look. Each with its sessions ("4 sesiones: 8, 22, 29 nov y 6 dic"),
    where it came from (its posts' links, or a story's profile) and its link on the site, for "Ocultar"."""
    since = now - timedelta(days=config.NEW_SERIES_DAYS)
    today = now.date().isoformat()
    found = []
    for event in events:
        dates = event.session_dates
        first = _first_published(event, processed)
        if not dates or dates[-1] < today or first is None or first < since:
            continue
        found.append(
            {
                "id": event.id,
                "title": event.title,
                "account": event.account,
                "sessions": sessions_label(dates),
                "dates": dates,
                "url": links.event_url(event.id),
                "first_published": first.isoformat(timespec="minutes"),
                "sources": [
                    {"kind": "story" if media.media_type == "STORY" else "post", "link": media.permalink}
                    for media in event.media
                ],
            }
        )
    return sorted(found, key=lambda item: item["first_published"], reverse=True)


def collect(
    now: datetime | None = None,
    instagram: Callable[[], dict[str, Any]] | None = check_instagram,
    read: Callable[[str, Any], Any] = sweep_state.read,
) -> dict[str, Any]:
    """Everything `admin status` shows, as plain data. `instagram=None` skips the Instagram call."""
    now = now or config.now_bogota()
    today = now.date().isoformat()

    history = read(config.RUN_HISTORY_FILE.name, [])
    admin_runs = read(config.ADMIN_RUNS_FILE.name, [])
    used = GeminiUsage.model_validate(read(config.GEMINI_USAGE_FILE.name, {})).on(quota_day()).requests
    external = read(config.EXTERNAL_USAGE_FILE.name, {})
    external_used = external.get("providers", {}) if external.get("day") == usage_day(now) else {}
    states = {
        name: AccountState.model_validate(value) for name, value in read(config.ACCOUNT_STATE_FILE.name, {}).items()
    }
    processed = read(config.PROCESSED_POSTS_FILE.name, {})
    followed = storage.read_accounts()
    posts = (
        (record.get("account", ""), had_events(record.get("outcome"), bool(record.get("is_event_post"))))
        for record in processed.values()
    )
    overdue = overdue_by_account(followed, states, posts, now)
    sweep_gap = 24 / max(1, len(config.SWEEP_TIMES))  # hours between sweeps, on average

    events = storage.load_events() if config.EVENTS_FILE.exists() else None
    # Upcoming until its last day: an event over several days is on the site while it goes on.
    upcoming = [event for event in events or [] if (event.last_day or "") >= today]
    discovered = discovery.load_cache(config.PRIVATE_DIR / "discovery.json")

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "sweeps": {
            # Newest first, without their changes: the history has them.
            "recent": [{k: v for k, v in run.items() if k != "changes"} for run in history[-RECENT_RUNS:][::-1]],
            "next": [moment.isoformat(timespec="minutes") for moment in next_sweeps(now)],
        },
        "gemini": {
            "lite_only": config.LITE_ONLY,
            "resets_at": quota_reset(now).isoformat(timespec="minutes"),
            "models": [
                {"model": model, "role": _role(model), "used": used.get(model, 0), "budget": daily_budget(model)}
                for model in config.MODEL_LIMITS
            ],
        },
        # The last resort, used only when Gemini runs out (the keys are the sweep's alone: whether they're set isn't
        # known here). `answered`: how many answers each model gave today.
        "external": {
            "resets_at": usage_reset(now).isoformat(timespec="minutes"),
            "providers": [
                _external_usage(provider, external_used.get(provider.name, {}))
                for provider in config.EXTERNAL_PROVIDERS
            ],
        },
        "instagram": instagram() if instagram else None,
        "instagram_quota": _instagram_quota(history),
        "lighter_reads": _lighter_reads(history),
        "accounts": {
            "followed": len(followed),
            "first_sweep_pending": [
                account for account in followed if account not in states or not states[account].backfill_done
            ],
            # Past their turn (as the sweep counts turns) by more than a sweep's gap: a sweep didn't reach them (its
            # share, Instagram's limit). One never read isn't late but new (infinitely overdue).
            "waiting": [account for account in followed if sweep_gap < overdue[account] < float("inf")],
        },
        "posts": {
            "recorded": len(processed),
            "provisional": sum(1 for record in processed.values() if record.get("provisional")),
        },
        "events": None
        if events is None
        else {
            "upcoming": len(upcoming),
            "low_confidence": sum(1 for event in upcoming if event.confidence == "low"),
        },
        "new_series": new_series(events or [], processed, now),
        "history": history_of(history, admin_runs),
        "discovery": None
        if not discovered
        else {
            "checked": len(discovered),
            "classified": sum(1 for account in discovered.values() if account.classification),
        },
    }


# ---------- for people ----------


def moment_label(iso: str, now: datetime) -> str:
    """'hoy 9:00 p. m.', 'ayer 9:00 a. m.', 'mañana 9:00 a. m.', 'sábado 3/10, 9:00 a. m.'."""
    moment = datetime.fromisoformat(iso).astimezone(config.BOGOTA_TZ)
    hour = clock(moment)
    days = (moment.date() - now.date()).days
    if days == 0:
        return f"hoy {hour}"
    if days == -1:
        return f"ayer {hour}"
    if days == 1:
        return f"mañana {hour}"
    return f"{WEEKDAYS[moment.weekday()]} {moment.day}/{moment.month}, {hour}"


def _count(number: int, one: str, many: str) -> str:
    """ "1 error", "3 errores"; empty for 0."""
    return f"{number} {one if number == 1 else many}" if number else ""


def _run_line(run: dict[str, Any], now: datetime) -> str:
    problems = [
        "límite de Instagram" if run.get("rate_limited") else "",
        "sin tiempo" if run.get("out_of_time") else "",
        _count(len(run.get("failed_accounts", [])), "cuenta sin leer", "cuentas sin leer"),
        _count(run.get("post_errors", 0), "error", "errores"),
    ]
    problems = [problem for problem in problems if problem]
    mark = "⚠️" if problems else "✅"
    parts = [
        f"{run.get('events_new', 0)} nuevos",
        f"{run.get('events_merged', 0)} unidos",
        f"{run.get('pending', 0)} en espera" if run.get("pending") else "",
        f"Instagram {run['instagram_usage']}%" if run.get("instagram_usage") else "",
        f"{run.get('provisional', 0)} provisionales" if run.get("provisional") else "",
        *problems,
    ]
    when = moment_label(run["finished_at"], now)
    link = f" · [ver]({run['run_url']})" if run.get("run_url") else ""
    return f"- {mark} {when}: " + ", ".join(part for part in parts if part) + link


def _series_line(item: dict[str, Any]) -> str:
    """A new series for people: its link, account (in code: no GitHub mention), sessions, posts, and how to hide it."""
    sources = [
        f"[{'historia' if source['kind'] == 'story' else 'publicación'}]({source['link']})"
        for source in item["sources"]
        if source.get("link")
    ]
    origin = f" · de {', '.join(sources)}" if sources else ""
    return (
        f"- [{item['title']}]({item['url']}) · `@{item['account']}` · {item['sessions']}{origin} · "
        f"`/ocultar {item['id']}`"
    )


def _models_lines(status: dict[str, Any], now: datetime) -> list[str]:
    """Gemini's use today per model, and the last resort's when it was used (Gemini ran out)."""
    gemini = status["gemini"]
    lines = ["### Gemini hoy", "", "| Modelo | Para | Usado | Presupuesto |", "|---|---|---|---|"]
    for model in gemini["models"]:
        full = " (agotado)" if model["used"] >= model["budget"] else ""
        lines.append(f"| `{model['model']}` | {model['role']} | {model['used']}{full} | {model['budget']} |")
    lines += ["", f"La cuota se reinicia {moment_label(gemini['resets_at'], now)}"]
    if gemini["lite_only"]:
        lines.append("Modo solo Flash-Lite activo (GEMINI_LITE_ONLY).")
    for provider in (status.get("external") or {}).get("providers", []):
        if provider["used"]:
            answered = ", ".join(f"`{model}` {count}" for model, count in provider["answered"].items())
            lines.append(
                f"⚠️ {provider['name']} (último recurso, Gemini sin cuota): {provider['used']} de {provider['budget']} "
                "solicitudes hoy" + (f" (respuestas: {answered})" if answered else "") + "."
            )
    return [*lines, ""]


def markdown(status: dict[str, Any]) -> str:
    """The status for people (GitHub summaries, issue replies, the terminal), in Spanish."""
    now = datetime.fromisoformat(status["generated_at"])
    lines = ["## Estado de Pa' Bailar", ""]

    if series := status.get("new_series"):
        lines += ["### Series nuevas (revisar)", ""]
        lines += [_series_line(item) for item in series]
        lines += ["", "Si una no está bien: `/ocultar` y su código la quita del sitio (o Ocultar, en la página).", ""]

    sweeps = status["sweeps"]
    lines += ["### Barridos", ""]
    lines += [_run_line(run, now) for run in sweeps["recent"]] or ["- Todavía no hay barridos registrados."]
    lines += ["", "Próximos: " + " y ".join(moment_label(iso, now) for iso in sweeps["next"]), ""]

    lines += _models_lines(status, now)

    instagram, quota = status["instagram"], status.get("instagram_quota")
    if instagram is not None or quota is not None:
        lines += ["### Instagram", ""]
        if instagram is not None:
            lines.append("- Token: funciona." if instagram["ok"] else f"- ⚠️ Token: no funciona ({instagram['error']}).")
        if quota is not None:
            lines.append(f"- {quota_line(quota, now)}")
        lines.append("")

    accounts = status["accounts"]
    pending = accounts["first_sweep_pending"]
    lines += ["### Cuentas y eventos", "", f"- {accounts['followed']} cuentas en los barridos."]
    if pending:
        lines.append(f"- {len(pending)} en su primer barrido (más profundo): " + ", ".join(f"@{a}" for a in pending))
    if waiting := accounts.get("waiting"):
        lines.append(
            f"- ⚠️ {len(waiting)} esperando más de un barrido después de su turno: "
            + ", ".join(f"@{a}" for a in waiting)
        )
    posts = status["posts"]
    lines.append(f"- {posts['recorded']} publicaciones analizadas en los últimos días.")
    if posts["provisional"]:
        lines.append(
            f"- {posts['provisional']} publicaciones provisionales (leídas sin Flash: un Flash anterior, Flash-Lite o "
            "el último recurso), a releer con Flash."
        )
    if lighter := status.get("lighter_reads"):
        lines.append(f"- {lighter_reads_line(lighter)}")
    if status["events"] is not None:
        events = status["events"]
        low = f", {events['low_confidence']} con datos dudosos" if events["low_confidence"] else ""
        lines.append(f"- {events['upcoming']} eventos próximos en el sitio{low}.")
    if status["discovery"] is not None:
        found = status["discovery"]
        lines.append(f"- Descubrimiento: {found['checked']} cuentas revisadas, {found['classified']} clasificadas.")
    return "\n".join(lines) + "\n"
