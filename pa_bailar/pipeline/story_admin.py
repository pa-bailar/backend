"""Adding a story by hand from its screenshots (`sweep --story`, the admin tools' "Agregar historia"). What needs
neither Gemini nor Instagram (dates, crops, ids, the account's name) is in stories.py."""

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import cast

from .. import config, links, storage, stories
from ..gemini import GeminiKeyError, QuotaExhaustedError, RejectedRequestError
from ..instagram import InstagramError, Post, api_timestamp
from ..models import AccountState, ExtractedEvent, PostAnalysis, Session, StoredEvent, StoryAnalysis, StoryEvent
from ..text import WEEKDAYS
from .base import SweepBase
from .common import RETRYABLE_ERRORS, AddPostError, has_ended, no_quota_message

log = logging.getLogger(__name__)


@dataclass
class AddedStory:
    """What add_story did, for the admin tools' answer (the "receipt": what was read and where it came from)."""

    story_id: str
    account: str
    account_source: str  # where the account came from, in Spanish
    account_checked: bool  # Instagram's API can read it (so it's swept)
    account_added: bool
    outcome: str | None  # ProcessedPost.outcome
    reason: str  # Gemini's
    model: str | None
    provisional: bool  # read by Flash-Lite (Flash out of quota): kept as it is
    events: list[StoredEvent]
    taken: datetime
    taken_source: str
    date_notes: dict[str, list[str]] = field(default_factory=dict)  # by event title: how its date was worked out
    mentions: list[str] = field(default_factory=list)
    location: str | None = None
    gemini_crop: bool = True  # the flyer is Gemini's box; False: the fixed crop
    past: list[str] = field(default_factory=list)  # events whose date had passed: not published
    unchanged: bool = False  # these same screenshots were published before: not read again
    duplicate_of: str | None = None  # another screenshot of a story published before (stories.same_story)

    @property
    def done(self) -> bool:
        """Its screenshots aren't needed any more (published, or already were): they can be deleted."""
        return self.unchanged or self.duplicate_of is not None or self.outcome in ("event", "merged")


def _story_event(
    item: StoryEvent, resolved: stories.ResolvedDate, location: str | None, image_index: int
) -> ExtractedEvent:
    """A story's event as the sweep stores events: its date (a workshop series: its sessions) worked out in code, the
    location sticker as the venue when none is written, and a weekday that doesn't match the date (or a date far
    ahead) as a doubt."""
    doubts = list(item.doubts)
    if resolved.weekday_mismatch or resolved.far_ahead:
        doubts += [note for note in resolved.notes if note.startswith(("dice ", "más de"))]
    return ExtractedEvent(
        title=item.title,
        event_type=item.event_type,
        is_recurring=item.is_recurring,  # a weekly night isn't: its next date is published
        styles=item.styles,
        organizer=item.organizer,
        venue=item.venue or location,
        address=item.address,
        area=item.area,
        date=resolved.start.isoformat() if resolved.start else None,
        end_date=resolved.end.isoformat() if resolved.end else None,
        sessions=[
            Session(date=day.isoformat(), start_time=session.start_time, end_time=session.end_time)
            for day, session in resolved.sessions
        ]
        or None,
        weekday=WEEKDAYS[resolved.start.weekday()] if resolved.start else item.weekday,
        start_time=item.start_time,
        end_time=item.end_time,
        prices=item.prices,
        artists=item.artists,
        activities=item.activities,
        contact=item.contact,
        confidence="low" if resolved.weekday_mismatch else item.confidence,
        doubts=doubts,
        image_index=image_index,
        same_as=item.same_as,
        in_bogota="yes",  # shared by hand by the admin, who saw where it is (the prompt still leaves out other cities)
    )


class StoryAdmin(SweepBase):
    def add_story(
        self, shots: list[stories.Screenshot], account: str | None = None, notes: str | None = None
    ) -> AddedStory:
        """Publish the events of a story from screenshots of it (`sweep --story`, the admin tools' "Agregar
        historia"): one Gemini request for all of them (up to stories.MAX_SCREENSHOTS), no triage.

        - The same screenshots again (a retried request) aren't read again; another screenshot of a story already
          published, within a day and a half, neither (perceptual hash), unless notes come with it.
        - The account: the one typed, else the author of a post the story reshares, else the name at the top of
          the story; checked with one Instagram call, or matched to a known account when it's cut off ("…").
          Mentions and a location sticker are hints, never the account. An account the API can read and isn't
          swept yet is added.
        - Dates are worked out from what's printed (stories.resolve_date), relative to when the screenshot was
          taken; an event whose date passed isn't published. A weekly night publishes its next date.
        - The flyer is a crop of the screenshot (Gemini's box, checked and padded, or a fixed crop): the
          screenshot itself is never published. The event's permalink is the account's profile."""
        if not shots:
            raise AddPostError("No llegó ninguna captura.")
        self.by_hand = True
        shots = shots[: stories.MAX_SCREENSHOTS]
        images = [shot.image for shot in shots]
        story_id = stories.story_id(images)
        now = config.now_bogota()
        taken, taken_source = min((stories.taken_at(shot, now) for shot in shots), key=lambda pair: pair[0])
        hashes = [stories.image_hash(image) for image in images]

        record = self.processed.get(story_id)
        if record and record.outcome in ("event", "merged"):
            log.info("   %s: the same screenshots, published before", story_id)
            return self._story_answer(story_id, taken, taken_source, unchanged=True)
        twin = None if notes else self._same_story(hashes, now)
        if twin:
            log.info("   %s: another screenshot of %s, published before", story_id, twin)
            return self._story_answer(twin, taken, taken_source, duplicate_of=twin)

        if not self.extractor.can_analyze():
            raise AddPostError(no_quota_message())
        known = self._known_events(account, taken) if account else []
        try:
            analysis, model, provisional = self.extractor.extract_story(images, taken, account, notes, known)
        except RejectedRequestError as error:
            raise AddPostError(f"Gemini no pudo leer las capturas ({error}).") from error
        except QuotaExhaustedError as error:
            raise AddPostError(no_quota_message()) from error
        except GeminiKeyError as error:
            raise AddPostError("La clave de Gemini no funciona (vencida o revocada): hay que cambiarla.") from error
        except RETRYABLE_ERRORS as error:
            raise AddPostError(f"Algo falló al leerlas ({error}). Inténtalo de nuevo en un rato.") from error

        owner, source, checked = self._story_account(account, analysis)
        today = now.date()
        crops = [stories.crop(image, self._content_box(analysis, index)) for index, image in enumerate(images)]
        best = max(range(len(crops)), key=lambda index: (crops[index].from_gemini, crops[index].area))
        extracted: list[ExtractedEvent] = []
        date_notes: dict[str, list[str]] = {}
        past: list[str] = []
        for item in analysis.events:
            resolved = stories.resolve_date(item, taken.date(), today)
            index = item.image_index
            image_index = index if index is not None and 0 <= index < len(crops) else best
            event = _story_event(item, resolved, analysis.location_sticker, image_index)
            if has_ended(event, today):
                past.append(item.title)
                continue
            extracted.append(event)
            date_notes[" ".join(item.title.split())] = resolved.notes

        age = stories.story_age(analysis.story_age)
        published = (taken - age) if age else taken
        post = cast(
            Post,
            {
                "id": story_id,
                "media_type": "STORY",
                "permalink": links.profile_link(owner),  # a story is gone after 24 hours
                "timestamp": api_timestamp(published),
            },
        )
        day = f"{published:%Y-%m-%d}"
        log.info("   %s STORY %s (@%s, %s screenshot(s), by hand)", day, story_id, owner, len(shots))
        result = PostAnalysis(is_event_post=analysis.is_event_post, reason=analysis.reason, events=extracted)
        if not self._store_analysis(owner, post, [item.image for item in crops], result, model, provisional):
            raise AddPostError("No se pudo guardar el flyer. Inténtalo de nuevo en un rato.")
        record = self.processed[story_id]
        record.provisional = False  # no later sweep sees a story: a Flash-Lite read stays as it is
        record.image_hashes = hashes
        if past and record.outcome == "not_event":
            record.outcome, record.detail = "discarded", "ya pasó"
        self._save()

        added = checked and storage.add_account(owner)
        if added:
            self.accounts.setdefault(owner, AccountState(first_seen=today.isoformat()))
            log.info("@%s added to accounts.txt", owner)
        self.stats.flyers_removed = storage.remove_unused_flyers(self.events)
        self.stats.gemini_requests = self.extractor.requests_this_run()
        storage.save_account_state(self.accounts)
        storage.save_meta(asdict(self.stats))
        answer = self._story_answer(story_id, taken, taken_source)
        answer.account_source, answer.account_checked, answer.account_added = source, checked, added
        answer.provisional, answer.date_notes, answer.past = provisional, date_notes, past
        answer.mentions = [name for raw in analysis.mentions_in_image if (name := stories.read_handle(raw)[0])]
        answer.location = analysis.location_sticker
        flyer_slides = {event.image_index for event in extracted}
        answer.gemini_crop = all(crops[index].from_gemini for index in flyer_slides if index is not None)
        return answer

    def _story_answer(
        self,
        story_id: str,
        taken: datetime,
        taken_source: str,
        unchanged: bool = False,
        duplicate_of: str | None = None,
    ) -> AddedStory:
        record = self.processed[story_id]
        events = [event for event in self.events if event.id in record.event_ids]
        return AddedStory(
            story_id=story_id,
            account=record.account,
            account_source="",
            account_checked=True,
            account_added=False,
            outcome=record.outcome,
            reason=record.reason,
            model=record.model,
            provisional=False,
            events=events,
            taken=taken,
            taken_source=taken_source,
            unchanged=unchanged,
            duplicate_of=duplicate_of,
        )

    def _same_story(self, hashes: list[str], now: datetime) -> str | None:
        """A published story these screenshots are of (another screenshot of it), shared recently."""
        since = now - timedelta(hours=stories.SAME_STORY_HOURS)
        return next(
            (
                story_id
                for story_id, record in self.processed.items()
                if story_id.startswith(stories.STORY_PREFIX)
                and record.outcome in ("event", "merged")
                and datetime.fromisoformat(record.processed_at) >= since
                and stories.same_story(hashes, record.image_hashes)
            ),
            None,
        )

    @staticmethod
    def _content_box(analysis: StoryAnalysis, index: int) -> list[int] | None:
        return next((image.content_box for image in analysis.images if image.index == index), None)

    def _can_read(self, account: str) -> bool:
        """Whether Instagram's API can read the account (one call)."""
        try:
            self.instagram.fetch_recent_posts(account, limit=1)
        except InstagramError as error:
            log.info("   the API can't read @%s (%s)", account, error)
            return False
        return True

    def _story_account(self, typed: str | None, analysis: StoryAnalysis) -> tuple[str, str, bool]:
        """(the story's account, where it came from in Spanish, whether the API can read it)."""
        candidates: list[tuple[str | None, str]] = [(typed, "escrita en el pedido")] if typed else []
        candidates += [
            (analysis.reshared_from, "la de la publicación que comparte la historia"),
            (analysis.account_in_image, "leída del encabezado de la historia"),
        ]
        swept = set(storage.read_accounts())
        known = swept | {event.account for event in self.events}
        for raw, source in candidates:
            name, cut = (raw, False) if raw == typed else stories.read_handle(raw)
            if not name:
                continue
            if not cut and self._can_read(name):
                return name, source, True
            if raw == typed:
                return name, f"{source}; Instagram no la deja leer (personal o privada)", False
            match = stories.known_account(name, cut, known)
            if match:
                return match, f"{source}, completada con una cuenta conocida", match in swept
            if not cut:
                return name, f"{source}; no pude comprobarla en Instagram", False
        raise AddPostError(
            "No pude saber de qué cuenta es la historia (el nombre no se ve o está cortado y no lo reconozco). "
            "Compártela otra vez escribiendo la @cuenta."
        )
