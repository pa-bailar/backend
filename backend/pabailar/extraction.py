"""Turn an Instagram post (images + caption) into structured events with Gemini."""

import logging
import time
from datetime import datetime

from google import genai
from google.genai import errors, types

from . import config
from .instagram import Post
from .models import PostAnalysis, StoredEvent

log = logging.getLogger(__name__)

ATTEMPTS_PER_MODEL = 3
SERVER_ERROR_BACKOFF_SECONDS = 5  # multiplied by the attempt number
RATE_LIMIT_WAIT_SECONDS = 60  # per-minute quotas reset within a minute

PROMPT = """You catalog dance events (salsa, bachata, mambo, etc.) in Bogotá, Colombia, from Instagram posts.

Instagram account: @{account}
Post published: {published} (Bogotá time)
Today: {today}

Caption:
\"\"\"{caption}\"\"\"

The images (flyer, carousel slides or a video preview frame) are attached and numbered from 0.
For each event, set image_index to the image that actually shows that event. Do not point to a
generic cover slide when another slide shows the event itself.
Several events may share the same image when that image announces all of them (e.g. a monthly schedule).

KNOWN EVENTS already announced by this account in earlier posts (id | date | start time | title):
{known_events}
Academies often announce the same event several times: a flyer, then a video, a reminder or a second
flyer. If an event in this post is one of the known events (same occasion, even if the title or wording
differs, e.g. "este sábado" vs the date), set same_as to that event's id and still fill in every detail
you can see. Otherwise set same_as to null.

What counts as an event (one-time, with a specific date):
- socials, parties, anniversaries, concerts, festivals, competitions, shows;
- one-time workshops, masterclasses and special classes with guest teachers.
What does NOT count:
- regular classes and courses, weekly or recurring nights (mark is_recurring=true if you include one);
- recaps of past events, student showcases, wedding choreographies, tutorials, motivational posts,
  general ads without a specific date.

Rules:
- A post can contain several events (e.g. a monthly schedule): return each one separately.
- Dates without a year: pick the occurrence closest after the publication date.
- Check the weekday matches the date; if not, note it in 'doubts'.
- Prices: '15K' or '15 mil' = 15000.
- Write extracted text (title, activities, doubts) in Spanish as it appears.
- Never invent data. Leave unknown fields empty and mention important gaps in 'doubts'."""


class ExtractionError(RuntimeError):
    """No Gemini model could analyze the post."""


class EventExtractor:
    def __init__(self, api_key: str):
        self._client = genai.Client(api_key=api_key)
        self._last_call = 0.0

    def _wait_for_rate_limit(self) -> None:
        wait = config.SECONDS_BETWEEN_GEMINI_CALLS - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    @staticmethod
    def _build_contents(
        account: str, post: Post, published: datetime, images: list[bytes], known_events: list[StoredEvent]
    ) -> list:
        known = "\n".join(
            f"- {event.id} | {event.date} | {event.start_time or '?'} | {event.title}" for event in known_events
        )
        prompt = PROMPT.format(
            account=account,
            published=published.astimezone(config.BOGOTA_TZ).strftime("%Y-%m-%d %A"),
            today=datetime.now(config.BOGOTA_TZ).strftime("%Y-%m-%d %A"),
            caption=post.get("caption") or "(sin texto)",
            known_events=known or "(none)",
        )
        contents: list = []
        for index, image in enumerate(images):
            contents += [f"Image {index}:", types.Part.from_bytes(data=image, mime_type="image/jpeg")]
        contents.append(prompt)
        return contents

    def analyze(
        self,
        account: str,
        post: Post,
        published: datetime,
        images: list[bytes],
        known_events: list[StoredEvent],
    ) -> tuple[PostAnalysis, str]:
        """Return the analysis and the name of the model that produced it.

        `known_events` are this account's stored events, so Gemini can tell when a post (e.g. a video)
        announces one of them again.
        """
        contents = self._build_contents(account, post, published, images, known_events)
        generation_config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PostAnalysis,
        )

        for model in config.GEMINI_MODELS:
            for attempt in range(1, ATTEMPTS_PER_MODEL + 1):
                self._wait_for_rate_limit()
                try:
                    response = self._client.models.generate_content(
                        model=model, contents=contents, config=generation_config
                    )
                    if isinstance(response.parsed, PostAnalysis):
                        return response.parsed, model
                    log.info("    %s returned no valid JSON, retrying", model)
                except errors.ServerError as error:
                    log.info("    %s busy (%s), retrying", model, error.code)
                    time.sleep(SERVER_ERROR_BACKOFF_SECONDS * attempt)
                except errors.ClientError as error:
                    if error.code == 404:  # model not available to this key
                        break
                    if error.code == 429 and attempt == 1:
                        log.info("    %s rate limit, waiting %ss", model, RATE_LIMIT_WAIT_SECONDS)
                        time.sleep(RATE_LIMIT_WAIT_SECONDS)
                        continue
                    if error.code == 429:
                        log.info("    %s quota used up, trying the next model", model)
                        break
                    raise
        raise ExtractionError("no Gemini model could analyze the post")
