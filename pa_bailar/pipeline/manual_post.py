"""Adding one post by hand (`sweep --post`, the admin tools' Agregar and Volver a leer)."""

import logging
from dataclasses import dataclass
from datetime import datetime

from .. import config, links, public_post, storage
from ..gemini import GeminiKeyError, QuotaExhaustedError, RejectedRequestError
from ..instagram import InstagramError, Post, is_not_visible, published_at
from ..models import AccountState, StoredEvent
from . import common
from .base import SweepBase
from .common import RETRYABLE_ERRORS, AddPostError, no_quota_message

log = logging.getLogger(__name__)

# What a post analyzed before became, when reading it again by hand can't change it (caption unchanged):
# published or merged, or discarded (recurring, no date) by the extraction itself. "not_event" (the filter)
# and "rejected" are read again: whoever asks says it's an event, and the extraction skips the filter.
SETTLED_OUTCOMES = ("event", "merged", "discarded")


@dataclass
class AddedPost:
    """What add_post did, for the admin tools' answer."""

    account: str
    account_added: bool  # it wasn't swept: added to accounts.txt (its older posts load on the next sweep)
    permalink: str
    outcome: str | None  # ProcessedPost.outcome
    reason: str  # Gemini's
    model: str | None
    provisional: bool
    events: list[StoredEvent]  # the events it became or joined, as stored
    public: bool = False  # read from its public page (public_post.py): the API couldn't give it
    readable: bool = True  # the API can read the account (so it's swept); False: personal or private
    unchanged: bool = False  # analyzed before and unchanged: not read again (no Gemini request; `again` forces it)
    detail: str | None = None  # ProcessedPost.detail: why it was discarded ("ya pasó", "fuera de Bogotá"...)


class ManualPosts(SweepBase):
    def add_post(self, url: str, account: str | None = None, again: bool = False) -> AddedPost:
        """Publish the events of one post by hand (`sweep --post`, the admin tools' Agregar), without triage
        (whoever asks knows it's an event).

        The post comes from Instagram's API, among the account's latest; when the API can't give it (a personal or
        private account, a collaboration listed under another account, Instagram's limit), from its public page
        (public_post.py), which also names the author when the link doesn't. An account the API can read and
        isn't swept yet is added to accounts.txt.

        Gemini only reads it when that can change something: a post analyzed before is read again only if its
        caption changed, or if it was filtered out as "not an event" or rejected (whoever asks says it is one).
        Otherwise the answer is what it already became, unless `again` ("Volver a leer"): then it's read again
        anyway (one Gemini request), e.g. after the prompts improved."""
        code = links.post_code(url)
        if not code:
            raise AddPostError("Ese enlace no es de una publicación de Instagram (instagram.com/p/…).")
        self.by_hand = True  # whoever asks wants it published, even if it was hidden before
        known_id = self._record_id(code)
        known = self.processed.get(known_id) if known_id else None
        account = account or (known.account if known else None) or links.account_in_link(url)
        public: tuple[str, Post] | None = None
        if not account:
            public = self._public_post(code)
            account = public[0]

        post: Post | None = None
        readable = True
        from_public = False
        try:
            self.instagram.check_token()
            posts = self.instagram.fetch_recent_posts(account, limit=config.ADMIN_POST_SEARCH)
            post = next((post for post in posts if links.same_post(post["permalink"], code)), None)
        except InstagramError as error:
            log.info("   the API can't give @%s's posts (%s): reading the post's public page", account, error)
            readable = not is_not_visible(error)
        if post is None:
            public = public or self._public_post(code)
            post, from_public = public[1], True
            if public[0] != account:  # a collaboration: the post is its author's
                account, readable = public[0], False
        if known_id and known_id != post["id"]:
            post = self._one_identity(known_id, post)

        added = readable and not from_public and storage.add_account(account)
        if added:
            self.accounts.setdefault(account, AccountState(first_seen=config.now_bogota().date().isoformat()))
            log.info("@%s added to accounts.txt", account)
        record = self.processed.get(post["id"])
        unchanged = (
            not again
            and record is not None
            and record.outcome in SETTLED_OUTCOMES
            and self._same_caption(post)
            and not self._announced_hidden(post["id"])  # undoing an "Ocultar": read it again
        )
        if unchanged:
            log.info("   analyzed before and unchanged: not read again %s", post["permalink"])
        else:
            published = published_at(post)
            by_hand = "by hand, read again" if again and record else "by hand"
            log.info("   %s %-14s %s (%s)", f"{published:%Y-%m-%d}", post["media_type"], post["permalink"], by_hand)
            self._extract_post(account, post, published)
            self.stats.flyers_removed = storage.remove_unused_flyers(self.events)
            self.stats.gemini_requests = self.extractor.requests_this_run()
        storage.save_account_state(self.accounts)
        storage.save_meta(self.stats.for_meta())

        record = self.processed[post["id"]]
        events = [event for event in self.events if event.id in record.event_ids]
        return AddedPost(
            record.account,
            added,
            post["permalink"],
            record.outcome,
            record.reason,
            record.model,
            record.provisional,
            events,
            public=from_public,
            readable=readable,
            unchanged=unchanged,
            detail=record.detail,
        )

    def _public_post(self, code: str) -> tuple[str, Post]:
        """The post from its public page, or AddPostError saying why it couldn't be read."""
        try:
            return public_post.fetch_public_post(code)
        except public_post.PublicPostError as error:
            raise AddPostError(f"No pude leer la publicación: la API de Instagram no la entrega y {error}.") from error

    def _extract_post(self, account: str, post: Post, published: datetime) -> None:
        """Extract and store one post without triage, or raise AddPostError saying why it couldn't."""
        if not self.extractor.can_analyze():
            raise AddPostError(no_quota_message())
        try:
            images = common.download_images(post)  # through the module: tests replace it
            known = self._known_events(account, published)
            analysis, model, provisional = self.extractor.extract(account, post, published, images, known)
        except RejectedRequestError as error:
            raise AddPostError(f"Gemini no pudo leer la publicación ({error}).") from error
        except QuotaExhaustedError as error:
            raise AddPostError(no_quota_message()) from error
        except GeminiKeyError as error:
            raise AddPostError("La clave de Gemini no funciona (vencida o revocada): hay que cambiarla.") from error
        except RETRYABLE_ERRORS as error:
            raise AddPostError(f"Algo falló al leerla ({error}). Inténtalo de nuevo en un rato.") from error
        if not self._store_analysis(account, post, images, analysis, model, provisional):
            raise AddPostError("No se pudo guardar el flyer. Inténtalo de nuevo en un rato.")
