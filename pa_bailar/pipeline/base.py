"""SweepBase: what the sweep and the admin tools share. The state (events, analyzed posts, events hidden by hand,
accounts), storing one analyzed post (its events new or merged, its record, a cancelled post's events taken down),
and keeping one identity per post (the API's id, or public-<id> when it was read from its public page)."""

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, NamedTuple, cast

from .. import config, links, public_post, storage
from ..account_options import AccountOptions
from ..changes import changed_fields, fields_label
from ..extraction import EventExtractor
from ..ids import new_event_id
from ..instagram import InstagramClient, Post
from ..instagram_usage import ReadCosts
from ..merging import (
    already_stored,
    detach_post,
    find_existing,
    matches_hidden,
    merge_duplicates,
    merge_into,
    refused_link,
)
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
    party_at_a_bar,
    style_family,
    styles_in_text,
)
from ..prompts import account_rules
from ..text import PRICE_WORDS, fold
from . import common
from .common import Extractor, Flyer, PostSource, RunStats, caption_hash, has_ended, media_for, unpublishable

log = logging.getLogger(__name__)


def _with_doubt(event: ExtractedEvent, doubt: str) -> ExtractedEvent:
    return event if doubt in event.doubts else event.model_copy(update={"doubts": [*event.doubts, doubt]})


# A caption or Gemini's reason saying the event is off (folded text: lowercase, no accents), in the pieces below. Only
# words that say it of the event: a reminder Flash finds no event in takes the account's events it announced off the
# site, so a word that also means something else loses an event for good. Not "no habrá" ("no habrá venta de boletas
# en taquilla"), "cancelación" ("política de cancelación") nor "nueva fecha" ("abrimos nueva fecha en noviembre"): the
# audit of 7 Oct 2026, after #151 added them. The verbs' forms besides the participles joined in the bug-squash pass of
# 8 Oct 2026: without them, "se suspende el social de hoy" left a cancelled event on the site while another post
# announced it.
#
# The participles ("cancelado", "aplazadas"…) are also how a doubt says an event may be off (health.PLACE_DOUBT): one
# list for both.
CANCELLED_PARTICIPLES = r"cancelad[oa]s?|aplazad[oa]s?|pospuest[oa]s?|suspendid[oa]s?|reprogramad[oa]s?|postergad[oa]s?"
_IN_ENGLISH = r"cancell?ed|postponed"
# "Se cancela", "se cancelan", "se canceló", "se cancelaron", unless it means paid (_PAID).
_SE_CANCELA = r"se cancel(?:an?|o|aron)"
# The other verbs with "se", said of the event: "se aplaza", "se reprogramó", "se pospone", "se pospuso", "se suspende"…
_SE_CALLED_OFF = (
    r"se (?:aplaz|reprogram|posterg)(?:an?|o|aron)|se pospon(?:e|en)|se pospus(?:o|ieron)|se suspend(?:e|en|io|ieron)"
)
# The organizers calling it off: "cancelamos", "pospusimos"…
_WE_CALL_IT_OFF = r"cancelamos|aplazamos|posponemos|pospusimos|suspendemos|suspendimos|reprogramamos|postergamos"
_WONT_TAKE_PLACE = r"no se realizara|no se llevara a cabo"
# "Tuvimos que cancelar", "hemos decidido aplazar", "nos vemos obligados a posponer"…
_WE_HAD_TO = (
    r"(?:tuvimos|tenemos|debemos|decidimos|hemos decidido|nos toca|nos toco|nos vemos obligados a"
    r"|nos vimos obligados a)(?: que)? (?:cancelar|aplazar|posponer|suspender|reprogramar|postergar)"
)
_CANCELLED = re.compile(
    rf"\b({CANCELLED_PARTICIPLES}|{_IN_ENGLISH}|{_SE_CANCELA}|{_SE_CALLED_OFF}|{_WE_CALL_IT_OFF}|{_WONT_TAKE_PLACE}"
    rf"|{_WE_HAD_TO})\b"
)

# In Colombia "cancelar" is also "to pay": "se cancela" is paid after a price in its sentence ("la entrada se cancela
# en la puerta", "Cover: 15k se cancela en la entrada"; a price's word not past a colon: "Entrada: se cancela el social"
# says it's off), before a price ("se cancelan 20 mil al ingresar", "se cancela el valor de la entrada"), before when or
# how it's paid ("se cancela en efectivo", "Inversión: $50.000. Se cancela el día del taller"), or already ("ya se
# canceló"); never "se cancela por lluvia" nor "el día de hoy". Read line by line: a price on one line says nothing
# about the next.
#
# A price's word: text.PRICE_WORDS (shared with the rule checks' price line), and how a payment is named.
_PRICE_WORD = (
    rf"\b(?:{'|'.join(PRICE_WORDS)}|entrada|inscripcion|matricula|cuota|pago|mensualidad|reserva|saldo|abono)s?\b"
)
# An amount of money.
_AMOUNT = (
    r"(?:\$[ \t]*\d"  # "$50.000", "$ 50"
    r"|\b\d+(?:\.\d{3})*(?:[ \t]*(?:k|mil|cop|pesos)\b|[ \t]*%)"  # "50 mil", "15k", "120.000 pesos", "50%"
    r"|\b\d{1,3}(?:\.\d{3})+\b)"  # "50.000": a dot between digits groups thousands
)
# Up to 30 characters of the same sentence, past no colon. The dot of "$50.000" ends no sentence: before the bug-squash
# pass of 8 Oct 2026 the amount and the words after it went unread, and a reminder Flash found no event in took its
# event down.
_IN_ITS_SENTENCE = r"(?:[^.!?:]|(?<=\d)\.(?=\d)){0,30}?"
# When or how it's paid, right after it: "en efectivo", "en dos cuotas", "por Nequi", "al llegar", "antes del taller",
# "el mismo día", "el día del taller" (not "el día de hoy")…
_WHEN_OR_HOW_PAID = (
    r"(?:en (?:efectivo|la puerta|puerta|taquilla|la entrada|caja|el lugar|(?:dos|tres|\d+) cuotas)\b"
    r"|con (?:tarjeta|efectivo|nequi|daviplata|transferencia)\b|al (?:ingresar|llegar|entrar|ingreso|momento)\b"
    r"|antes del?\b|el mismo dia\b|el dia del?\b(?! (?:hoy|manana)\b)|directamente\b|por adelantado\b"
    r"|con anticipacion\b|por (?:nequi|daviplata|transferencia|pse|tarjeta|bancolombia)\b)"
)
# A price right after it, past an article at most: "se cancelan 20 mil", "se cancela a $20.000", "se cancela el 50%",
# "se cancela el valor de la entrada" (the code-quality pass of 8 Oct 2026: each took a reminder's event down); not "se
# cancela el social" nor "el 15 de octubre".
_THEN_A_PRICE = rf"(?: (?:el|la|los|las|un|una|a|al|solo|solamente|unicamente))* (?:{_PRICE_WORD}|{_AMOUNT})"
_PAID = re.compile(
    rf"(?:{_PRICE_WORD}|{_AMOUNT}){_IN_ITS_SENTENCE}\b{_SE_CANCELA}\b"
    r"|\bya se cancel(?:o|aron)\b"
    rf"|\b{_SE_CANCELA}{_THEN_A_PRICE}"
    rf"|\b{_SE_CANCELA} {_WHEN_OR_HOW_PAID}"
)

# Words that say it isn't off: "el social NO se cancela por la lluvia", "no está cancelado", "no lo aplazamos", "no se
# aplaza ni se cancela", "ni se cancela ni se aplaza".
_OFF_VERB = (
    r"(?:se |esta |estan |fue |fueron |ha sido |han sido |sera |seran |lo |la |los |las )?"
    r"(?:cancel|aplaz|suspend|pospon|pospu|reprogram|posterg)\w*"
)
_DENIED = re.compile(rf"\b(?:no|ni) {_OFF_VERB}(?: ni {_OFF_VERB})*")
# Words that only say it might be off: a condition ("si no se completa el cupo, el taller se aplaza", "se aplaza si
# llueve", "en caso de lluvia se aplaza", "si el evento es cancelado se devuelve el dinero"; not "Sí, …" nor "si bien")
# or a question ("¿se cancela por la lluvia?"). Reminders repeat them, and Flash finding no event in one took its event
# down for good (the bug-squash pass of 8 Oct 2026). A condition after the word governs it within its clause only: "se
# cancela por lluvia, si ya pagaste te devolvemos el dinero" says it's off.
_CONDITION = re.compile(r"\bsi\b(?!,| bien\b)|\ben caso de\b")
# A sentence ends after "!", "?" or a dot (not the dot of "$50.000"), and before a question's "¿": a question ignored
# took the sentence before it along ("Evento cancelado ¿Quieres tu reembolso? Escríbenos": the code-quality pass of 8
# Oct 2026).
_SENTENCE_END = re.compile(r"(?<=[!?])|(?<=\.)(?!\d)|(?=¿)")
_CLAUSE_END = re.compile(r"[,;]")


def _states_it(sentence: str) -> bool:
    """Whether a sentence says the event is off: a cancellation word, not in a question nor under a condition (before
    it in the sentence, or after it in its clause)."""
    if "?" in sentence or "¿" in sentence:
        return False
    return any(
        not _CONDITION.search(sentence[: found.start()])
        and not _CONDITION.search(_CLAUSE_END.split(sentence[found.end() :], maxsplit=1)[0])
        for found in _CANCELLED.finditer(sentence)
    )


def _sentences(line: str) -> list[str]:
    """A line's sentences, folded, with what doesn't say the event is off blanked out: "se cancela" meaning it's paid
    (_PAID), then the denials (_DENIED)."""
    return _SENTENCE_END.split(_DENIED.sub(" ", _PAID.sub(" ", fold(line))))


def _says_cancelled(post: Post, analysis: PostAnalysis) -> bool:
    """Whether the post's caption, or Gemini's reason for finding no event in it, says it's cancelled or postponed: a
    sentence that states it (not "se cancela" meaning it's paid, nor a condition, a denial or a question)."""
    lines = [*(post.get("caption") or "").splitlines(), analysis.reason]
    return any(_states_it(sentence) for line in lines for sentence in _sentences(line))


def _days(event: EventDetails) -> str:
    """An event's day for the log: its date, or first → last day (a workshop series: and how many sessions)."""
    sessions = f" ({len(event.sessions)} sessions)" if event.sessions else ""
    return f"{event.date} → {event.end_date}{sessions}" if event.end_date else str(event.date)


def _details(event: ExtractedEvent) -> dict[str, Any]:
    return event.model_dump(include=set(EventDetails.model_fields))


# The doubt another account's "cancelled" post leaves on an event it doesn't own (SweepBase._take_down_cancelled):
# "@<account> lo anunció cancelado o aplazado: revisar". Kept through re-reads (SweepBase._keep_review_flags).
CANCEL_FLAG = "lo anunció cancelado o aplazado: revisar"


class _Fit(NamedTuple):
    """How well an event a post announced before fits a new reading of the post. Compared as a tuple: the same date
    weighs most, then the same title, start time and type, in that order."""

    same_date: bool
    same_title: bool
    same_time: bool
    same_type: bool


def _fit(event: StoredEvent, candidate: ExtractedEvent) -> _Fit:
    return _Fit(
        same_date=event.date == candidate.date,
        same_title=fold(event.title) == fold(candidate.title),
        same_time=bool(event.start_time) and event.start_time == candidate.start_time,
        same_type=event.event_type == candidate.event_type,
    )


class _Before(NamedTuple):
    """What there was before a post was stored, for the run's changes (SweepBase._note_changes): the events it
    announced, as they were, and the ids stored and hidden by hand."""

    events: dict[str, StoredEvent]
    stored_ids: set[str]
    hidden_ids: set[str]


def _best_fit(candidate: ExtractedEvent, events: list[StoredEvent]) -> _Fit:
    """How well the closest of these events fits the reading."""
    return max((_fit(event, candidate) for event in events), default=_Fit(False, False, False, False))


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
        self.stats = RunStats()  # before the duplicates are merged: the run notes them (changes.py)
        # An event hidden by hand stays off the site, even if the data PR of the run that hid it wasn't merged.
        stored = storage.load_events()
        self.options = storage.read_account_options()
        # An event is a bar's when its account is one now (accounts.txt): marking or unmarking an account updates
        # its stored events too.
        self.events = [self._as_bar_says(event) for event in stored if event.id not in self.hidden]
        self.processed = storage.load_processed_posts()
        self._merge_duplicates()
        if self.events != stored:
            storage.save_events(self.events)
        self.by_hand = False  # adding a post or story by hand: it may publish again what was hidden
        self.accounts = storage.load_account_state()
        self.started = time.monotonic()
        self.time_up_logged = False
        self.rate_limited = False  # Meta is throttling the app: the remaining accounts wait for the next run
        self.read_costs = ReadCosts()  # each account read's cost, and the forecast that stops the sweep

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

    def _as_bar_says(self, event: StoredEvent) -> StoredEvent:
        """A stored event as its account's options say now: `bar` follows accounts.txt, and a bar's social is a
        party unless its title or posts announce a social (stored before the type existed: normalize.party_at_a_bar)."""
        bar = self._is_bar(event.account)
        updates: dict[str, object] = {} if event.bar == bar else {"bar": bar}
        if bar:
            text = " ".join([event.title, *(media.caption or "" for media in event.media)])
            kind = party_at_a_bar(event.event_type, text)
            if kind != event.event_type:
                updates["event_type"] = kind
        return event.model_copy(update=updates) if updates else event

    def _typed(self, account: str, post: Post, event: ExtractedEvent) -> ExtractedEvent:
        """A bar's night read as a social is a party unless it announces one (normalize.party_at_a_bar)."""
        if not self._is_bar(account):
            return event
        kind = party_at_a_bar(event.event_type, f"{event.title} {post.get('caption') or ''}")
        return event if kind == event.event_type else event.model_copy(update={"event_type": kind})

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

    def _publishable(
        self, account: str, post: Post, analysis: PostAnalysis, light: bool
    ) -> tuple[list[ExtractedEvent], set[str]]:
        """The reading's events through the safeguards (normalize, the city, styles and type; a doubt on each of
        several read by a lighter model, `light`): those that can be published, and why the others can't (for the
        post's record)."""
        # A bar's events are at the bar (a Bogotá venue): its captions name where guests and styles come from.
        checked = (
            analysis.events
            if self._is_bar(account)
            else [doubtful_city(e, post.get("caption")) for e in analysis.events]
        )
        several = len(checked) > 1
        cleaned = [
            self._typed(account, post, self._safeguarded(account, post, normalize_event(event), several))
            for event in checked
        ]
        if several and light:
            cleaned = [_with_doubt(event, MULTI_DOUBT) for event in cleaned]
        publishable: list[ExtractedEvent] = []
        reasons: set[str] = set()
        for event in cleaned if analysis.is_event_post else []:
            why = self._discard_reasons(account, post["id"], event)
            reasons.update(why)
            if not why:
                publishable.append(event)
        return publishable, reasons

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
        light = provisional or config.LITE_ONLY  # read by a lighter model (Flash-Lite, the last resort)
        publishable, reasons = self._publishable(account, post, analysis, light)
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
        # If this post was analyzed before, forget what it contributed and add it again below. Events that
        # only this post announced give their ids back, so a re-extraction keeps the events' URLs.
        reusable = [event for event in self.events if {media.post_id for media in event.media} == {post["id"]}]
        announced = {event.id for event in self.events if any(media.post_id == post["id"] for media in event.media)}
        # As they were, for the run's changes (_note_changes).
        before = {event.id: event for event in self.events if event.id in announced}
        stored_ids, hidden_ids = {event.id for event in self.events}, set(self.hidden)
        self.events = detach_post(self.events, post["id"])
        cancelled = not publishable and bool(announced) and _says_cancelled(post, analysis)

        if not publishable:
            log.info("     skipped: %s", analysis.reason)
        readings = list(zip(publishable, flyers, strict=True))
        rebuilt = list(reusable)  # as they were: _add_readings takes from `reusable` as it gives their ids back
        added = self._add_readings(
            account, post, readings, reusable, count=count_as_new, light=light, announced=announced
        )
        self._keep_review_flags(rebuilt)
        results = [result for result in added if result]
        outcome: tuple[PostOutcome, list[str], str | None]
        if results:
            merged_only = all(merged for _, merged in results)
            outcome = ("merged" if merged_only else "event", [event_id for event_id, _ in results], None)
        elif added:  # every event it announces was hidden by hand
            outcome = ("hidden", [], "oculto a mano")
        elif cancelled:  # it announced events, and now says they're cancelled ("CANCELADO")
            self._take_down_cancelled(account, announced)
            outcome = ("discarded", [], "cancelado")
        elif analysis.is_event_post and analysis.events:
            outcome = ("discarded", [], ", ".join(sorted(reasons)))
        else:
            outcome = ("not_event", [], None)
        # The record last: if anything above fails, the post isn't recorded as analyzed (with its events detached and
        # not added again), so it's read again next run.
        self._record_processed(account, post, analysis.is_event_post, analysis.reason, model, provisional)
        self._set_outcome(post, *outcome)
        self._save()
        self._note_changes(
            account,
            post,
            results,
            _Before(before, stored_ids, hidden_ids),
            provisional=provisional and post["media_type"] != "STORY",  # no sweep reads a story again
            upgrade=not count_as_new,
            cancelled=cancelled,
        )
        return True

    def _note_changes(
        self,
        account: str,
        post: Post,
        results: list[tuple[str, bool]],
        before: _Before,
        provisional: bool,
        upgrade: bool,
        cancelled: bool,
    ) -> None:
        """What storing this post did to each event, for the run's history (changes.py): new or provisional, merged
        into an event already on the site, published again after being hidden, read again (corrected or updated, or
        nothing changed), or gone (cancelled, or a new reading no longer announces it)."""
        events = {event.id: event for event in self.events}
        why = "Flash" if upgrade else "releído a mano" if self.by_hand else "publicación editada"
        for event_id, merged in results:
            event = events[event_id]
            if event_id in before.events:
                fields = changed_fields(before.events[event_id], event)
                if not fields:
                    self.stats.note("reread", event, "Flash confirmó la lectura" if upgrade else f"{why}, sin cambios")
                elif upgrade:
                    self.stats.note("corrected", event, f"Flash {fields_label(fields)}")
                else:
                    self.stats.note("updated", event, f"{why}: {fields_label(fields)}")
            elif event_id in before.hidden_ids:
                self.stats.note("restored", event, "oculto antes, publicado de nuevo a mano")
            elif merged and event_id in before.stored_ids:
                source = "una historia" if post["media_type"] == "STORY" else "otra publicación"
                self.stats.note("merged", event, source if account == event.account else f"{source} de @{account}")
            elif provisional:
                self.stats.note("provisional", event, "leído por un modelo más liviano: Flash lo relee después")
            else:
                self.stats.note("new", event)
        for event_id, event in before.events.items():
            if event_id in events:
                continue  # still on the site: other posts announce it (or it was flagged: _take_down_cancelled)
            if cancelled:
                self.stats.note("cancelled", event, "la publicación dice que se canceló o se aplazó")
            else:
                gone = "Flash no lo encontró al releer" if upgrade else f"{why}: ya no lo anuncia"
                self.stats.note("dropped", event, gone)

    def _keep_review_flags(self, before: list[StoredEvent]) -> None:
        """An event rebuilt from a new reading of its only post (`before`: as it was) keeps another account's
        cancellation flag (_take_down_cancelled): low confidence and its doubt. A re-read (Flash's upgrade, an edited
        caption) doesn't make the cancellation less worth a look; rebuilt from the reading alone, the flag was lost
        when Flash re-read the event's remaining post in the same run (the bug-squash pass of 9 Oct 2026)."""
        flags = {event.id: [doubt for doubt in event.doubts if doubt.endswith(CANCEL_FLAG)] for event in before}
        for index, event in enumerate(self.events):
            kept = [doubt for doubt in flags.get(event.id, []) if doubt not in event.doubts]
            if kept:
                self.events[index] = event.model_copy(update={"confidence": "low", "doubts": [*event.doubts, *kept]})

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
                doubt = f"@{account} {CANCEL_FLAG}"
                flagged = event.model_copy(update={"confidence": "low", "doubts": [*event.doubts, doubt]})
                self.events[self.events.index(event)] = flagged
                self.stats.note("flagged", flagged, doubt)
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

    def _add_readings(
        self,
        account: str,
        post: Post,
        readings: list[tuple[ExtractedEvent, Flyer]],
        reusable: list[StoredEvent],
        count: bool,
        light: bool,
        announced: set[str],
    ) -> list[tuple[str, bool] | None]:
        """Each of the post's readings (an event and its flyer) merged or stored (_add_event), the results in the post's
        order. The readings closest to an event this post announced before go first, so each takes that event's id
        (_event_id): a new event listed before it took its URL (the bug-squash pass of 8 Oct 2026)."""
        closest_first = sorted(range(len(readings)), key=lambda i: _best_fit(readings[i][0], reusable), reverse=True)
        added: list[tuple[str, bool] | None] = [None] * len(readings)
        for i in closest_first:
            candidate, flyer = readings[i]
            added[i] = self._add_event(
                account,
                post,
                candidate,
                media_for(post, flyer),
                reusable,
                count=count,
                light=light,
                announced=announced,
            )
        return added

    def _add_event(
        self,
        account: str,
        post: Post,
        candidate: ExtractedEvent,
        media: EventMedia,
        reusable: list[StoredEvent],
        count: bool = True,
        light: bool = False,
        announced: frozenset[str] | set[str] = frozenset(),
    ) -> tuple[str, bool] | None:
        """Merge into the same event from another post, or store it as a new event: (its id, merged?). None when
        it's an event hidden by hand (hide_event): left off the site, unless the post is added by hand.

        `count=False` for re-extractions (upgrades), which replace events instead of adding new ones. A reading by
        Flash (not `light`) merged into an event settles a lighter model's several-events doubt (MULTI_DOUBT), and
        corrects an event this post announced before (`announced`) that only lighter models read (merge_into).
        """
        hidden = self._hidden_match(account, candidate, post["id"])
        if hidden and not self.by_hand:
            log.info("     hidden by hand, left off the site: %s %s", _days(hidden.event), hidden.event.title)
            self.stats.note("kept_hidden", hidden.event, "oculto a mano: no se volvió a publicar")
            return None
        if hidden:  # added by hand: published again (with its old id, when it's stored as new)
            del self.hidden[hidden.event.id]
            log.info("     hidden by hand before, published again (added by hand): %s", hidden.event.title)
        if refused := refused_link(self.events, account, candidate, post["id"]):
            log.info("     Gemini linked it to %s, which isn't on its day: not merged", refused.id)
            doubt = f"posible cambio de fecha: Gemini lo une a {refused.id}"
            candidate = candidate.model_copy(update={"doubts": [*candidate.doubts, doubt]})
        existing = find_existing(self.events, account, candidate, post["id"], announced)
        if existing:
            correcting = not light and existing.id in announced and self._only_lighter_reads(existing)
            merged = merge_into(existing, candidate, media, correcting=correcting)
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

    def _only_lighter_reads(self, event: StoredEvent) -> bool:
        """Whether every post or story the event stands on was read by a lighter model (provisional)."""
        records = [self.processed.get(media.post_id) for media in event.media]
        return all(record is not None and record.provisional for record in records)

    def _event_id(self, candidate: ExtractedEvent, reusable: list[StoredEvent]) -> str:
        """The id of the event this post announced before that fits it best (_fit), else a new readable one. A re-read
        may list a post's events in another order (Flash after Flash-Lite): the first one on the date took the id of
        the post's first event that day, so a workshop and a social swapped URLs, and visitors' saved events (the
        bug-squash pass of 8 Oct 2026)."""
        previous = max(reusable, key=lambda event: _fit(event, candidate), default=None)  # the first of the best
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

    def _merge_duplicates(self) -> None:
        """Stored events the rules now say are one (merging.merge_duplicates), merged on load; the posts that
        became the dropped one now point at the one kept, and the processed records are saved with them."""
        titles = {event.id: event.title for event in self.events}
        self.events, pairs = merge_duplicates(self.events)
        if not pairs:
            return
        kept_events = {event.id: event for event in self.events}
        renamed = dict((dropped, kept) for kept, dropped in pairs)
        for record in self.processed.values():
            if any(event_id in renamed for event_id in record.event_ids):
                record.event_ids = list(dict.fromkeys(renamed.get(i, i) for i in record.event_ids))
        storage.save_processed_posts(self.processed)
        for kept, dropped in pairs:
            log.info("Duplicate events merged: %s into %s", dropped, kept)
            if kept in kept_events:  # a dropped one may have been kept before (three of one event)
                self.stats.note("duplicate", kept_events[kept], f"unido con «{titles[dropped]}», el mismo evento")

    def _save(self) -> None:
        """Save after every post so progress survives an interrupted run."""
        storage.save_events(self.events)
        storage.save_processed_posts(self.processed)
        storage.save_hidden_events(self.hidden)
