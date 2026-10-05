"""SweepBase: what the sweep and the admin tools share. The state (events, analyzed posts, events hidden by hand,
accounts), storing one analyzed post (its events new or merged, its record, a cancelled post's events taken down),
and keeping one identity per post (the API's id, or public-<id> when it was read from its public page)."""

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, cast

from .. import config, links, public_post, storage
from ..account_options import AccountOptions
from ..extraction import EventExtractor
from ..ids import new_event_id
from ..instagram import InstagramClient, Post
from ..merging import already_stored, detach_post, find_existing, matches_hidden, merge_into, refused_link
from ..models import (
    EventDetails,
    EventMedia,
    ExtractedEvent,
    HiddenEvent,
    PostAnalysis,
    PostOutcome,
    ProcessedPost,
    StoredEvent,
)
from ..normalize import (
    GUESSED_STYLES_DOUBT,
    MULTI_DOUBT,
    doubtful_city,
    normalize_event,
    style_family,
    styles_in_text,
)
from ..prompts import account_rules
from ..text import fold
from . import common
from .common import Extractor, PostSource, RunStats, caption_hash, has_ended, media_for, unpublishable

log = logging.getLogger(__name__)


def _with_doubt(event: ExtractedEvent, doubt: str) -> ExtractedEvent:
    return event if doubt in event.doubts else event.model_copy(update={"doubts": [*event.doubts, doubt]})


# A caption or Gemini's reason saying the event is off (folded text: lowercase, no accents).
_CANCELLED = re.compile(
    r"\b(cancelad[oa]s?|cancelamos|se cancela|cancell?ed|aplazad[oa]s?|aplazamos|se aplaza|pospuest[oa]s?"
    r"|posponemos|se pospone|postponed|suspendid[oa]s?|suspendemos)\b"
)


def _says_cancelled(post: Post, analysis: PostAnalysis) -> bool:
    """Whether the post's caption, or Gemini's reason for finding no event in it, says it's cancelled or postponed."""
    return bool(_CANCELLED.search(fold(f"{post.get('caption') or ''} {analysis.reason}")))


def _days(event: EventDetails) -> str:
    """An event's day for the log: its date, or first → last day (a workshop series: and how many sessions)."""
    sessions = f" ({len(event.sessions)} sessions)" if event.sessions else ""
    return f"{event.date} → {event.end_date}{sessions}" if event.end_date else str(event.date)


def _details(event: ExtractedEvent) -> dict[str, Any]:
    return event.model_dump(include=set(EventDetails.model_fields))


class SweepBase:
    def __init__(
        self,
        lookback_days: int,
        instagram: PostSource | None = None,
        extractor: Extractor | None = None,
        all_accounts: bool = False,
    ):
        """Clients are built from the environment unless given (tests pass fakes). `all_accounts` reads every
        account now, whether it's its turn or not (a manual full sweep)."""
        self.all_accounts = all_accounts
        self.lookback = timedelta(days=lookback_days)
        self.instagram = instagram or InstagramClient.from_env()
        self.extractor = extractor or EventExtractor(config.require_env("GEMINI_API_KEY"))
        self.hidden = storage.load_hidden_events()
        # An event hidden by hand stays off the site, even if the data PR of the run that hid it wasn't merged.
        stored = storage.load_events()
        self.options = storage.read_account_options()
        # An event is a bar's when its account is one now (accounts.txt): marking or unmarking an account updates
        # its stored events too.
        self.events = [
            event if event.bar == self._is_bar(event.account) else event.model_copy(update={"bar": not event.bar})
            for event in stored
            if event.id not in self.hidden
        ]
        if self.events != stored:
            storage.save_events(self.events)
        self.processed = storage.load_processed_posts()
        self.by_hand = False  # adding a post or story by hand: it may publish again what was hidden
        self.accounts = storage.load_account_state()
        self.stats = RunStats()
        self.started = time.monotonic()
        self.time_up_logged = False
        self.rate_limited = False  # Meta is throttling the app: the remaining accounts wait for the next run

    def _safeguarded(self, account: str, post: Post, event: ExtractedEvent, several: bool) -> ExtractedEvent:
        """An event that came back without styles gets the ones its title or caption names, else its account's usual
        one (styles_in_text, _usual_styles): the dance filters would miss it otherwise. Free, no request. One of
        `several` events in a post looks at its own title first, and takes the caption's styles only when they're
        all one family (all salsa): a caption naming salsa and bachata doesn't say which event is which. Guessed
        styles carry GUESSED_STYLES_DOUBT, so a reading's own styles replace them later (merging.merge_into)."""
        if event.styles:
            return event
        caption = styles_in_text(post.get("caption"))
        if several:
            own = styles_in_text(event.title)
            styles = own or (caption if len({style_family(style) for style in caption}) == 1 else [])
        else:
            styles = styles_in_text(f"{event.title} {post.get('caption') or ''}")
        styles = styles or self._usual_styles(account)
        if not styles:
            return event
        return event.model_copy(update={"styles": styles, "doubts": [*event.doubts, GUESSED_STYLES_DOUBT]})

    def _usual_styles(self, account: str) -> list[str]:
        """The styles nearly all of an account's stored events share (at least 3 events, 80% of them): a bachata
        school's bachata. Empty when the account is varied or new. Only styles a model read count, not guessed ones."""
        events = [
            event
            for event in self.events
            if event.account == account and event.styles and GUESSED_STYLES_DOUBT not in event.doubts
        ]
        if len(events) < 3:
            return []
        counts: dict[str, int] = {}
        for event in events:
            for style in event.styles:
                counts[style] = counts.get(style, 0) + 1
        return [style for style, count in counts.items() if count >= 0.8 * len(events)]

    def _is_bar(self, account: str) -> bool:
        return self.options.get(account, AccountOptions()).bar

    def _by_hand(self, post_id: str) -> bool:
        """This read, or the post's first one, was asked for by hand: read as it is (no account rules or filter)."""
        record = self.processed.get(post_id)
        return self.by_hand or bool(record and record.by_hand)

    def _rules(self, account: str, post_id: str) -> str:
        """The prompts' extra rules for this account (a bar, a style focus), from accounts.txt; "" for a post added by
        hand: whoever adds it wants it read as it is."""
        options = self.options.get(account, AccountOptions())
        return "" if self._by_hand(post_id) else account_rules(options.bar, options.focus)

    def _hidden_match(self, account: str, candidate: ExtractedEvent, post_id: str) -> HiddenEvent | None:
        return next(
            (item for item in self.hidden.values() if matches_hidden(item.event, account, candidate, post_id)), None
        )

    def _announced_hidden(self, post_id: str) -> bool:
        """Whether an event hidden by hand came from this post or story: adding it by hand reads it again (even
        unchanged, even when its other events are still published), so the hidden event can come back."""
        return any(media.post_id == post_id for item in self.hidden.values() for media in item.event.media)

    # ---------- one post, one identity: the API's id, or public-<id> when read from its public page ----------

    def _record_id(self, code: str, public_only: bool = False) -> str | None:
        """The id under which a post (by its link's code) was analyzed, if it was."""
        return next(
            (
                post_id
                for post_id, record in self.processed.items()
                if (not public_only or post_id.startswith(public_post.ID_PREFIX))
                and links.same_post(record.permalink, code)
            ),
            None,
        )

    def _one_identity(self, known_id: str, post: Post) -> Post:
        """The same post under two ids (read once through the API, once from its public page): keep one. The
        API's id wins, so the sweeps recognize it."""
        if known_id.startswith(public_post.ID_PREFIX) and not post["id"].startswith(public_post.ID_PREFIX):
            self._rename_post(known_id, post["id"])
            return post
        return cast(Post, {**post, "id": known_id})

    def _rename_post(self, old: str, new: str) -> None:
        """Move a post's record and its place in events to a new id (flyers and clips keep their file names)."""
        self.processed[new] = self.processed.pop(old)
        # Hidden events too, so adding the post by hand still recognizes what was hidden from it (_announced_hidden).
        for event in [*self.events, *(item.event for item in self.hidden.values())]:
            for media in event.media:
                if media.post_id == old:
                    media.post_id = new
        log.info("   %s is %s: the same post, now under the API's id", old, new)
        self._save()

    def _same_caption(self, post: Post) -> bool:
        """Whether the post's caption is the one analyzed: its fingerprint or, for a post read before from its
        public page (whose caption may be spaced differently), the caption stored with its events."""
        record = self.processed[post["id"]]
        if record.caption_hash == caption_hash(post):
            return True
        stored = next(
            (media.caption for event in self.events for media in event.media if media.post_id == post["id"]), None
        )
        return stored is not None and " ".join(stored.split()) == " ".join((post.get("caption") or "").split())

    # ---------- storing one analyzed post ----------

    def _store_analysis(
        self,
        account: str,
        post: Post,
        images: list[bytes],
        analysis: PostAnalysis,
        model: str,
        provisional: bool,
        count_as_new: bool = True,
    ) -> bool:
        """Store the post's events. False when it must be retried next run (a flyer couldn't be saved)."""
        # A bar's events are at the bar (a Bogotá venue): its captions name where guests and styles come from.
        checked = (
            analysis.events
            if self._is_bar(account)
            else [doubtful_city(e, post.get("caption")) for e in analysis.events]
        )
        several = len(checked) > 1
        cleaned = [self._safeguarded(account, post, normalize_event(event), several) for event in checked]
        light = provisional or config.LITE_ONLY  # read by a lighter model (Flash-Lite, the last resort)
        if several and light:
            cleaned = [_with_doubt(event, MULTI_DOUBT) for event in cleaned]
        publishable: list[ExtractedEvent] = []
        reasons: set[str] = set()  # why the others weren't published, for the post's record
        for event in cleaned if analysis.is_event_post else []:
            why = self._discard_reasons(account, post["id"], event)
            reasons.update(why)
            if not why:
                publishable.append(event)
        try:
            flyers = common.save_flyers(post["id"], publishable, images)  # through the module: tests replace it
        except OSError as error:
            return self._retry_later(account, f"could not save flyer: {error}")

        if count_as_new:
            self.stats.count(account, "posts_analyzed")
        self.stats.events_discarded += len(analysis.events) - len(publishable)
        if provisional:
            self.stats.provisional += 1
            log.info("     extracted by %s (provisional: Flash out of quota, upgraded on a later run)", model)
        self._record_processed(account, post, analysis.is_event_post, analysis.reason, model, provisional)
        # If this post was analyzed before, forget what it contributed and add it again below. Events that
        # only this post announced give their ids back, so a re-extraction keeps the events' URLs.
        reusable = [event for event in self.events if {media.post_id for media in event.media} == {post["id"]}]
        announced = {event.id for event in self.events if any(media.post_id == post["id"] for media in event.media)}
        self.events = detach_post(self.events, post["id"])
        cancelled = not publishable and bool(announced) and _says_cancelled(post, analysis)

        if not publishable:
            log.info("     skipped: %s", analysis.reason)
        added = [
            self._add_event(account, post, candidate, media_for(post, flyer), reusable, count=count_as_new, light=light)
            for candidate, flyer in zip(publishable, flyers, strict=True)
        ]
        results = [result for result in added if result]
        if results:
            merged_only = all(merged for _, merged in results)
            self._set_outcome(post, "merged" if merged_only else "event", [event_id for event_id, _ in results])
        elif added:  # every event it announces was hidden by hand
            self._set_outcome(post, "hidden", detail="oculto a mano")
        elif cancelled:  # it announced events, and now says they're cancelled ("CANCELADO")
            self._take_down_cancelled(account, announced)
            self._set_outcome(post, "discarded", detail="cancelado")
        elif analysis.is_event_post and analysis.events:
            self._set_outcome(post, "discarded", detail=", ".join(sorted(reasons)))
        else:
            self._set_outcome(post, "not_event")
        self._save()
        return True

    def _take_down_cancelled(self, account: str, event_ids: set[str]) -> None:
        """A post that announced these events now says they're cancelled or postponed (its caption edited to
        "CANCELADO"); those only it announced are gone already (detach_post). Of the others, still announced by
        other posts, the events of this post's own account (the one that announced them first: events are stored
        under it) leave the site, and the other posts' records lose them. Another account's event stays, with low
        confidence and a doubt, so the health report lists it for review: a venue or collaborator dropping out
        doesn't cancel the organizer's event."""
        for event in [event for event in self.events if event.id in event_ids]:
            if event.account == account:
                self.events.remove(event)
                for record in self.processed.values():
                    if event.id not in record.event_ids:
                        continue
                    record.event_ids = [other for other in record.event_ids if other != event.id]
                    if not record.event_ids:  # nothing left to upgrade or show
                        record.outcome, record.detail, record.provisional = "discarded", "cancelado", False
                log.info("     cancelled, taken off the site: %s %s", _days(event), event.title)
            else:
                doubt = f"@{account} lo anunció cancelado o aplazado: revisar"
                flagged = event.model_copy(update={"confidence": "low", "doubts": [*event.doubts, doubt]})
                self.events[self.events.index(event)] = flagged
                log.info("     @%s says it's cancelled, flagged for review: %s %s", account, _days(event), event.title)

    def _discard_reasons(self, account: str, post_id: str, event: ExtractedEvent) -> list[str]:
        """Why an extracted event isn't published (empty: it is), in Spanish: unpublishable, or "ya pasó" when its
        last day is before today in Bogotá and it isn't an event already stored (a new account's first sweep reads
        posts a month old; an event already on the site still takes its later posts and re-reads)."""
        reasons = unpublishable(event)
        if "fuera de Bogotá" in reasons:
            log.info("     not in Bogotá (Gemini), left out: %s %s", _days(event), event.title)
        ended = bool(event.date) and has_ended(event, config.now_bogota().date())
        if ended and not already_stored(self.events, account, event, post_id):
            log.info("     already over, left out: %s %s", _days(event), event.title)
            reasons.append("ya pasó")
        return reasons

    def _retry_later(self, account: str, reason: str) -> bool:
        log.warning("     left for the next run: %s", reason)
        self.stats.count(account, "errors")
        return False

    def _known_events(self, account: str, published: datetime) -> list[StoredEvent]:
        """Events of this account that a new post could be announcing again (not already over)."""
        since = (config.bogota_date(published) - timedelta(days=1)).isoformat()
        return [event for event in self.events if event.account == account and (event.last_day or "") >= since]

    def _add_event(
        self,
        account: str,
        post: Post,
        candidate: ExtractedEvent,
        media: EventMedia,
        reusable: list[StoredEvent],
        count: bool = True,
        light: bool = False,
    ) -> tuple[str, bool] | None:
        """Merge into the same event from another post, or store it as a new event: (its id, merged?). None when
        it's an event hidden by hand (hide_event): left off the site, unless the post is added by hand.

        `count=False` for re-extractions (upgrades), which replace events instead of adding new ones. A reading by
        Flash (not `light`) merged into an event settles a lighter model's several-events doubt (MULTI_DOUBT).
        """
        hidden = self._hidden_match(account, candidate, post["id"])
        if hidden and not self.by_hand:
            log.info("     hidden by hand, left off the site: %s %s", _days(hidden.event), hidden.event.title)
            return None
        if hidden:  # added by hand: published again (with its old id, when it's stored as new)
            del self.hidden[hidden.event.id]
            log.info("     hidden by hand before, published again (added by hand): %s", hidden.event.title)
        if refused := refused_link(self.events, account, candidate, post["id"]):
            log.info("     Gemini linked it to %s, which isn't on its day: not merged", refused.id)
            doubt = f"posible cambio de fecha: Gemini lo une a {refused.id}"
            candidate = candidate.model_copy(update={"doubts": [*candidate.doubts, doubt]})
        existing = find_existing(self.events, account, candidate, post["id"])
        if existing:
            merged = merge_into(existing, candidate, media)
            if not light and MULTI_DOUBT in merged.doubts:
                merged = merged.model_copy(update={"doubts": [d for d in merged.doubts if d != MULTI_DOUBT]})
            self.events[self.events.index(existing)] = merged
            if count:
                self.stats.count(account, "events_merged")
            log.info("     same event as an earlier post, merged: %s %s", _days(existing), existing.title)
            return existing.id, True
        event_id = hidden.event.id if hidden else self._event_id(candidate, reusable)
        event = StoredEvent(
            **_details(candidate), id=event_id, account=account, media=[media], bar=self._is_bar(account)
        )
        self.events.append(event)
        if count:
            self.stats.count(account, "events_new")
        log.info("     event: %s %s | %s [%s]", _days(event), event.start_time or "", event.title, event.event_type)
        return event.id, False

    def _event_id(self, candidate: ExtractedEvent, reusable: list[StoredEvent]) -> str:
        """The id of the event this post announced before (same date first), else a new readable one."""
        previous = next((event for event in reusable if event.date == candidate.date), None) or next(
            iter(reusable), None
        )
        taken = {event.id for event in self.events} | set(self.hidden)  # a hidden event keeps its id to itself
        if previous:
            reusable.remove(previous)
            return previous.id
        assert candidate.date, "only events with a date are stored (unpublishable)"
        return new_event_id(candidate.title, candidate.date, taken)

    def _record_processed(
        self, account: str, post: Post, is_event_post: bool, reason: str, model: str, provisional: bool
    ) -> None:
        if state := self.accounts.get(account):
            state.unreadable.pop(post["id"], None)  # read at last (or given up): no run to count any more
        self.processed[post["id"]] = ProcessedPost(
            by_hand=self._by_hand(post["id"]),
            account=account,
            permalink=post["permalink"],
            processed_at=config.now_bogota().isoformat(timespec="seconds"),
            is_event_post=is_event_post,
            reason=reason,
            model=model,
            provisional=provisional,
            caption_hash=caption_hash(post),
        )

    def _record_not_event(self, account: str, post: Post, reason: str, model: str) -> None:
        """A post that announces no event (the triage, or the account's style filter), recorded and saved."""
        self.stats.count(account, "posts_analyzed")
        self.stats.posts_triaged_out += 1
        self._record_processed(account, post, False, reason, model, provisional=False)
        self._set_outcome(post, "not_event")
        self._save()
        log.info("     not an event: %s", reason)

    def _set_outcome(
        self, post: Post, outcome: PostOutcome, event_ids: list[str] | None = None, detail: str | None = None
    ) -> None:
        record = self.processed[post["id"]]
        record.outcome, record.event_ids, record.detail = outcome, event_ids or [], detail

    def _save(self) -> None:
        """Save after every post so progress survives an interrupted run."""
        storage.save_events(self.events)
        storage.save_processed_posts(self.processed)
        storage.save_hidden_events(self.hidden)
