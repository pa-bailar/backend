"""How Pa' Bailar is doing, in one place: the data behind `admin status` and the admin page (docs/ADMIN.md).

Plain reading of what the sweeps record (no AI, no Gemini requests):
  - the latest sweeps and the next ones (run_history.json, config.SWEEP_TIMES);
  - today's Gemini usage per model against its daily budget, and when the quota resets (gemini_usage.json);
  - Instagram: whether the token works and how much of Instagram's quota is used (one call, optional);
  - accounts followed, those still in their first, deeper sweep (accounts.txt, accounts.json);
  - analyzed posts, provisional ones waiting for Flash, upcoming events (processed_posts.json, events.json);
  - discovery progress, on your computer (private/discovery.json).
`collect` gathers it as plain data (JSON for the admin page); `markdown` writes it for people, in Spanish.
"""

from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import config, discovery, storage, sweep_state
from .gemini import daily_budget, quota_day

RECENT_RUNS = 5
WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def next_sweeps(now: datetime, count: int = 2) -> list[datetime]:
    """The next scheduled sweeps (config.SWEEP_TIMES, Bogotá time) after `now`."""
    upcoming: list[datetime] = []
    day = now.date()
    while len(upcoming) < count:
        for hhmm in sorted(config.SWEEP_TIMES):
            hour, minute = map(int, hhmm.split(":"))
            moment = datetime.combine(day, time(hour, minute), config.BOGOTA_TZ)
            if moment > now and len(upcoming) < count:
                upcoming.append(moment)
        day += timedelta(days=1)
    return upcoming


def quota_reset(now: datetime) -> datetime:
    """When Gemini's daily quotas reset next (midnight Pacific), in Bogotá time."""
    pacific = now.astimezone(ZoneInfo(config.QUOTA_TIMEZONE))
    midnight = datetime.combine(pacific.date() + timedelta(days=1), time(0), pacific.tzinfo)
    return midnight.astimezone(config.BOGOTA_TZ)


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
    return ", ".join(roles) or "discovery"


def check_instagram() -> dict[str, Any]:
    """One Graph API call: does the token work, and how much of Instagram's quota is used."""
    from .instagram import InstagramClient, InstagramError  # only when asked: needs the Meta secrets

    try:
        client = InstagramClient.from_env()
        client.check_token()
    except (InstagramError, OSError, SystemExit) as error:
        return {"ok": False, "app_usage_percent": None, "error": str(error)}
    return {"ok": True, "app_usage_percent": client.app_usage_percent, "error": None}


def collect(
    now: datetime | None = None,
    instagram: Callable[[], dict[str, Any]] | None = check_instagram,
    read: Callable[[str, Any], Any] = sweep_state.read,
) -> dict[str, Any]:
    """Everything `admin status` shows, as plain data. `instagram=None` skips the Instagram call."""
    now = now or config.now_bogota()
    today = now.date().isoformat()

    history = read(config.RUN_HISTORY_FILE.name, [])
    usage = read(config.GEMINI_USAGE_FILE.name, {})
    used = usage.get("requests", {}) if usage.get("day") == quota_day() else {}
    account_state = read(config.ACCOUNT_STATE_FILE.name, {})
    processed = read(config.PROCESSED_POSTS_FILE.name, {})
    followed = storage.read_accounts()

    events = storage.read_json(config.EVENTS_FILE, None)
    upcoming = [event for event in events or [] if (event.get("date") or "") >= today]
    discovered = discovery.load_cache(config.PRIVATE_DIR / "discovery.json")

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "sweeps": {
            "recent": history[-RECENT_RUNS:][::-1],  # newest first
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
        "instagram": instagram() if instagram else None,
        "accounts": {
            "followed": len(followed),
            "first_sweep_pending": [
                account for account in followed if not account_state.get(account, {}).get("backfill_done")
            ],
        },
        "posts": {
            "recorded": len(processed),
            "provisional": sum(1 for record in processed.values() if record.get("provisional")),
        },
        "events": None
        if events is None
        else {
            "upcoming": len(upcoming),
            "low_confidence": sum(1 for event in upcoming if event.get("confidence") == "low"),
        },
        "discovery": None
        if not discovered
        else {
            "checked": len(discovered),
            "classified": sum(1 for account in discovered.values() if account.classification),
        },
    }


# ---------- for people ----------


def _when(iso: str, now: datetime) -> str:
    """'hoy 9:00 p. m.', 'mañana 9:00 a. m.', 'sábado 3 de oct., 9:00 a. m.'."""
    moment = datetime.fromisoformat(iso).astimezone(config.BOGOTA_TZ)
    hour = moment.strftime("%I:%M").lstrip("0") + (" a. m." if moment.hour < 12 else " p. m.")
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
        f"{run.get('provisional', 0)} provisionales" if run.get("provisional") else "",
        *problems,
    ]
    when = _when(run["finished_at"], now)
    link = f" · [ver]({run['run_url']})" if run.get("run_url") else ""
    return f"- {mark} {when}: " + ", ".join(part for part in parts if part) + link


def markdown(status: dict[str, Any]) -> str:
    """The status for people (GitHub summaries, issue replies, the terminal), in Spanish."""
    now = datetime.fromisoformat(status["generated_at"])
    lines = ["## Estado de Pa' Bailar", ""]

    sweeps = status["sweeps"]
    lines += ["### Barridos", ""]
    lines += [_run_line(run, now) for run in sweeps["recent"]] or ["- Todavía no hay barridos registrados."]
    lines += ["", "Próximos: " + " y ".join(_when(iso, now) for iso in sweeps["next"]), ""]

    gemini = status["gemini"]
    lines += ["### Gemini hoy", "", "| Modelo | Para | Usado | Presupuesto |", "|---|---|---|---|"]
    for model in gemini["models"]:
        full = " (agotado)" if model["used"] >= model["budget"] else ""
        lines.append(f"| `{model['model']}` | {model['role']} | {model['used']}{full} | {model['budget']} |")
    lines += ["", f"La cuota se reinicia {_when(gemini['resets_at'], now)}"]
    if gemini["lite_only"]:
        lines.append("Modo solo Flash-Lite activo (GEMINI_LITE_ONLY).")
    lines.append("")

    instagram = status["instagram"]
    if instagram is not None:
        lines += ["### Instagram", ""]
        if instagram["ok"]:
            lines.append(f"- Token: funciona. Cuota de Instagram usada: {instagram['app_usage_percent']}%.")
        else:
            lines.append(f"- ⚠️ Token: no funciona ({instagram['error']}).")
        lines.append("")

    accounts = status["accounts"]
    pending = accounts["first_sweep_pending"]
    lines += ["### Cuentas y eventos", "", f"- {accounts['followed']} cuentas en los barridos."]
    if pending:
        lines.append(f"- {len(pending)} en su primer barrido (más profundo): " + ", ".join(f"@{a}" for a in pending))
    posts = status["posts"]
    lines.append(f"- {posts['recorded']} publicaciones analizadas en los últimos días.")
    if posts["provisional"]:
        lines.append(f"- {posts['provisional']} eventos provisionales (leídos con Flash-Lite), a releer con Flash.")
    if status["events"] is not None:
        events = status["events"]
        low = f", {events['low_confidence']} con datos dudosos" if events["low_confidence"] else ""
        lines.append(f"- {events['upcoming']} eventos próximos en el sitio{low}.")
    if status["discovery"] is not None:
        found = status["discovery"]
        lines.append(f"- Descubrimiento: {found['checked']} cuentas revisadas, {found['classified']} clasificadas.")
    return "\n".join(lines) + "\n"
