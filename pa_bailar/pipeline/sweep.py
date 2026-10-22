"""Sweep: the regular sweep (the accounts whose turn it is, their new and edited posts, retention, the run's
statistics), with the admin tools' operations mixed in (manual_post.py, story_admin.py, hiding.py)."""

import logging
import statistics
import time
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import NamedTuple

from .. import config, links, public_post, storage
from ..account_options import AccountOptions, mentions_focus
from ..batching import BatchItem
from ..changes import changed_fields
from ..external import is_external
from ..gemini import (
    GeminiKeyError,
    OutOfTimeError,
    QuotaExhaustedError,
    RejectedRequestError,
    UnreadableAnswerError,
    quota_date,
)
from ..instagram import InstagramError, Post, is_rate_limited, published_at, slide_count
from ..models import AccountState, PostOutcome, ProcessedPost, StoredEvent, had_events
from ..stories import STORY_PREFIX
from ..text import parse_hhmm
from . import common
from .batches import Batches
from .common import ENDED, RETRYABLE_ERRORS, RunStats, caption_hash, clip_for, flyer_slide
from .hiding import Hiding
from .manual_post import ManualPosts
from .story_admin import StoryAdmin

log = logging.getLogger(__name__)

# How the style filter's reason ends (accounts.txt `solo:`): a post recorded with it is filtered again, with the day's
# words, whenever it comes back in the window (_filtered_before).
_OUTSIDE_FOCUS = "(la cuenta es solo para esos estilos)"

# What Flash's second opinion on a post the triage ruled out makes of it that the triage missed: an event published, or
# one hidden by hand (Sweep._check_triage). Not "discarded": past, recurring or out of Bogotá, the triage's "no" holds.
_MISSED: frozenset[PostOutcome] = frozenset({"event", "merged", "hidden"})
# The note on an event the triage had ruled out (the admin page's history).
MISSED_BY_TRIAGE = "el filtro (Flash-Lite) lo había descartado: Flash lo encontró"


def hours_overdue(state: AccountState | None, now: datetime, unproductive: bool = False, busy: bool = False) -> float:
    """How long past its turn an account is (negative: not its turn yet). Never read: always due. `unproductive`: its
    posts never become events (unproductive_accounts), so it takes its turn every other day, as a quiet one. An
    occasional one (its last post OCCASIONAL_AFTER_DAYS ago) too, unless something of it waits for its next read: an
    upcoming event or a post for Flash (`busy`: busy_accounts), a post no model could read yet, its first sweep."""
    if state is None or state.last_swept_at is None:
        return float("inf")
    silent = (now.date() - date.fromisoformat(state.latest_post)).days if state.latest_post else 0
    waits = busy or bool(state.unreadable) or not state.backfill_done
    occasional = silent >= config.OCCASIONAL_AFTER_DAYS and not waits
    if silent >= config.DORMANT_AFTER_DAYS:
        every = config.DORMANT_SWEEP_EVERY_HOURS
    elif silent >= config.QUIET_AFTER_DAYS or unproductive or occasional:
        every = config.QUIET_SWEEP_EVERY_HOURS
    else:
        every = config.SWEEP_EVERY_HOURS
    return (now - datetime.fromisoformat(state.last_swept_at)).total_seconds() / 3600 - every


def unproductive_accounts(posts: Iterable[tuple[str, bool]]) -> set[str]:
    """Of the posts read (each its account and whether it had events: models.had_events), the accounts with
    UNPRODUCTIVE_AFTER_POSTS of them and not one event: they take their turn every other day, like quiet ones (the
    owner, 8 Oct 2026). Their first event brings them back to daily."""
    read: Counter[str] = Counter()
    productive: set[str] = set()
    for account, events in posts:
        read[account] += 1
        if events:
            productive.add(account)
    return {account for account, count in read.items() if count >= config.UNPRODUCTIVE_AFTER_POSTS} - productive


def busy_accounts(posts: Iterable[ProcessedPost], events: Iterable[StoredEvent], now: datetime) -> set[str]:
    """The accounts the occasional tier never slows down (the owner, 9 Oct 2026): those with an event on the site that
    hasn't ended (its own, or one a post of theirs joined), whose changes or cancellation must show within a day, and
    those with a post read by a lighter model that a sweep would still re-read with Flash (only a read of the account
    does). A post is re-read only within the lookback, and it was published before it was first read: one read
    longer ago than that is out of reach, and waits for nothing (a first, deeper sweep's old posts)."""
    today = now.date().isoformat()
    upcoming = {event.id: event.account for event in events if (event.last_day or "") >= today}
    reachable = now - timedelta(days=config.DEFAULT_LOOKBACK_DAYS)
    busy = set(upcoming.values())
    for record in posts:
        waiting = record.provisional and datetime.fromisoformat(record.processed_at) >= reachable
        if waiting or any(event_id in upcoming for event_id in record.event_ids):
            busy.add(record.account)
    return busy


def overdue_by_account(
    accounts: Iterable[str],
    states: Mapping[str, AccountState],
    posts: Iterable[ProcessedPost],
    events: Iterable[StoredEvent],
    now: datetime,
) -> dict[str, float]:
    """How long past its turn each account is (hours_overdue), its tier read from its state, from the posts read
    (unproductive_accounts, busy_accounts) and from the events on the site (busy_accounts). The sweep's order and the
    status page's waiting accounts both count turns with it, so a tier counts the same in both."""
    posts = list(posts)
    unproductive = unproductive_accounts(
        (record.account, had_events(record.outcome, record.is_event_post)) for record in posts
    )
    busy = busy_accounts(posts, events, now)
    return {
        account: hours_overdue(states.get(account), now, account in unproductive, account in busy)
        for account in accounts
    }


def lead_days(posts: Iterable[ProcessedPost], events: Iterable[StoredEvent]) -> dict[str, list[int]]:
    """Per account, how many days ahead it announced each of its events: from the day (Bogotá) of its earliest post
    of the event to the event's first day (0: the same day). A post is the account's whose read recorded it (by its
    link: a collaboration's post joins another account's event), the event's own when its record is gone; a story
    isn't (no sweep reads one), nor an event first announced after it began (a festival's later days)."""
    reader = {record.permalink: record.account for record in posts}
    leads: dict[str, list[int]] = {}
    for event in events:
        if not event.date:
            continue
        first: dict[str, date] = {}
        for item in event.media:
            if item.post_id.startswith(STORY_PREFIX):
                continue
            account = reader.get(item.permalink, event.account)
            day = config.bogota_date(datetime.fromisoformat(item.published.replace("+0000", "+00:00")))
            first[account] = min(day, first.get(account, day))
        for account, day in first.items():
            if (lead := (date.fromisoformat(event.date) - day).days) >= 0:
                leads.setdefault(account, []).append(lead)
    return leads


def missed_as_past(posts: Iterable[ProcessedPost], now: datetime) -> Counter[str]:
    """Per account, the posts a turn's read found too late within config.SHORT_NOTICE_MISS_DAYS: discarded because
    their event had ended ("ya pasó"). Not its first read's (a new account's first sweep reads posts a month old, a
    bar's the past week's nights: config.SHORT_NOTICE_FIRST_READ_HOURS after its earliest record; once those are
    forgotten, a later read's are skipped there, so it errs towards no evidence), nor a post added by hand."""
    posts = list(posts)
    earliest: dict[str, datetime] = {}
    for record in posts:
        when = datetime.fromisoformat(record.processed_at)
        earliest[record.account] = min(when, earliest.get(record.account, when))
    since = now - timedelta(days=config.SHORT_NOTICE_MISS_DAYS)
    first_read = timedelta(hours=config.SHORT_NOTICE_FIRST_READ_HOURS)
    missed: Counter[str] = Counter()
    for record in posts:
        when = datetime.fromisoformat(record.processed_at)
        ended = record.outcome == "discarded" and ENDED in (record.detail or "").split(", ")
        if ended and not record.by_hand and when >= since and when >= earliest[record.account] + first_read:
            missed[record.account] += 1
    return missed


def short_notice_accounts(posts: Iterable[ProcessedPost], events: Iterable[StoredEvent], now: datetime) -> set[str]:
    """The accounts whose turn is the evening sweep (the owner, 17 Oct 2026): those that announce their nights the same
    day or the day before, so a morning read finds them over. From history: a turn's read found a post of theirs
    already past (missed_as_past), or they announce a median under config.SHORT_NOTICE_DAYS ahead over at least
    config.SHORT_NOTICE_MIN_EVENTS of their events on the site (lead_days). The sweep's order and the status page both
    take it from here."""
    posts = list(posts)
    habit = {
        account
        for account, leads in lead_days(posts, events).items()
        if len(leads) >= config.SHORT_NOTICE_MIN_EVENTS and statistics.median(leads) < config.SHORT_NOTICE_DAYS
    }
    return habit | set(missed_as_past(posts, now))


def is_evening_sweep(now: datetime) -> bool:
    """Whether a run starting at `now` is the day's evening sweep, the short-notice accounts' turn: the last of
    config.SWEEP_TIMES (21:00, Bogotá), from config.LATER_SWEEP_MARGIN_MINUTES before it (a run started a little
    early is that sweep) until midnight. A run by hand after midnight is the next day's, before its evening."""
    local = now.astimezone(config.BOGOTA_TZ)
    last = max(parse_hhmm(clock) for clock in config.SWEEP_TIMES)
    starts = datetime.combine(local.date(), last, config.BOGOTA_TZ)
    return local >= starts - timedelta(minutes=config.LATER_SWEEP_MARGIN_MINUTES)


def sweeps_in_quota_day(now: datetime) -> list[datetime]:
    """When the scheduled sweeps (config.SWEEP_TIMES, Bogotá) of `now`'s Gemini quota day (Pacific) start, in order:
    3:00, 6:30 and 21:00 of one Bogotá day (its quota day starts at 2:00 Bogotá, or 3:00 in the Pacific's winter)."""
    day = quota_date(now)
    today = now.astimezone(config.BOGOTA_TZ).date()
    starts = [
        datetime.combine(today + timedelta(days=offset), parse_hhmm(clock), config.BOGOTA_TZ)
        for offset in (-1, 0, 1)
        for clock in config.SWEEP_TIMES
    ]
    return sorted(moment for moment in starts if quota_date(moment) == day)


def later_sweeps_in_quota_day(now: datetime) -> int:
    """How many scheduled sweeps still start in `now`'s Gemini quota day, past config.LATER_SWEEP_MARGIN_MINUTES (one
    starting within it is this run, started a little early)."""
    soonest = now + timedelta(minutes=config.LATER_SWEEP_MARGIN_MINUTES)
    return sum(1 for starts in sweeps_in_quota_day(now) if starts > soonest)


def flash_reserve(now: datetime) -> float:
    """The share of Flash's daily budget a run starting at `now` leaves unused: each later sweep of the quota day keeps
    an equal share of the day's sweeps (two thirds at 3:00, one third at 6:30, nothing at 21:00). What a sweep leaves
    unused passes on to the next one."""
    later = later_sweeps_in_quota_day(now)
    return later / max(len(sweeps_in_quota_day(now)), later + 1) if later else 0.0


class RuledOut(NamedTuple):
    """A post the triage ruled out this run, as fetched, with its images: held for Flash's second opinion."""

    account: str
    post: Post
    published: datetime
    images: list[bytes]


def second_opinion_order(items: Iterable[RuledOut], records: Iterable[ProcessedPost]) -> list[RuledOut]:
    """The posts the triage ruled out, in the order Flash gives them a second opinion (Sweep._check_triage): those of
    accounts with an event on record first (they do post events: a "no" there is likelier wrong), then the others, then
    the unproductive ones (unproductive_accounts: none of their posts became an event); the newest first in each (its
    event, if any, is likelier ahead)."""
    read = [(record.account, had_events(record.outcome, record.is_event_post)) for record in records]
    productive = {account for account, events in read if events}
    unproductive = unproductive_accounts(read)

    def rank(item: RuledOut) -> tuple[int, float]:
        tier = 0 if item.account in productive else 2 if item.account in unproductive else 1
        return tier, -item.published.timestamp()

    return sorted(items, key=rank)


def upgrade_urgency(event_ids: list[str], events: dict[str, StoredEvent], today: str) -> tuple[int, str]:
    """Where a provisional post stands in the line for Flash: its soonest upcoming event first (one under way counts
    as today), then those without one (not an event, discarded, past), which a Flash read may still correct."""
    upcoming = [
        max(event.date, today)
        for event_id in event_ids
        if (event := events.get(event_id)) and event.date and (event.last_day or event.date) >= today
    ]
    return (0, min(upcoming)) if upcoming else (1, "")


def waiting_for_flash(
    posts: Mapping[str, ProcessedPost], events: dict[str, StoredEvent], today: str
) -> dict[str, list[str]]:
    """Per account, its provisional posts whose events haven't ended (upgrade_urgency), the soonest first: the ones a
    read of the account, in its turn or not, fetches for Flash wherever they are. Not a story (no read returns one), nor
    a post known only by its public page's id (the API knows it by another: a turn's read adopts it)."""
    waiting: dict[str, list[tuple[str, str]]] = {}
    for post_id, record in posts.items():
        if not record.provisional or post_id.startswith((STORY_PREFIX, public_post.ID_PREFIX)):
            continue
        soonest, day = upgrade_urgency(record.event_ids, events, today)
        if soonest == 0:
            waiting.setdefault(record.account, []).append((day, post_id))
    return {account: [post_id for _, post_id in sorted(items)] for account, items in waiting.items()}


def upgrade_read_depth(records: Iterable[ProcessedPost], oldest: str) -> int:
    """How many of an account's latest posts to ask for to reach back to a post read at `oldest` (its processed_at):
    its posts read since then, that one included, plus config.UPGRADE_READ_MARGIN_POSTS for posts never recorded; at
    least a turn's config.POSTS_PER_ACCOUNT, at most config.UPGRADE_READ_MAX_POSTS."""
    since = datetime.fromisoformat(oldest)
    newer = sum(1 for record in records if datetime.fromisoformat(record.processed_at) >= since)
    wanted = max(newer + config.UPGRADE_READ_MARGIN_POSTS, config.POSTS_PER_ACCOUNT)
    return min(wanted, config.UPGRADE_READ_MAX_POSTS)


def _bad_key(error: GeminiKeyError) -> SystemExit:
    """The run's end when the Gemini key doesn't work: every request would fail, so it fails loudly, saying why."""
    return SystemExit(
        f"Gemini API key doesn't work ({error}). Create a new key in Google AI Studio and update "
        "GEMINI_API_KEY (.env and the GitHub secret)."
    )


class Sweep(Batches, ManualPosts, StoryAdmin, Hiding):
    """The sweep (`run`) and the admin tools' operations (`add_post`, `add_story`, `hide_story`, `hide_event`), over
    one shared state (SweepBase)."""

    def run(self) -> RunStats:
        try:
            username = self.instagram.check_token()
        except InstagramError as error:
            raise SystemExit(
                f"Instagram token invalid ({error}). Generate a new one, run `python -m pa_bailar refresh-token` "
                "and update META_ACCESS_TOKEN (.env and the GitHub secret)."
            ) from error
        log.info("Instagram token OK (@%s)", username)

        self._share_flash()
        self._to_upgrade: list[tuple[str, Post, datetime]] = []
        self._ruled_out: list[RuledOut] = []  # held for Flash's second opinion (_check_triage)
        self._read_this_run: set[str] = set()  # the accounts whose turn's read was tried: no read for Flash after it
        self._waited_for_flash = False  # once a run (_wait_for_flash)
        self._batch = []  # posts waiting for a shared extraction request (batches.py)
        due = self._due_accounts()
        self.stats.due_accounts = due
        share = self._share_per_run()
        if len(due) > share:
            log.info("%s accounts' turn: %s this run, the rest first next run", len(due), share)
        for account in due[:share]:
            if self._instagram_full():
                break
            if self.rate_limited:
                log.warning("Instagram rate limit reached: the remaining accounts wait for the next run")
                break
            if self._out_of_time():  # no Gemini work would start: they wait, first next run (_due_accounts)
                break
            self.stats.accounts += 1
            self._read_this_run.add(account)
            with self._contained(account, f"@{account}"), self._read_cost(account):
                self._process_account(account)

        self._check_triage()  # before the upgrades: its small share, or they'd take all of Flash
        self._upgrade_by_urgency()
        self.stats.instagram_reads = self.read_costs.summary()  # the reads for Flash too
        self._apply_retention()
        self.stats.flyers_removed = storage.remove_unused_flyers(self.events)
        self.stats.gemini_requests = self.extractor.requests_this_run()
        self.stats.models_unavailable = self.extractor.models_unavailable()
        self.stats.external = self.extractor.external_report()
        self.stats.rate_limited = self.rate_limited
        self._record_instagram_usage()
        self.stats.out_of_time = self.time_up_logged
        storage.save_account_state(self.accounts)
        storage.save_meta(self.stats.for_meta())
        return self.stats

    def _share_flash(self) -> None:
        """Leave the later sweeps of this Gemini quota day their share of Flash (flash_reserve)."""
        now = datetime.now(UTC)
        if share := flash_reserve(now):
            self.extractor.reserve_flash(share)
            later = later_sweeps_in_quota_day(now)
            log.info("Flash: %d%% of today's requests left for %d later sweep(s) today", share * 100, later)

    def _upgrade_by_urgency(self) -> None:
        """Re-read provisional posts with Flash, while it has requests and time: the soonest events first, the ones
        visitors look at now (before, in the accounts' order, whatever came first took them). The posts the turn's
        reads fetched, and, in the same order, the accounts not read this run that hold provisional posts of events
        not over yet (waiting_for_flash), read beyond their turn for those posts only (_read_for_flash), up to
        config.UPGRADE_READS_PER_RUN and while Instagram's forecast has room."""
        today = config.now_bogota().date().isoformat()
        events = {event.id: event for event in self.events}

        def urgency(item: tuple[str, Post, datetime]) -> tuple[int, str]:
            record = self.processed.get(item[1]["id"])
            return upgrade_urgency(record.event_ids if record else [], events, today)

        queue = sorted(self._to_upgrade, key=urgency)
        waiting = waiting_for_flash(self.processed, events, today)
        reads = [
            (upgrade_urgency(self.processed[post_ids[0]].event_ids, events, today), account, post_ids)
            for account, post_ids in waiting.items()
            if account in self.options and account not in self._read_this_run
        ]
        reads = sorted(reads)[: config.UPGRADE_READS_PER_RUN]
        if not queue and not reads:
            return
        log.info("%d provisional posts to re-read with Flash, the soonest events first", len(queue))
        if reads:
            log.info(
                "%d accounts not read this run hold provisional posts of upcoming events: read for Flash",
                len(reads),
            )
        while queue or reads:
            if (not self.extractor.can_upgrade() and not self._wait_for_flash()) or self._out_of_time():
                left = len(queue) + sum(len(post_ids) for _, _, post_ids in reads)
                log.info("   no Flash (or time) left: %d wait for a later run", left)
                break
            if reads and (not queue or reads[0][0] <= urgency(queue[0])):
                _, account, post_ids = reads.pop(0)
                fetched = self._read_for_flash(account, post_ids)
                if fetched is None:  # Instagram has no room for more reads
                    reads = []
                queue = sorted([*queue, *(fetched or [])], key=urgency)
                continue
            account, post, published = queue.pop(0)
            record = self.processed.get(post["id"])
            if not record or not record.provisional:
                continue  # read again meanwhile (e.g. its caption was edited)
            log.info("   %s upgrading provisional analysis %s", f"{published:%Y-%m-%d}", post["permalink"])
            with self._contained(account, f"the upgrade of {post['permalink']}"):
                self._upgrade_post(account, post, published)

    def _check_triage(self) -> None:
        """Flash's second opinion on the triage (config.TRIAGE_CHECKS_PER_RUN; the owner, 17 Oct 2026): a few of the
        posts the triage ruled out this run, as they were fetched (no other Instagram read), in second_opinion_order,
        each extracted by Flash while it can be used as for an upgrade (can_upgrade: budget beyond the later sweeps'
        share, not paused as busy; never waiting for it) and time is left. Before the upgrades, a small fixed share
        (the owner, 22 Oct 2026): after them it never ran, since they took all of Flash every run. The upgrades take
        the rest. What Flash finds is stored as any Flash reading (_check_ruled_out)."""
        held, self._ruled_out = self._ruled_out, []
        sample = second_opinion_order(held, self.processed.values())[: config.TRIAGE_CHECKS_PER_RUN]
        if not sample:
            return
        log.info("%d posts ruled out by triage this run: Flash checks %d of them", len(held), len(sample))
        for item in sample:
            if not self.extractor.can_upgrade() or self._out_of_time():
                log.info("   no Flash (or time) left for the triage's checks")
                break
            record = self.processed.get(item.post["id"])
            if record is None or record.outcome != "not_event" or record.triage_checked:
                continue  # read again meanwhile
            log.info("   %s triage said no event, Flash reads %s", f"{item.published:%Y-%m-%d}", item.post["permalink"])
            with self._contained(item.account, f"the triage check of {item.post['permalink']}"):
                self._check_ruled_out(item)

    def _check_ruled_out(self, item: RuledOut) -> None:
        """Flash's reading of a post the triage ruled out, stored as any Flash reading (the safeguards, merging, the
        post's record: Flash's model, not provisional), the record marked as checked. An event published (_MISSED) is a
        triage miss, counted and noted; none (or only past, recurring or out-of-Bogotá ones) agrees with the triage.
        A failure leaves the triage's record as it was: the post isn't held past this run."""
        account, post, published, images = item
        try:
            analysis, model, _ = self.extractor.extract(
                account,
                post,
                published,
                images,
                self._known_events(account, published),
                allow_provisional=False,
                rules=self._rules(account, post["id"]),
            )
        except RETRYABLE_ERRORS as error:
            log.info("     no second opinion: %s", error)
            return
        if not self._store_analysis(account, post, images, analysis, model, provisional=False, post_counted=True):
            return
        record = self.processed[post["id"]]
        record.triage_checked = True
        self._save()
        self.stats.triage_checked += 1
        if record.outcome not in _MISSED:
            log.info("     Flash agrees with the triage (%s)", record.outcome)
            return
        self.stats.triage_misses += 1
        for event in self.events:
            change = self.stats.changes.get(event.id)
            if event.id in record.event_ids and change is not None and change.kind == "new":
                self.stats.note("new", event, MISSED_BY_TRIAGE)
        log.warning("     the triage missed it: Flash found %s (%s)", ", ".join(record.event_ids), record.outcome)

    def _hold_ruled_out(self, item: RuledOut) -> None:
        """Hold a post the triage ruled out for Flash's second opinion at the run's end (_check_triage), with its
        images: the first config.TRIAGE_CHECKS_HELD of the run's in second_opinion_order."""
        if config.TRIAGE_CHECKS_PER_RUN <= 0:
            return
        self._ruled_out.append(item)
        if len(self._ruled_out) > config.TRIAGE_CHECKS_HELD:
            ordered = second_opinion_order(self._ruled_out, self.processed.values())
            self._ruled_out = ordered[: config.TRIAGE_CHECKS_HELD]

    def _read_for_flash(self, account: str, post_ids: list[str]) -> list[tuple[str, Post, datetime]] | None:
        """Read an account beyond its turn, only for these provisional posts: deep enough to reach the oldest
        (_flash_depth), and only they are queued for Flash. Not its turn: no other post of it is read, and nothing that
        sets its turn changes (last_swept_at, latest_post), so a 6:30 read for Flash doesn't take a 21:00 account. None
        when Instagram's forecast has no room (the run isn't marked as stopped: no account of a turn waits for it)."""
        usage = self.instagram.app_usage_percent
        if self.rate_limited or self.read_costs.stop_reason(usage) is not None:
            log.info(
                "   Instagram quota %s%% used, a read costs up to %s%%: no more reads for Flash this run",
                usage,
                self.read_costs.expected_cost(),
            )
            return None
        depth = self._flash_depth(account) or config.POSTS_PER_ACCOUNT
        log.info(
            "== @%s (not its turn: %d provisional posts for Flash, its last %d posts)", account, len(post_ids), depth
        )
        self.stats.upgrade_reads += 1
        try:
            with self._read_cost(account):
                posts = self.instagram.fetch_recent_posts(account, limit=depth)
        except InstagramError as error:
            log.warning("   could not fetch posts: %s", error)
            if is_rate_limited(error):
                self.rate_limited = True
                self.stats.instagram_stop = "meta"
                return None
            return []
        return self._fetched_for_flash(account, posts, post_ids)

    def _fetched_for_flash(
        self, account: str, posts: list[Post], post_ids: list[str]
    ) -> list[tuple[str, Post, datetime]]:
        """The posts among those fetched that wait for Flash (`post_ids`), to queue. One not returned (deleted, or
        deeper than the read went) is logged and counted (upgrade_misses), and tried again on a later run."""
        fetched = {post["id"]: post for post in posts}
        for post_id in post_ids:
            if post_id not in fetched:
                log.info(
                    "   not among its last %d posts, left as read: %s", len(posts), self.processed[post_id].permalink
                )
                self.stats.upgrade_misses += 1
        return [(account, post, published_at(post)) for post_id in post_ids if (post := fetched.get(post_id))]

    def _waiting_for_flash(self, account: str) -> list[str]:
        """The account's provisional posts of events not over yet (waiting_for_flash), the soonest first."""
        today = config.now_bogota().date().isoformat()
        events = {event.id: event for event in self.events}
        return waiting_for_flash(self.processed, events, today).get(account, [])

    def _flash_depth(self, account: str) -> int:
        """How deep a read of the account must go to reach its provisional posts waiting for Flash (upgrade_read_depth);
        0 when none waits."""
        post_ids = self._waiting_for_flash(account)
        if not post_ids:
            return 0
        oldest = min((self.processed[post_id].processed_at for post_id in post_ids), key=datetime.fromisoformat)
        return upgrade_read_depth((r for r in self.processed.values() if r.account == account), oldest)

    @contextmanager
    def _read_cost(self, account: str) -> Iterator[None]:
        """Record what a read of the account cost Instagram's quota (read_costs), if a call reached Meta, even when
        the read failed."""
        call = self.instagram.last_call
        try:
            yield
        finally:
            if self.instagram.last_call is not None and self.instagram.last_call is not call:
                log.info("   %s", self.read_costs.record(account, self.instagram.last_call).line())

    def _wait_for_flash(self) -> bool:
        """Flash only paused as busy, with budget left: wait for its pause to end, once a run, if the run's time
        budget allows it, and say whether it's ready then. Flash answered 503 at sweep times for hours on 6–7 Oct, so
        its upgrades found every model paused and none was done (34 waited on 7 Oct at 21:09, 9 of the run's 30
        minutes used); a pause of BUSY_PAUSE_SECONDS later it may answer. Out of quota, nothing to wait for."""
        if self._waited_for_flash:
            return False
        ready = self.extractor.flash_ready_at()
        if ready is None:
            return False
        wait = ready - time.monotonic()
        left = self.started + config.MAX_RUN_MINUTES * 60 - time.monotonic() - config.FLASH_WAIT_MARGIN_SECONDS
        if wait > left:
            return False
        self._waited_for_flash = True
        if wait > 0:
            log.info("   Flash busy a moment ago: waiting %d s for it before the upgrades", wait)
            time.sleep(wait)
        return self.extractor.can_upgrade()

    @contextmanager
    def _contained(self, account: str, what: str) -> Iterator[None]:
        """An unexpected error (e.g. a malformed answer) loses `what`, an account's run or an upgrade, not the run's:
        logged and counted against `account`. A key that doesn't work ends the run loudly: every request would fail."""
        try:
            yield
        except GeminiKeyError as error:
            raise _bad_key(error) from error
        except Exception:
            log.exception("   unexpected error with %s, continuing", what)
            self.stats.count(account, "errors")

    def _lighter_readings(self, post_id: str) -> dict[str, StoredEvent]:
        """The events this post announced that only lighter models read, as read: what Flash's reading is compared
        with. An event another post had Flash read already isn't: Flash's reading may not replace it there."""
        return {
            event.id: event
            for event in self.events
            if any(media.post_id == post_id for media in event.media) and self._only_lighter_reads(event)
        }

    def _audit_upgrade(self, before: dict[str, StoredEvent]) -> None:
        """What Flash changed in a lighter model's reading of these events (changes.changed_fields), counted per field
        in the run's record (upgrade_changes): how the backup reads hold up on new posts, not only on the test set (the
        owner, 7 Oct 2026: is it more robust now?). An event Flash's reading didn't keep counts as "dropped"."""
        if not before:
            return
        after = [event for event in self.events if event.id in before]
        found = {"compared": len(before), "dropped": len(before) - len(after)}
        changed: set[str] = set()
        for event in after:
            for name in changed_fields(before[event.id], event):
                found[name] = found.get(name, 0) + 1
                changed.add(name)
        changes = self.stats.upgrade_changes
        for key, count in found.items():
            changes[key] = changes.get(key, 0) + count
        log.info("     Flash's reading: %s", "changed " + ", ".join(sorted(changed)) if changed else "the same")

    def _instagram_full(self) -> bool:
        """Whether the next read would take Instagram's quota past config.INSTAGRAM_USAGE_CEILING (the share now plus
        its expected cost: instagram_usage.ReadCosts): then the remaining accounts wait, first next run. Not once Meta
        stopped the run itself (_fetch_posts): its reason stays "meta", not our ceiling (bug-squash pass, 9 Oct)."""
        if self.rate_limited:
            return False
        usage = self.instagram.app_usage_percent
        reason = self.read_costs.stop_reason(usage)
        if reason is None:
            return False
        log.warning(
            "Instagram quota %s%% used, a read costs up to %s%%: stopping before %s%%; the remaining accounts wait "
            "for the next run",
            usage,
            self.read_costs.expected_cost(),
            self.read_costs.ceiling,
        )
        self.rate_limited = True
        self.stats.instagram_stop = reason
        return True

    def _record_instagram_usage(self) -> None:
        """The run's highest reading of Instagram's quota, and which of Meta's measures it was (calls, CPU time, total
        time): what drives a run to its ceiling (config.INSTAGRAM_USAGE_CEILING) decides what to change."""
        peak, detail = self.instagram.peak_usage_percent, self.instagram.peak_usage_detail
        self.stats.instagram_usage, self.stats.instagram_usage_detail = peak, dict(detail)
        if detail:
            measures = ", ".join(f"{key} {value}%" for key, value in sorted(detail.items()))
            log.info("Instagram quota at its highest this run: %s%% (%s)", peak, measures)
        if reads := self.stats.instagram_reads:
            log.info(
                "Instagram reads: %s, %.1f s each (median %.1f s, at most %.1f s); %s%% of the quota each (at most "
                "%s%%, @%s); headers %s",
                reads.accounts,
                reads.mean_seconds,
                reads.median_seconds,
                reads.max_seconds,
                reads.mean_cost,
                reads.max_cost,
                reads.max_cost_account,
                reads.headers,
            )

    def _share_per_run(self) -> int:
        """How many accounts one sweep reads: its share of the day's sweeps, plus a margin for late ones."""
        if self.all_accounts:
            return len(storage.read_accounts())
        runs_per_day = max(1, len(config.SWEEP_TIMES))
        return -(-len(storage.read_accounts()) // runs_per_day) + config.EXTRA_ACCOUNTS_PER_RUN

    def _due_accounts(self) -> list[str]:
        """The accounts whose turn it is, in reading order: accounts in their regular sweep before new ones (a
        new account's first, deeper sweep can take days of quota), and within each, those that waited longest
        first. So an account a sweep didn't reach (its share, Instagram's limit) is first next time. A sweep with room
        in its share also reads, after them, those due within config.READ_AHEAD_HOURS: the 3:00 sweep takes part of
        the 6:30 sweep's accounts (due at 4:30), and they keep the 3:00 sweep from then on. Short-notice accounts
        (short_notice_accounts) take their turn in the evening sweep, first among the due ones, so neither its share
        nor Instagram's stop pushes them to the next morning; a sweep before it reads one only
        config.SHORT_NOTICE_WAIT_HOURS past its turn (never starved), and reading ahead never takes one."""
        followed = storage.read_accounts()
        now = config.now_bogota()
        overdue = overdue_by_account(followed, self.accounts, self.processed.values(), self.events, now)
        evening = is_evening_sweep(now)
        short = set() if self.all_accounts else short_notice_accounts(self.processed.values(), self.events, now)

        def turn_starts(account: str) -> float:
            """Hours past its turn this sweep reads it from: a short-notice one waits for the evening."""
            return config.SHORT_NOTICE_WAIT_HOURS if account in short and not evening else 0

        due = (
            followed
            if self.all_accounts
            else [account for account in followed if overdue[account] >= turn_starts(account)]
        )
        if held := [account for account in followed if 0 <= overdue[account] < turn_starts(account)]:
            log.info("%s short-notice accounts wait for the evening sweep: %s", len(held), ", ".join(held))
        if not self.all_accounts and len(due) < self._share_per_run():
            ahead = [
                account
                for account in followed
                if -config.READ_AHEAD_HOURS <= overdue[account] < 0 and account not in short
            ]
            if ahead:
                log.info(
                    "%s accounts' turn, and %s due within %s h read ahead",
                    len(due),
                    len(ahead),
                    config.READ_AHEAD_HOURS,
                )
            due += ahead

        def is_new(account: str) -> bool:
            state = self.accounts.get(account)
            return state is None or not state.backfill_done

        def after_short_notice(account: str) -> bool:
            """In the evening sweep, every account but the short-notice ones goes after them."""
            return not (evening and account in short)

        return sorted(due, key=lambda account: (is_new(account), after_short_notice(account), -overdue[account]))

    def _apply_retention(self) -> None:
        """Archive long-past events (storage.archive_events) and forget old analyzed posts, so the site's data and
        flyers don't grow forever. Their full flyers and clips go with the unused ones (remove_unused_flyers)."""
        now = config.now_bogota()
        oldest_date = (now - timedelta(days=config.EVENT_RETENTION_DAYS)).date().isoformat()
        kept = [event for event in self.events if not event.last_day or event.last_day >= oldest_date]
        expired = [event for event in self.events if event not in kept]
        self.stats.events_expired = storage.archive_events(expired) if expired else 0
        for event in expired:
            self.stats.note("archived", event, f"terminó hace más de {config.EVENT_RETENTION_DAYS} días")
        self.events = kept
        past = [key for key, item in self.hidden.items() if (item.event.last_day or "") < oldest_date]
        for key in past:  # long past: no post of it will be read again
            del self.hidden[key]

        # Never forget a post the lookback could still fetch (e.g. a manual run with --days 60).
        keep_days = max(config.PROCESSED_RETENTION_DAYS, self.lookback.days + 1)
        oldest_record = now - timedelta(days=keep_days)
        old = [pid for pid, rec in self.processed.items() if datetime.fromisoformat(rec.processed_at) < oldest_record]
        for post_id in old:
            del self.processed[post_id]
        self.stats.processed_forgotten = len(old)

        if self.stats.events_expired or old or past:
            log.info(
                "Retention: %s past events archived, %s old post records forgotten", self.stats.events_expired, len(old)
            )
            self._save()

    # ---------- per account ----------

    def _process_account(self, account: str) -> None:
        state = self.accounts.setdefault(account, AccountState(first_seen=config.now_bogota().date().isoformat()))
        if self._is_bar(account) and not state.backfill_done:
            state.backfill_done = True  # a bar's old posts are past nights: no deeper first sweep (account_options)
        backfill = not state.backfill_done
        account_stats = self.stats.account(account)
        account_stats.backfill = backfill
        log.info("== @%s%s", account, " (new account: deeper first sweep)" if backfill else "")

        posts = self._fetch_posts(account, state, backfill)
        if posts is None:
            return
        if posts:
            account_stats.latest_post = config.bogota_date(max(published_at(p) for p in posts)).isoformat()
            state.latest_post = account_stats.latest_post
        window = timedelta(days=config.BACKFILL_DAYS) if backfill else self.lookback
        cutoff = datetime.now(UTC) - window
        # The posts waiting for a shared extraction request (batches.py) are read before the turn's end, error or not.
        with self._account_batch(account):
            # Oldest first, so a flyer is usually stored before the video or reminder that follows it.
            for post in sorted(posts, key=lambda p: p["timestamp"]):
                published = published_at(post)
                if published >= cutoff:
                    self._read_post(account, post, published)
        # Its provisional posts of events not over yet, older than the window too (the read went back to them:
        # _fetch_posts): re-read with Flash after every account, as the window's are (_read_post).
        waiting = self._fetched_for_flash(account, posts, self._waiting_for_flash(account))
        self._to_upgrade += [item for item in waiting if item[2] < cutoff]
        fetched = {post["id"] for post in posts}  # a post no longer fetched is never read again
        state.unreadable = {post_id: runs for post_id, runs in state.unreadable.items() if post_id in fetched}

        self._complete_media(posts)
        # Read: its turn is over, unless posts wait (Gemini's quota, time): then it's due again next run.
        if account_stats.pending == 0:
            state.last_swept_at = config.now_bogota().isoformat(timespec="seconds")
        if backfill and account_stats.pending == 0:
            state.backfill_done = True
            log.info("   first sweep complete: from now on, regular sweep")
        storage.save_account_state(self.accounts)

    def _fetch_posts(self, account: str, state: AccountState, backfill: bool) -> list[Post] | None:
        """The account's latest posts (more for its first, deeper sweep, and back to its oldest provisional post of an
        event not over yet: _flash_depth). None when Instagram couldn't give them: its turn is over, unless Instagram's
        rate limit stopped it."""
        try:
            limit = config.BACKFILL_POSTS if backfill else max(config.POSTS_PER_ACCOUNT, self._flash_depth(account))
            return self.instagram.fetch_recent_posts(account, limit=limit)
        except InstagramError as error:
            log.error("   could not fetch posts: %s", error)
            self.rate_limited = is_rate_limited(error)
            if self.rate_limited:
                self.stats.instagram_stop = "meta"  # Meta's own limit, before our ceiling
            else:
                state.last_swept_at = config.now_bogota().isoformat(timespec="seconds")  # tried: its turn is over
            self.stats.count(account, "errors")
            self.stats.account(account).fetch_failed = True
            return None

    def _read_post(self, account: str, post: Post, published: datetime) -> None:
        """One post within the window: analyzed if it's new, again if its caption was edited, with Flash if it was
        read provisionally; nothing if it's known and unchanged."""
        record = self.processed.get(post["id"]) or self._adopt_public_record(post)
        post_hash = caption_hash(post)
        if record is None:
            log.info("   %s %-14s %s", f"{published:%Y-%m-%d}", post["media_type"], post["permalink"])
            if self._out_of_time() or self._analyze_new_post(account, post, published) is False:
                self.stats.count(account, "pending")
        elif record.caption_hash is None:
            record.caption_hash = post_hash  # analyzed before captions were fingerprinted
            self._save()
        elif record.caption_hash != post_hash:
            if self._out_of_time():
                self.stats.count(account, "pending")  # still edited next run: the account stays due, read then
                return
            log.info("   %s caption edited, analyzing again %s", f"{published:%Y-%m-%d}", post["permalink"])
            # A post that had events skips the filter: the extraction decides again, and takes its old
            # events off the site if it no longer announces them ("CANCELADO"). Others go through the
            # filter as usual (Flash-Lite), keeping Flash's small quota for events.
            announced = had_events(record.outcome, record.is_event_post)
            read = self._analyze_new_post(account, post, published, triage=not announced, reread=True)
            if read:
                self.stats.reanalyzed += 1
            elif read is False:  # no quota or time left, or an error: the account stays due, so the edit is read soon
                self.stats.count(account, "pending")
        elif self._filtered_before(account, post, record):
            log.info("   %s now names the account's styles, analyzing %s", f"{published:%Y-%m-%d}", post["permalink"])
            read = False if self._out_of_time() else self._analyze_new_post(account, post, published, reread=True)
            if read:
                self.stats.reanalyzed += 1
            elif read is False:  # None: waiting in the batch, counted when it's read (batches.py)
                self.stats.count(account, "pending")
        elif record.provisional:
            self._to_upgrade.append((account, post, published))  # re-read after every account, by urgency

    def _adopt_public_record(self, post: Post) -> ProcessedPost | None:
        """A post added by hand from its public page, now among the account's posts: the same post, not a new
        one (no second Gemini request). It's analyzed again only if its caption changed since."""
        code = links.post_code(post["permalink"])
        known_id = self._record_id(code, public_only=True) if code else None
        if known_id is None:
            return None
        self._rename_post(known_id, post["id"])
        record = self.processed[post["id"]]
        if self._same_caption(post):
            record.caption_hash = caption_hash(post)  # the API's spacing from now on
        return record

    def _complete_media(self, posts: list[Post]) -> None:
        """Add what posts stored before clips and slide counts existed are missing, from their fresh copy
        (Instagram's video links expire, so only posts just fetched can get a clip)."""
        by_id = {post["id"]: post for post in posts}
        changed = False
        for event in self.events:
            for media in event.media:
                post = by_id.get(media.post_id)
                if post is None:
                    continue
                if media.slides is None and (slides := slide_count(post)):
                    media.slides, changed = slides, True
                needs_clip = media.preview is None and media.flyer and media.media_type != "IMAGE"
                if needs_clip and media.flyer and (preview := clip_for(post, flyer_slide(media.flyer))):
                    media.preview, changed = preview, True
        if changed:
            self._save()

    def _out_of_time(self) -> bool:
        """True once the run has used its time budget (MAX_RUN_MINUTES): start no more Gemini work."""
        over = time.monotonic() - self.started >= config.MAX_RUN_MINUTES * 60
        if over and not self.time_up_logged:
            log.warning("Run time budget used (%s min): the rest waits for the next run", config.MAX_RUN_MINUTES)
            self.time_up_logged = True
        return over

    # ---------- per post ----------

    def _analyze_new_post(
        self, account: str, post: Post, published: datetime, triage: bool = True, reread: bool = False
    ) -> bool | None:
        """Triage, then extract if it's an event (`triage=False`: extract directly). False when the post must be
        retried next run. With batched extraction on (batches.py), a post to extract waits in the account's batch:
        None, and it's counted (pending, or re-analyzed when it was read before: `reread`) once the batch is read."""
        # A post that had events (triage=False) is read again whatever its caption says now ("CANCELADO").
        if triage and self._outside_focus(account, post):
            return True
        if not self.extractor.can_analyze():
            return False  # no quota left today: it waits (no download, not an error)
        try:
            images = common.download_images(post)  # through the module: tests replace it
        except OSError as error:
            return self._retry_later(account, f"could not download images: {error}")

        verdict, triage_model = None, None
        if triage:
            try:
                verdict, triage_model = self.extractor.triage(
                    account, post, published, images, rules=self._rules(account, post["id"])
                )
            except QuotaExhaustedError as error:
                if isinstance(error, OutOfTimeError) or self.extractor.can_extract_with_flash():
                    # Flash-Lite out of today's quota: wait for it rather than spend Flash's small one on every post.
                    log.info("     waits for the next run (triage): %s", error)
                    return False
                # Flash is out too, so the extraction is the last resort's: it decides alone. Never a last-resort
                # triage: its "no" would be final, and Groq's tokens a minute don't fit a triage and an extraction.
                log.info("     Flash-Lite and Flash out of quota: extracting directly (the last resort)")
            except RETRYABLE_ERRORS as error:
                # Triage unavailable: let the extraction decide on its own.
                log.info("     triage unavailable (%s), extracting directly", error)

        if verdict is not None and not verdict.is_event_post:
            self._record_not_event(account, post, verdict.reason, triage_model or "-")
            if triage_model and not self._by_hand(post["id"]):  # the triage's own "no": Flash may check it
                self._hold_ruled_out(RuledOut(account, post, published, images))
            return True
        if self._batching():
            rules = self._rules(account, post["id"])
            self._queue_extraction(account, BatchItem(post, published, images, rules=rules, reread=reread))
            return None
        return self._extract_and_store(account, post, published, images)

    def _extract_and_store(self, account: str, post: Post, published: datetime, images: list[bytes]) -> bool:
        """Extract a post's events and store them. False when it must be retried next run."""
        try:
            known = self._known_events(account, published)
            analysis, model, provisional = self.extractor.extract(
                account, post, published, images, known, rules=self._rules(account, post["id"])
            )
        except RejectedRequestError as error:
            # Gemini refuses this post itself (e.g. an image it can't read, an answer too long): retrying would spend
            # quota on every run and keep a new account's first sweep from ever finishing. Record it and move on.
            log.warning("     Gemini rejected the post, skipping it: %s", error)
            return self._record_rejected(account, post, f"rechazado por Gemini: {error}")
        except QuotaExhaustedError as error:
            log.info("     waits for the next run: %s", error)
            return False
        except UnreadableAnswerError as error:
            runs = self._unreadable_run(account, post["id"])
            if runs < config.UNREADABLE_RUNS:
                return self._retry_later(account, f"{error} (run {runs} of {config.UNREADABLE_RUNS})")
            log.warning("     no valid answer on %s runs, giving the post up: %s", runs, error)
            reason = f"rechazado: Gemini no dio una respuesta válida en {runs} corridas"
            return self._record_rejected(account, post, reason)
        except RETRYABLE_ERRORS as error:
            return self._retry_later(account, str(error))

        return self._store_analysis(account, post, images, analysis, model, provisional)

    def _record_rejected(self, account: str, post: Post, reason: str) -> bool:
        """A post Gemini can't read, recorded so it isn't retried (an error of the run, not pending)."""
        self.stats.count(account, "errors")
        self._record_processed(account, post, False, reason, "-", provisional=False)
        self._set_outcome(post, "rejected")
        self._save()
        return True

    def _unreadable_run(self, account: str, post_id: str) -> int:
        """Count one more run on which no model gave valid JSON for this post: how many so far (config.UNREADABLE_RUNS
        gives it up). Kept in the account's state (AccountState.unreadable), cleared once the post is recorded."""
        state = self.accounts.setdefault(account, AccountState(first_seen=config.now_bogota().date().isoformat()))
        state.unreadable[post_id] = state.unreadable.get(post_id, 0) + 1
        storage.save_account_state(self.accounts)
        return state.unreadable[post_id]

    def _outside_focus(self, account: str, post: Post) -> bool:
        """An account limited to some styles (accounts.txt `solo:`, account_options): a post whose caption names
        none of them is recorded as no event before any Gemini request (free). Read again if its caption is edited;
        a post added by hand isn't filtered."""
        focus = self.options.get(account, AccountOptions()).focus
        if self._by_hand(post["id"]) or mentions_focus(post.get("caption"), focus):
            return False
        reason = f"no menciona {' ni '.join(focus)} {_OUTSIDE_FOCUS}"
        self._record_not_event(account, post, reason, "-")
        return True

    def _filtered_before(self, account: str, post: Post, record: ProcessedPost) -> bool:
        """A post the style filter left out that passes it now: the filter's words grew since (the audit of 7 Oct
        2026 added "salsoteca", "Fania", "bachazouk"…), or the account lost its `solo:`. Checked again for free each
        time it's in the window."""
        focus = self.options.get(account, AccountOptions()).focus
        return (record.reason or "").endswith(_OUTSIDE_FOCUS) and mentions_focus(post.get("caption"), focus)

    def _upgrade_post(self, account: str, post: Post, published: datetime) -> None:
        """Re-extract a provisional post with Flash; keep the provisional result if that fails. A post the last
        resort read without a triage (Flash-Lite was out) and found no event in goes through the triage first, as a
        new post would: Flash is spent on it only if Flash-Lite says it's an event."""
        record = self.processed[post["id"]]
        try:
            images = common.download_images(post)
            if record.outcome == "not_event" and is_external(record.model):
                verdict, triage_model = self.extractor.triage(
                    account, post, published, images, rules=self._rules(account, post["id"])
                )
                if not verdict.is_event_post:
                    self._record_processed(account, post, False, verdict.reason, triage_model, provisional=False)
                    self._set_outcome(post, "not_event")
                    self._save()
                    self.stats.upgraded += 1
                    log.info("     not an event (triage): %s", verdict.reason)
                    return
            known = self._known_events(account, published)
            analysis, model, _ = self.extractor.extract(
                account, post, published, images, known, allow_provisional=False, rules=self._rules(account, post["id"])
            )
        except RejectedRequestError as error:
            log.warning("     Gemini rejected the upgrade, keeping the provisional analysis: %s", error)
            self.processed[post["id"]].provisional = False  # stop retrying it
            self._save()
            return
        except UnreadableAnswerError as error:
            if (runs := self._unreadable_run(account, post["id"])) < config.UNREADABLE_RUNS:
                log.info("     upgrade postponed (run %s of %s): %s", runs, config.UNREADABLE_RUNS, error)
                return
            log.warning("     no valid answer on %s runs, keeping the provisional analysis: %s", runs, error)
            self.processed[post["id"]].provisional = False  # stop spending Flash's quota on it
            self.accounts[account].unreadable.pop(post["id"], None)
            self._save()
            return
        except RETRYABLE_ERRORS as error:
            log.info("     upgrade postponed: %s", error)
            return
        before = self._lighter_readings(post["id"])
        if self._store_analysis(account, post, images, analysis, model, provisional=False, count_as_new=False):
            self.stats.upgraded += 1
            self._audit_upgrade(before)
