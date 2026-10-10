"""What happened to which event in a run: the admin page's "Historial" (docs/ADMIN.md).

Each sweep, and each admin request that changes events (Agregar, Volver a leer, a story, Ocultar), notes one change
per event it touched: added, merged with another post, corrected by Flash, cancelled, hidden, archived… (ChangeKind),
with the event's title, account, date and id (its link on the site). The sweep keeps them with its record in
run_history.json (health.RunRecord), the admin requests in admin_runs.json (AdminRun); `admin status` gathers both
(status.history). Bounded: at most config.RUN_CHANGES_KEPT per run, the most telling first, the rest only counted.
Plain data, no AI.
"""

from collections import Counter
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, TypeAdapter

from . import config, storage
from .models import EventDetails, StoredEvent
from .text import fold

ChangeKind = Literal[
    "new",  # a new event on the site
    "provisional",  # a new event read by a lighter model: Flash reads it again later
    "merged",  # another post or story of an event already on the site
    "corrected",  # Flash read again what only a lighter model had read, and changed it
    "updated",  # its post was read again (its caption edited, Volver a leer) and the event changed
    "reread",  # read again (by Flash, an edited caption, by hand): nothing changed
    "dropped",  # a new reading of its post doesn't announce it any more: off the site
    "cancelled",  # its post says it's cancelled or postponed: off the site
    "flagged",  # another account's post says it's cancelled: kept, marked for a look
    "hidden",  # taken off the site by hand (Ocultar, or the story it came from hidden)
    "kept_hidden",  # a post of an event hidden by hand: left off the site
    "restored",  # hidden by hand before, published again (added by hand)
    "duplicate",  # two stored events the rules now say are one: merged
    "archived",  # past for config.EVENT_RETENTION_DAYS: moved to the archive
]

# The most telling first: a run's list is shown, and cut, in this order.
KIND_ORDER: tuple[ChangeKind, ...] = (
    "cancelled",
    "flagged",
    "hidden",
    "restored",
    "new",
    "provisional",
    "corrected",
    "updated",
    "dropped",
    "merged",
    "duplicate",
    "kept_hidden",
    "reread",
    "archived",
)

# Changes of where an event stands (off the site, back on it): the latest of these always shows (changes.noted).
STANDING: frozenset[ChangeKind] = frozenset({"cancelled", "dropped", "hidden", "restored", "archived"})

# What a re-read compares between two readings of an event (Flash's against a lighter model's: Sweep._audit_upgrade;
# any re-read: SweepBase._note_changes), and how the owner reads each.
AUDITED_FIELDS = ("date", "end_date", "start_time", "title", "venue", "event_type", "styles")
FIELD_NAMES = {
    "date": "la fecha",
    "end_date": "el último día",
    "start_time": "la hora",
    "title": "el título",
    "venue": "el lugar",
    "event_type": "el tipo",
    "styles": "los ritmos",
}


class EventChange(BaseModel):
    """What happened to one event in a run."""

    kind: ChangeKind
    id: str  # its page on the site: links.event_url(id)
    title: str
    account: str  # the account it's stored under (its first post's)
    date: str | None = None  # its (first) day, YYYY-MM-DD
    detail: str | None = None  # a short note in Spanish: "cambió el lugar", "otra publicación de @x"


def change(kind: ChangeKind, event: StoredEvent, detail: str | None = None) -> EventChange:
    return EventChange(kind=kind, id=event.id, title=event.title, account=event.account, date=event.date, detail=detail)


def reading(event: EventDetails) -> dict[str, object]:
    """An event's audited fields, as compared: titles and venues folded (accents and case aren't a misreading)."""
    return {
        "date": event.date,
        "end_date": event.end_date,
        "start_time": event.start_time,
        "title": fold(event.title),
        "venue": fold(event.venue or ""),
        "event_type": event.event_type,
        "styles": sorted(event.styles),
    }


def changed_fields(before: EventDetails, after: EventDetails) -> list[str]:
    """The audited fields that differ between two readings of an event."""
    old, new = reading(before), reading(after)
    return [name for name in AUDITED_FIELDS if old[name] != new[name]]


def fields_label(fields: list[str]) -> str:
    """ "cambió el lugar", "cambió la hora y el lugar", "cambió la fecha, la hora y el lugar"."""
    names = [FIELD_NAMES[name] for name in fields]
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]
    return f"cambió {listed}"


def noted(changes: dict[str, EventChange], new: EventChange) -> None:
    """Note a change in a run's changes (one per event, by id: the latest wins). An event the run added stays "new"
    (or "provisional") through what happens to it later in the same run, with the latest note: Flash reading it again
    in the same sweep is part of how it came, not a second change; one it took off the site again shows that."""
    first = changes.get(new.id)
    if first is not None and first.kind in ("new", "provisional"):
        if new.kind == "merged":  # another post of it, in the same run: still a new event
            return
        if new.kind in ("corrected", "updated", "reread"):  # read again in the same run (Flash): new, as read now
            new = new.model_copy(update={"kind": "new"})
    elif (
        first is not None
        and new.kind not in STANDING
        and new.kind != first.kind
        and KIND_ORDER.index(first.kind) < KIND_ORDER.index(new.kind)
    ):
        # A less telling note doesn't hide a more telling one of the same run: a flag stays through a correction, a
        # correction through a re-read (the bug-squash pass of 9 Oct 2026: an event's second provisional post, re-read
        # after the first, turned "corrected" into "reread").
        return
    changes[new.id] = new


def ordered(changes: Iterable[EventChange]) -> list[EventChange]:
    """The most telling first (KIND_ORDER), each kind in the order it happened."""
    return sorted(changes, key=lambda item: KIND_ORDER.index(item.kind))


def bounded(changes: Iterable[EventChange], limit: int | None = None) -> tuple[list[EventChange], int]:
    """The changes to keep (ordered, at most `limit`: config.RUN_CHANGES_KEPT) and how many were left out."""
    limit = config.RUN_CHANGES_KEPT if limit is None else limit
    every = ordered(changes)
    return every[:limit], max(len(every) - limit, 0)


def counts(changes: Iterable[EventChange]) -> dict[str, int]:
    """How many of each kind, in KIND_ORDER: the run's summary ("3 nuevos · 2 unidos")."""
    found = Counter(item.kind for item in changes)
    return {kind: found[kind] for kind in KIND_ORDER if found[kind]}


# ---------- the admin requests' runs ----------

AdminAction = Literal["post", "post_again", "story", "hide_event", "hide_story"]


class AdminRun(BaseModel):
    """One admin request that ran in the sweep workflow (`sweep --post`, `--story`, `--hide-event`,
    `--hide-story`), for the history: what it changed. Not in run_history.json: those runs aren't sweeps, and the
    health rules compare sweeps."""

    finished_at: str
    run_url: str | None = None
    action: AdminAction
    target: str | None = None  # the post's link, the story's or the event's id
    error: str | None = None  # why it couldn't (its answer's first line), when it couldn't
    changes: list[EventChange] = []
    changes_left_out: int = 0
    change_counts: dict[str, int] = {}


_admin_runs_adapter = TypeAdapter(list[AdminRun])


def load_admin_runs() -> list[AdminRun]:
    return _admin_runs_adapter.validate_python(storage.read_json(config.ADMIN_RUNS_FILE, []))


def record_admin_run(
    action: AdminAction,
    target: str | None,
    changes: Iterable[EventChange],
    run_url: str | None = None,
    error: str | None = None,
) -> AdminRun:
    """Add an admin request's run to admin_runs.json (the latest config.ADMIN_RUNS_KEPT)."""
    every = list(changes)
    kept, left_out = bounded(every)
    run = AdminRun(
        finished_at=config.now_bogota().isoformat(timespec="seconds"),
        run_url=run_url,
        action=action,
        target=target,
        error=error,
        changes=kept,
        changes_left_out=left_out,
        change_counts=counts(every),
    )
    runs = [*load_admin_runs(), run][-config.ADMIN_RUNS_KEPT :]
    storage.write_json(config.ADMIN_RUNS_FILE, _admin_runs_adapter.dump_python(runs, mode="json"))
    return run
