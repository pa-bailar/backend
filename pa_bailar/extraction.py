"""Turn an Instagram post (images + caption) into structured events with Gemini, within the free quotas.

Two steps, each on the model that fits it:
  1. triage   (Flash-Lite, large quota): does the post announce an event? Most posts don't.
  2. extract  (Flash, small quota, best quality): every detail of the events. If every Flash model is
              out of quota, Flash-Lite extracts instead and the result is marked provisional, to be
              re-extracted with Flash on a later run.
A story (screenshots shared to the admin page, stories.py) skips the triage: one extraction request for all
its screenshots (`extract_story`), with the same fallback.
The prompts are in prompts.py; quotas and retries in gemini.py.
"""

import io
from datetime import datetime

from google.genai import types
from PIL import Image
from pydantic import BaseModel

from . import config
from .gemini import ExtractionError, ModelPool
from .instagram import Post
from .models import PostAnalysis, StoredEvent, StoryAnalysis, Triage
from .prompts import EXTRACTION_PROMPT, STORY_PROMPT, TRIAGE_PROMPT

TRIAGE_IMAGE_SIZE = (512, 512)  # triage only needs a glance at the flyer
TRIAGE_JPEG_QUALITY = 80


def _format_context(account: str, post: Post, published: datetime) -> dict[str, str]:
    return {
        "account": account,
        "published": published.astimezone(config.BOGOTA_TZ).strftime("%Y-%m-%d %A"),
        "today": config.now_bogota().strftime("%Y-%m-%d %A"),
        "caption": post.get("caption") or "(sin texto)",
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
    def __init__(self, api_key: str):
        self.pool = ModelPool(api_key)

    def can_extract_with_flash(self) -> bool:
        return self.pool.any_budget(config.EXTRACTION_MODELS)

    def can_analyze(self) -> bool:
        """Some model still has quota today for a new post (triage, extraction or provisional extraction)."""
        return self.pool.any_budget((*config.TRIAGE_MODELS, *config.EXTRACTION_MODELS, *config.PROVISIONAL_MODELS))

    def models_unavailable(self) -> list[str]:
        """Models Gemini said this key can't use, this run (gemini.ModelPool.unavailable)."""
        return sorted(self.pool.unavailable)

    def requests_this_run(self) -> dict[str, int]:
        return dict(self.pool.requests_this_run)

    def triage(self, account: str, post: Post, published: datetime, images: list[bytes]) -> tuple[Triage, str]:
        """Cheap yes/no on the caption and one small image."""
        contents: list[types.PartUnionDict] = [TRIAGE_PROMPT.format(**_format_context(account, post, published))]
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
    ) -> tuple[PostAnalysis, str, bool]:
        """Every detail of the post's events: (analysis, model, provisional).

        `known_events` are this account's stored events, so Gemini can tell when a post (e.g. a video)
        announces one of them again. Provisional means a Flash-Lite answer, to be redone with Flash.
        """
        known = _known_list(known_events)
        prompt = EXTRACTION_PROMPT.format(**_format_context(account, post, published), known_events=known or "(none)")
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
        return self._extract(contents, StoryAnalysis, allow_provisional=True)

    def _extract[T: BaseModel](
        self, contents: list[types.PartUnionDict], schema: type[T], allow_provisional: bool
    ) -> tuple[T, str, bool]:
        """Flash, else (when allowed) Flash-Lite as a provisional read: (answer, model, provisional)."""
        try:
            analysis, model = self.pool.generate(config.EXTRACTION_MODELS, contents, schema)
            return analysis, model, False
        except ExtractionError:
            # No provisional models (lite-only mode, where Flash-Lite already extracts): the error stands as it
            # is, so a rejected post is recorded as rejected and a busy model is retried next run.
            if not allow_provisional or not config.PROVISIONAL_MODELS:
                raise
        analysis, model = self.pool.generate(config.PROVISIONAL_MODELS, contents, schema)
        return analysis, model, True
