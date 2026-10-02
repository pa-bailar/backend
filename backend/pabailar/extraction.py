"""Turn an Instagram post (images + caption) into structured events with Gemini, within the free quotas.

Two steps, each on the model that fits it:
  1. triage   (Flash-Lite, large quota): does the post announce an event? Most posts don't.
  2. extract  (Flash, small quota, best quality): every detail of the events. If every Flash model is
              out of quota, Flash-Lite extracts instead and the result is marked provisional, to be
              re-extracted with Flash on a later run.
`ModelPool` spaces calls per model (requests per minute) and stops using a model when its daily budget
is spent, persisting the day's usage so several runs on the same day share it.
"""

import io
import logging
import time
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from google import genai
from google.genai import errors, types
from PIL import Image
from pydantic import BaseModel

from . import config, storage
from .instagram import Post
from .models import STYLES, PostAnalysis, StoredEvent, Triage

log = logging.getLogger(__name__)

ATTEMPTS_PER_MODEL = 3
SERVER_ERROR_BACKOFF_SECONDS = 5  # multiplied by the attempt number
RATE_LIMIT_WAIT_SECONDS = 60  # per-minute quotas reset within a minute
TRIAGE_IMAGE_SIZE = (512, 512)  # triage only needs a glance at the flyer

_POST_CONTEXT = """Instagram account: @{account}
Post published: {published} (Bogotá time)
Today: {today}

Caption:
\"\"\"{caption}\"\"\""""

_EVENT_DEFINITION = """What counts as an event (one-time, with a specific date):
- socials, parties, anniversaries, concerts, festivals, competitions, shows;
- one-time workshops, masterclasses and special classes with guest teachers.
What does NOT count:
- regular classes and courses, weekly or recurring nights;
- recaps of past events, student showcases, wedding choreographies, tutorials, motivational posts,
  general ads without a specific date."""

TRIAGE_PROMPT = f"""You screen Instagram posts of dance academies in Bogotá, Colombia.

{_POST_CONTEXT}

The first image of the post (flyer, slide or video frame) is attached.

{_EVENT_DEFINITION}

Does this post announce at least one upcoming event? When unsure, answer true: a later step checks
the details, but a post wrongly answered false is lost."""

EXTRACTION_PROMPT = f"""You catalog dance events in Bogotá, Colombia, from Instagram posts.

{_POST_CONTEXT}

The images (flyer, carousel slides or a video preview frame) are attached and numbered from 0.
For each event, set image_index to the image that actually shows that event. Do not point to a
generic cover slide when another slide shows the event itself.
Several events may share the same image when that image announces all of them (e.g. a monthly schedule).

KNOWN EVENTS already announced by this account in earlier posts (id | date | start time | title):
{{known_events}}
Academies often announce the same event several times: a flyer, then a video, a reminder or a second
flyer. If an event in this post is one of the known events (same occasion, even if the title or wording
differs, e.g. "este sábado" vs the date), set same_as to that event's id and still fill in every detail
you can see. Otherwise set same_as to null.

{_EVENT_DEFINITION}
(Mark is_recurring=true for any regular or weekly event you include.)

Event type, by the main purpose of the event:
- social: socials, parties, "noche de…", anniversaries, Halloween/fiestas. A social that starts with a
  short class is still a social.
- workshop: taller, masterclass, clase especial or única, bootcamp, intensivo, class with a guest teacher.
- concert: live band or orchestra. festival: multi-day festival or congress.
- competition: concurso, competencia, batalla. show: a performance or gala without social dancing.
- other: anything else.

Dance styles: only from this list: {", ".join(STYLES)}.
- Salsa: "salsa cubana" for casino, rueda or timba; "salsa en línea" for on1, on2, mambo or
  New York / Los Angeles style; "salsa caleña" for estilo caleño. Plain "salsa" when the variant isn't said.
- Bachata: "bachata sensual" or "bachata dominicana" (tradicional) when said; otherwise plain "bachata".
- Other styles stay general (reguetón and hip hop are "urbano"; rumba and afrobeat are "afro").
- Use the flyer, the caption and the hashtags. Don't guess styles that aren't mentioned or shown.

Rules:
- A post can contain several events (e.g. a monthly schedule): return each one separately.
- Dates without a year: pick the occurrence closest after the publication date.
- Check the weekday matches the date; if not, note it in 'doubts'.
- Prices: '15K' or '15 mil' = 15000.
- Write extracted text (title, activities, doubts) in Spanish as it appears.
- Never invent data. Leave unknown fields empty and mention important gaps in 'doubts'."""


class ExtractionError(RuntimeError):
    """No Gemini model could answer (all out of quota, unavailable or failing)."""


def _quota_day() -> str:
    """Gemini daily quotas reset at midnight Pacific time."""
    return datetime.now(ZoneInfo(config.QUOTA_TIMEZONE)).date().isoformat()


def _daily_budget(model: str) -> int:
    limit = config.MODEL_LIMITS[model]
    return max(0, limit.requests_per_day - config.DAILY_BUDGET_MARGIN)


def _is_daily_quota_error(error: errors.ClientError) -> bool:
    text = str(error).lower()
    return "per day" in text or "perday" in text or "daily" in text


class ModelPool:
    """Calls Gemini models in a preferred order while respecting each one's quotas."""

    def __init__(self, api_key: str):
        self._client = genai.Client(api_key=api_key)
        self._day = _quota_day()
        usage = storage.load_gemini_usage()
        self._used: Counter[str] = Counter(usage.get("requests", {}) if usage.get("day") == self._day else {})
        self._last_call: dict[str, float] = {}
        self.requests_this_run: Counter[str] = Counter()

    def has_budget(self, model: str) -> bool:
        return self._used[model] < _daily_budget(model)

    def any_budget(self, models: list[str]) -> bool:
        return any(self.has_budget(model) for model in models)

    def _spend(self, model: str) -> None:
        self._used[model] += 1
        self.requests_this_run[model] += 1
        storage.save_gemini_usage({"day": self._day, "requests": dict(self._used)})

    def _exhaust(self, model: str) -> None:
        self._used[model] = max(self._used[model], _daily_budget(model))
        storage.save_gemini_usage({"day": self._day, "requests": dict(self._used)})

    def _pace(self, model: str) -> None:
        interval = 60 / config.MODEL_LIMITS[model].requests_per_minute + config.PACING_MARGIN_SECONDS
        wait = interval - (time.monotonic() - self._last_call.get(model, 0.0))
        if wait > 0:
            time.sleep(wait)
        self._last_call[model] = time.monotonic()

    def generate[T: BaseModel](self, models: list[str], contents: list, schema: type[T]) -> tuple[T, str]:
        """The parsed answer of the first model in `models` that can give one, and that model's name."""
        generation_config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            # We pass no tools; disabling this also silences the SDK's warning about it.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        for model in models:
            for attempt in range(1, ATTEMPTS_PER_MODEL + 1):
                if not self.has_budget(model):
                    log.info("    %s: daily budget used up, skipping", model)
                    break
                self._pace(model)
                self._spend(model)
                try:
                    response = self._client.models.generate_content(
                        model=model, contents=contents, config=generation_config
                    )
                    if isinstance(response.parsed, schema):
                        return response.parsed, model
                    log.info("    %s returned no valid JSON, retrying", model)
                except errors.ServerError as error:
                    log.info("    %s busy (%s), retrying", model, error.code)
                    time.sleep(SERVER_ERROR_BACKOFF_SECONDS * attempt)
                except errors.ClientError as error:
                    if error.code == 404:  # model not available to this key
                        log.warning("    %s is not available to this API key", model)
                        self._exhaust(model)
                        break
                    if error.code == 429 and (attempt > 1 or _is_daily_quota_error(error)):
                        log.info("    %s daily quota used up, trying the next model", model)
                        self._exhaust(model)
                        break
                    if error.code == 429:
                        log.info("    %s per-minute limit, waiting %ss", model, RATE_LIMIT_WAIT_SECONDS)
                        time.sleep(RATE_LIMIT_WAIT_SECONDS)
                        continue
                    raise
        raise ExtractionError(f"no model could answer ({', '.join(models)})")


def _format_context(account: str, post: Post, published: datetime) -> dict[str, str]:
    return {
        "account": account,
        "published": published.astimezone(config.BOGOTA_TZ).strftime("%Y-%m-%d %A"),
        "today": datetime.now(config.BOGOTA_TZ).strftime("%Y-%m-%d %A"),
        "caption": post.get("caption") or "(sin texto)",
    }


def _small_jpeg(image: bytes) -> bytes:
    picture = Image.open(io.BytesIO(image)).convert("RGB")
    picture.thumbnail(TRIAGE_IMAGE_SIZE)
    buffer = io.BytesIO()
    picture.save(buffer, "JPEG", quality=80)
    return buffer.getvalue()


class EventExtractor:
    def __init__(self, api_key: str):
        self.pool = ModelPool(api_key)

    def can_extract_with_flash(self) -> bool:
        return self.pool.any_budget(config.EXTRACTION_MODELS)

    def requests_this_run(self) -> dict[str, int]:
        return dict(self.pool.requests_this_run)

    def triage(self, account: str, post: Post, published: datetime, images: list[bytes]) -> tuple[Triage, str]:
        """Cheap yes/no on the caption and one small image."""
        contents: list = [TRIAGE_PROMPT.format(**_format_context(account, post, published))]
        if images:
            contents.insert(0, types.Part.from_bytes(data=_small_jpeg(images[0]), mime_type="image/jpeg"))
        return self.pool.generate(config.TRIAGE_MODELS, contents, Triage)

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
        contents: list = []
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
