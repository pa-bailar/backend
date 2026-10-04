"""`admin why <post link>`: why a post's event is, or isn't, on the site. No AI, no Gemini requests.

Fixed checks over what the sweeps record (sweep_state.py), in the order a post goes through them:
  1. Was it analyzed? (processed_posts.json, matched by the link's post code)
     - yes: what became of it (its `outcome`): published as events (are they still on the site?), merged
       into another post's event, discarded (recurring, no date), not an event (Gemini's reason), rejected.
  2. If not: is the account swept? (accounts.txt) If it is, one Instagram call finds the post among the
     account's latest, and its date says why: posted after the last sweep, before the account was added,
     outside the sweep's window, or the last sweeps couldn't read the account.
The verdict ends with what to do: usually Agregar (`sweep --post`), which extracts the post by hand.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from . import config, links, storage, sweep_state
from .instagram import InstagramError, Post, is_not_visible, published_at
from .text import dates_label

Mark = Literal["ok", "no", "info"]
Suggestion = Literal["add-post", "none"]

REMOVED_BY_HAND = "Quitado a mano"  # the reason recorded on a post whose event was removed from the site by hand
DISCARD_DETAIL = {
    "recurrente": "es una clase o noche que se repite, y el sitio solo publica eventos únicos",
    "sin fecha": "no tiene una fecha clara",
}


@dataclass
class Diagnosis:
    link: str
    account: str | None = None
    checks: list[tuple[Mark, str]] = field(default_factory=list)
    verdict: str = ""
    suggestion: Suggestion = "none"
    # {title, date, url} of the events on the site; date: '2026-11-13', or '13–15 nov 2026' over several days
    events: list[dict[str, str]] = field(default_factory=list)

    def check(self, mark: Mark, text: str) -> None:
        self.checks.append((mark, text))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _date(iso: str) -> str:
    moment = datetime.fromisoformat(iso).astimezone(config.BOGOTA_TZ)
    hour = moment.strftime("%I:%M").lstrip("0") + (" a. m." if moment.hour < 12 else " p. m.")
    return f"{moment.day}/{moment.month} {hour}"


def diagnose(
    url: str,
    account: str | None = None,
    *,
    read: Callable[[str, Any], Any] = sweep_state.read,
    fetch_posts: Callable[[str], list[Post]] | None = None,
    author_of: Callable[[str], str | None] | None = None,
    now: datetime | None = None,
) -> Diagnosis:
    """`fetch_posts(account)` lists the account's latest posts (one Instagram call); `author_of(code)` reads who
    published a post from its public page (public_post.py). None skips either step."""
    now = now or config.now_bogota()
    result = Diagnosis(link=url.strip())
    code = links.post_code(url)
    if not code:
        result.verdict = "Ese enlace no es de una publicación de Instagram (instagram.com/p/…)."
        return result

    processed: dict[str, dict[str, Any]] = read(config.PROCESSED_POSTS_FILE.name, {})
    record = next((r for r in processed.values() if links.same_post(r.get("permalink", ""), code)), None)
    followed = storage.read_accounts()
    events = storage.read_json(config.EVENTS_FILE, [])
    today = now.date().isoformat()

    if record:
        result.account = record["account"]
        _explain_record(result, record, events, today, swept=record["account"] in followed)
        return result

    author = author_of(code) if author_of else None
    result.account = account or links.account_in_link(url) or author
    if not result.account:
        result.check("info", "No tengo registrada esta publicación.")
        result.verdict = "El enlace no dice de qué cuenta es y su página pública no se pudo leer: indica la @cuenta."
        return result
    if author and author != result.account:  # a collaboration: the post is its author's, shown on both profiles
        result.check("info", f"La publicó @{author}, en colaboración con @{result.account}.")
        result.account = author
    if result.account not in followed:
        result.check("no", f"@{result.account} no está en los barridos.")
        result.verdict = (
            "Esa cuenta no se revisa. Agregar publica esta publicación, y suma la cuenta si Instagram deja leerla."
        )
        result.suggestion = "add-post"
        return result
    result.check("ok", f"@{result.account} está en los barridos.")
    result.check("info", "Esta publicación todavía no se ha analizado.")
    if fetch_posts is None:
        result.verdict = "No revisé Instagram para saber por qué."
        result.suggestion = "add-post"
        return result
    _explain_unseen(result, code, fetch_posts, read, now)
    return result


def _explain_record(
    result: Diagnosis, record: dict[str, Any], events: list[dict[str, Any]], today: str, swept: bool
) -> None:
    account = record["account"]
    result.check("ok" if swept else "no", f"@{account} {'está' if swept else 'ya no está'} en los barridos.")
    model = record.get("model") or "?"
    light = " (Flash-Lite, provisional: se relee con Flash)" if record.get("provisional") else ""
    result.check("ok", f"Analizada el {_date(record['processed_at'])} con {model}{light}.")

    outcome = record.get("outcome")
    if outcome is None:  # analyzed before outcomes were recorded
        outcome = "event" if record.get("is_event_post") else "not_event"
    ids = record.get("event_ids") or []
    if not ids and outcome == "event":  # old record: find its events by the post's link
        ids = [e["id"] for e in events if any(m.get("permalink") == record["permalink"] for m in e.get("media", []))]

    if outcome in ("event", "merged"):
        on_site = [e for e in events if e["id"] in ids]
        upcoming = [e for e in on_site if (e.get("end_date") or e.get("date") or "") >= today]  # until its last day
        if upcoming:
            joined = " (unida a un evento que otra publicación ya había anunciado)" if outcome == "merged" else ""
            result.check("ok", f"Se convirtió en {len(upcoming)} evento(s){joined}.")
            result.events = [
                {
                    "title": e["title"],
                    "date": dates_label(e["date"], e.get("end_date")),
                    "url": links.event_url(e["id"]),
                }
                for e in upcoming
            ]
            result.verdict = "Está en el sitio."
        elif on_site:
            result.check("info", "Su evento ya pasó: sale del sitio después de su fecha.")
            result.verdict = "Ya pasó su fecha."
        else:
            result.check("no", "Su evento ya no está en el sitio (puede que una lectura posterior lo cambiara).")
            result.verdict = "No está en el sitio. Agregarla la vuelve a leer."
            result.suggestion = "add-post"
    elif outcome == "discarded":
        detail = record.get("detail") or ""
        why = "; ".join(DISCARD_DETAIL.get(part, part) for part in detail.split(", ") if part) or "no era publicable"
        result.check("no", f"Era un evento, pero no se publicó: {why}.")
        result.verdict = "Se descartó a propósito. Si es un evento único con fecha, agregarla la vuelve a leer."
        result.suggestion = "add-post"
    elif outcome == "rejected":
        result.check("no", f"Gemini no pudo leerla: {record.get('reason', '')}")
        result.verdict = "Agregarla lo intenta de nuevo."
        result.suggestion = "add-post"
    elif str(record.get("reason", "")).startswith(REMOVED_BY_HAND):
        result.check("no", f"Se quitó a mano: {record['reason'].removeprefix(REMOVED_BY_HAND).strip(' :')}")
        result.verdict = "No está en el sitio a propósito."
    else:
        result.check("no", f"Gemini dijo que no es un evento: “{record.get('reason', '')}”")
        result.verdict = "Si sí es un evento, agregarla la lee de nuevo sin ese filtro."
        result.suggestion = "add-post"


def _explain_unseen(
    result: Diagnosis,
    code: str,
    fetch_posts: Callable[[str], list[Post]],
    read: Callable[[str, Any], Any],
    now: datetime,
) -> None:
    account = result.account
    assert account
    try:
        posts = fetch_posts(account)
    except InstagramError as error:
        if is_not_visible(error):
            result.check("no", f"La API de Instagram no puede leer @{account}: es una cuenta personal o privada.")
            result.verdict = "Los barridos no pueden seguirla. Agregar la lee desde su página pública."
        else:
            result.check("no", f"No pude leer @{account} en Instagram ({error}).")
            result.verdict = "Inténtalo de nuevo en un rato, o agrégala: Agregar la lee desde su página pública."
        return
    post = next((p for p in posts if links.same_post(p["permalink"], code)), None)
    if post is None:
        result.check("no", f"No está entre las últimas {config.ADMIN_POST_SEARCH} publicaciones de @{account}.")
        result.verdict = "Es antigua, o es una colaboración de otra cuenta. Agregar la lee desde su página pública."
        return

    published = published_at(post).astimezone(config.BOGOTA_TZ)
    result.check("ok", f"Publicada el {_date(published.isoformat())}")
    history: list[dict[str, Any]] = read(config.RUN_HISTORY_FILE.name, [])
    last = history[-1] if history else None
    account_state = read(config.ACCOUNT_STATE_FILE.name, {}).get(account, {})
    first_seen = account_state.get("first_seen")
    # Each account is read about once a day, not every run: compare with this account's last reading.
    read_at = account_state.get("last_swept_at") or (last["finished_at"] if last else None)
    tried = next(
        (r for r in reversed(history) if account in r.get("read_accounts", []) + r.get("failed_accounts", [])),
        last,
    )
    result.suggestion = "add-post"
    if first_seen is None:
        result.verdict = "La cuenta se agregó hace poco y todavía no se ha barrido: entra en el próximo barrido."
    elif read_at and published > datetime.fromisoformat(read_at):
        result.verdict = (
            "Se publicó después de la última lectura de la cuenta: entra en su próximo turno (cada cuenta se lee "
            "una vez al día). Agregarla la publica ya."
        )
    elif (
        first_seen
        and published.date().isoformat() < first_seen
        and now - published > timedelta(days=config.BACKFILL_DAYS)
    ):
        result.verdict = (
            "Se publicó antes de que empezáramos a revisar la cuenta, fuera de lo que se carga al agregarla."
        )
    elif now - published > timedelta(days=config.DEFAULT_LOOKBACK_DAYS):
        result.verdict = (
            f"Es de hace más de {config.DEFAULT_LOOKBACK_DAYS} días: los barridos solo revisan lo más reciente."
        )
    elif tried and account in tried.get("failed_accounts", []):
        result.verdict = "La última vez que le tocó, el barrido no pudo leer esta cuenta."
    elif last and last.get("pending"):
        result.verdict = "Está en espera: el último barrido se quedó sin cuota de Gemini o sin tiempo."
    else:
        result.verdict = "No encuentro por qué no se analizó."


# ---------- for people ----------

MARKS = {"ok": "✅", "no": "❌", "info": "ℹ️"}


def markdown(result: Diagnosis) -> str:
    lines = [f"**{result.verdict}**", ""]
    lines += [f"- {MARKS[mark]} {text}" for mark, text in result.checks]
    lines += [f"- 🔗 [{e['title']}]({e['url']}) · {e['date']}" for e in result.events]
    if result.suggestion == "add-post":
        lines += ["", "Para publicarla: **Agregar** con este mismo enlace."]
    return "\n".join(lines) + "\n"
