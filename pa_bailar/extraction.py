"""Turn an Instagram post (images + caption) into structured events with Gemini, within the free quotas.

Two steps, each on the model that fits it:
  1. triage   (Flash-Lite, large quota): does the post announce an event? Most posts don't.
  2. extract  (Flash, small quota, best quality): every detail of the events. If every Flash model is
              out of quota, Flash-Lite extracts instead and the result is marked provisional, to be
              re-extracted with Flash on a later run.
The last resort (external.py): when Flash and Flash-Lite are both out of today's quota (or not available to the
key), models outside Gemini extract instead (Groq, then OpenRouter: each only with its key set). Their extractions
are always provisional. If none can answer either, Gemini's error stands: the post waits for the next run. Only for
the extraction: a Flash failure that isn't its quota (busy, a rejected request) never reaches it, and the triage
never does (with Flash-Lite out, the sweep sends the post straight to the extraction when Flash is out too: see
pipeline/sweep.py).
A story (screenshots shared to the admin page, stories.py) skips the triage: one extraction request for all
its screenshots (`extract_story`), with Flash-Lite's fallback but not the last resort (a story is never read
again, so a last-resort reading would stay).
No request starts after the extractor's `deadline` (the run's time budget, MAX_RUN_MINUTES after it's made: one
extractor per run): the work waits for the next run (gemini.OutOfTimeError).
The prompts are in prompts.py; quotas and retries in gemini.py.
"""

import io
import logging
import time
from datetime import datetime

from google.genai import types
from PIL import Image
from pydantic import BaseModel

from . import config
from .external import ExternalReport, ExternalTier
from .gemini import ExtractionError, ModelPool, OutOfTimeError, QuotaExhaustedError, UnreadableAnswerError
from .instagram import Post
from .models import PostAnalysis, StoredEvent, StoryAnalysis, Triage
from .prompts import EXTRACTION_PROMPT, STORY_PROMPT, TRIAGE_PROMPT

log = logging.getLogger(__name__)

TRIAGE_IMAGE_SIZE = (512, 512)  # triage only needs a glance at the flyer
TRIAGE_JPEG_QUALITY = 80


def _format_context(account: str, post: Post, published: datetime, rules: str) -> dict[str, str]:
    return {
        "account": account,
        "published": published.astimezone(config.BOGOTA_TZ).strftime("%Y-%m-%d %A"),
        "today": config.now_bogota().strftime("%Y-%m-%d %A"),
        "caption": post.get("caption") or "(sin texto)",
        "account_rules": rules,
    }


def _known_days(event: StoredEvent) -> str:
    """ "2026-11-13", "2026-11-13 → 2026-11-15", or a workshop series' first → last day and its sessions."""
    days = f"{event.date}{f' → {event.end_date}' if event.end_date else ''}"
    return f"{days} (sessions: {', '.join(event.session_dates)})" if event.sessions else days


def _known_list(known_events: list[StoredEvent]) -> str:
    return "\n".join(
        f"- {event.id} | {_known_days(event)} | {event.start_time or '?'} | {event.title}" for event in known_events
    )


def _small_jpeg(image: bytes) -> bytes:
    picture = Image.open(io.BytesIO(image)).convert("RGB")
    picture.thumbnail(TRIAGE_IMAGE_SIZE)
    buffer = io.BytesIO()
    picture.save(buffer, "JPEG", quality=TRIAGE_JPEG_QUALITY)
    return buffer.getvalue()


class EventExtractor:
    def __init__(self, api_key: str, external: ExternalTier | None = None, deadline: float | None = None):
        """`external`: the last resort (by default its providers' keys come from the environment). `deadline`
        (time.monotonic()): no request starts after it; by default the run's time budget from now."""
        self.deadline = deadline if deadline is not None else time.monotonic() + config.MAX_RUN_MINUTES * 60
        self.pool = ModelPool(api_key)
        self.pool.deadline = self.deadline
        self.external = external or ExternalTier()

    def can_extract_with_flash(self) -> bool:
        return self.pool.any_budget(config.EXTRACTION_MODELS)

    def reserve_flash(self, share: float) -> None:
        """This run leaves `share` of Flash's daily requests for the later sweeps of the quota day."""
        self.pool.reserve(config.EXTRACTION_MODELS, share)

    def can_upgrade(self) -> bool:
        """Flash has budget left and isn't paused as busy (gemini.BUSY_PAUSE_SECONDS): worth re-reading a provisional
        post now."""
        return self.pool.any_ready(config.EXTRACTION_MODELS)

    def can_analyze(self) -> bool:
        """Some model still has quota today for a new post (triage, extraction or provisional extraction), counting
        the last resort."""
        gemini = (*config.TRIAGE_MODELS, *config.EXTRACTION_MODELS, *config.PROVISIONAL_MODELS)
        return self.pool.any_budget(gemini) or self.external.available()

    def models_unavailable(self) -> list[str]:
        """Models Gemini said this key can't use, today (gemini.ModelPool.unavailable): every run of the day."""
        return sorted(self.pool.unavailable)

    def requests_this_run(self) -> dict[str, int]:
        """Per Gemini model, and the last resort's per provider ("groq", "openrouter")."""
        return dict(self.pool.requests_this_run) | dict(self.external.requests_this_run)

    def external_report(self) -> ExternalReport:
        """What the last resort did this run (external.ExternalReport)."""
        return self.external.report()

    def triage(
        self, account: str, post: Post, published: datetime, images: list[bytes], rules: str = ""
    ) -> tuple[Triage, str]:
        """Cheap yes/no on the caption and one small image, by Flash-Lite only: QuotaExhaustedError when it's out
        (never the last resort, whose "no" would be final and whose tokens a triage would take from the extraction).
        `rules`: the account's own (prompts.account_rules)."""
        context = _format_context(account, post, published, rules)
        contents: list[types.PartUnionDict] = [TRIAGE_PROMPT.format(**context)]
        if images:
            contents.insert(0, types.Part.from_bytes(data=_small_jpeg(images[0]), mime_type="image/jpeg"))
        # A yes/no on one small image: little reasoning needed (extraction keeps the default).
        return self.pool.generate(config.TRIAGE_MODELS, contents, Triage, thinking=types.ThinkingLevel.LOW)

    def extract(
        self,
        account: str,
        post: Post,
        published: datetime,
        images: list[bytes],
        known_events: list[StoredEvent],
        allow_provisional: bool = True,
        rules: str = "",
    ) -> tuple[PostAnalysis, str, bool]:
        """Every detail of the post's events: (analysis, model, provisional).

        `known_events` are this account's stored events, so Gemini can tell when a post (e.g. a video)
        announces one of them again. Provisional means a Flash-Lite answer, to be redone with Flash. `rules`: the
        account's own (prompts.account_rules).
        """
        known = _known_list(known_events)
        context = _format_context(account, post, published, rules)
        prompt = EXTRACTION_PROMPT.format(**context, known_events=known or "(none)")
        contents: list[types.PartUnionDict] = []
        for index, image in enumerate(images):
            contents += [f"Image {index}:", types.Part.from_bytes(data=image, mime_type="image/jpeg")]
        contents.append(prompt)
        return self._extract(contents, PostAnalysis, allow_provisional)

    def extract_story(
        self,
        images: list[bytes],
        taken: datetime,
        account: str | None,
        notes: str | None,
        known_events: list[StoredEvent],
    ) -> tuple[StoryAnalysis, str, bool]:
        """A story's events from its screenshots, in one request: (analysis, model, provisional)."""
        prompt = STORY_PROMPT.format(
            taken=taken.astimezone(config.BOGOTA_TZ).strftime("%Y-%m-%d %A %H:%M"),
            today=config.now_bogota().strftime("%Y-%m-%d %A"),
            account=f"@{account}" if account else "(none: read it from the story)",
            notes=notes or "(sin notas)",
            known_events=_known_list(known_events) or "(none)",
        )
        contents: list[types.PartUnionDict] = []
        for index, image in enumerate(images):
            contents += [f"Screenshot {index}:", types.Part.from_bytes(data=image, mime_type="image/jpeg")]
        contents.append(prompt)
        return self._extract(contents, StoryAnalysis, allow_provisional=True, last_resort=False)

    def _extract[T: BaseModel](
        self, contents: list[types.PartUnionDict], schema: type[T], allow_provisional: bool, last_resort: bool = True
    ) -> tuple[T, str, bool]:
        """Flash, else (when allowed) Flash-Lite as a provisional read, else (`last_resort`, and only when Flash and
        Flash-Lite are both out of quota) the external providers, provisional too: (answer, model, provisional)."""
        try:
            analysis, model = self.pool.generate(config.EXTRACTION_MODELS, contents, schema)
            return analysis, model, False
        except ExtractionError as error:
            if not allow_provisional:
                raise
            flash_error = error
            if not config.PROVISIONAL_MODELS:
                # Lite-only mode (Flash-Lite already extracts): only running out of quota goes on to the last resort.
                # Any other error stands as it is, so a rejected post is recorded as rejected and a busy model is
                # retried next run.
                if last_resort and isinstance(error, QuotaExhaustedError):
                    return (*self._last_resort(contents, schema, error), True)
                raise
        try:
            analysis, model = self.pool.generate(config.PROVISIONAL_MODELS, contents, schema)
        except QuotaExhaustedError as out:
            if isinstance(flash_error, UnreadableAnswerError):
                raise flash_error from out  # counted as one more unreadable run (pipeline/sweep.py), not a wait
            # The last resort stands in for Gemini's quota only: a busy Flash, or one that refused the post (a safety
            # block), leaves it waiting for Gemini, as before the last resort existed.
            if not last_resort or not isinstance(flash_error, QuotaExhaustedError):
                raise
            return (*self._last_resort(contents, schema, out), True)
        return analysis, model, True

    def _last_resort[T: BaseModel](
        self, contents: list[types.PartUnionDict], schema: type[T], gemini_error: QuotaExhaustedError
    ) -> tuple[T, str]:
        """The external providers, when Gemini is out of quota for this step: an answer and its model, or else
        Gemini's error (the post waits for the next run, as without them). Nothing starts after the deadline."""
        if time.monotonic() >= self.deadline:
            raise OutOfTimeError("the run's time budget is used") from gemini_error
        if not self.external.available():
            raise gemini_error
        try:
            analysis, model = self.external.generate(contents, schema, deadline=self.deadline)
        except ExtractionError as error:
            log.info("     the last resort couldn't answer either: %s", error)
            raise gemini_error from error
        log.info("     read by %s (last resort: Gemini out of quota)", model)
        return analysis, model
