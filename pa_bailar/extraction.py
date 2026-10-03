"""Turn an Instagram post (images + caption) into structured events with Gemini, within the free quotas.

Two steps, each on the model that fits it:
  1. triage   (Flash-Lite, large quota): does the post announce an event? Most posts don't.
  2. extract  (Flash, small quota, best quality): every detail of the events. If every Flash model is
              out of quota, Flash-Lite extracts instead and the result is marked provisional, to be
              re-extracted with Flash on a later run.
The prompts are in prompts.py; quotas and retries in gemini.py.
"""

import io
from datetime import datetime

from google.genai import types
from PIL import Image

from . import config
from .gemini import ExtractionError, ModelPool
from .instagram import Post
from .models import PostAnalysis, StoredEvent, Triage
from .prompts import EXTRACTION_PROMPT, TRIAGE_PROMPT

TRIAGE_IMAGE_SIZE = (512, 512)  # triage only needs a glance at the flyer
TRIAGE_JPEG_QUALITY = 80


def _format_context(account: str, post: Post, published: datetime) -> dict[str, str]:
    return {
        "account": account,
        "published": published.astimezone(config.BOGOTA_TZ).strftime("%Y-%m-%d %A"),
        "today": config.now_bogota().strftime("%Y-%m-%d %A"),
        "caption": post.get("caption") or "(sin texto)",
    }


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
        known = "\n".join(
            f"- {event.id} | {event.date} | {event.start_time or '?'} | {event.title}" for event in known_events
        )
        prompt = EXTRACTION_PROMPT.format(**_format_context(account, post, published), known_events=known or "(none)")
        contents: list[types.PartUnionDict] = []
        for index, image in enumerate(images):
            contents += [f"Image {index}:", types.Part.from_bytes(data=image, mime_type="image/jpeg")]
        contents.append(prompt)

        try:
            analysis, model = self.pool.generate(config.EXTRACTION_MODELS, contents, PostAnalysis)
            return analysis, model, False
        except ExtractionError:
            if not allow_provisional:
                raise
        analysis, model = self.pool.generate(config.PROVISIONAL_MODELS, contents, PostAnalysis)
        return analysis, model, True
