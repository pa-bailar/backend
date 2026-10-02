"""Turn an Instagram post (images + caption) into structured events with Gemini."""

import time
from datetime import datetime
from typing import Literal, Optional

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

from . import config


class Price(BaseModel):
    label: str = Field(description="As written, e.g. 'Preventa', 'Taquilla', 'Alumnos', 'General'")
    amount_cop: int = Field(description="Colombian pesos. '15K' or '15 mil' = 15000")
    condition: Optional[str] = Field(None, description="e.g. 'hasta el 24 de septiembre', 'solo 50 cupos'")


class Event(BaseModel):
    title: str
    event_type: Literal["social", "workshop", "concert", "festival", "competition", "show", "other"] = Field(
        description="social = socials, parties, dance nights, anniversaries; workshop = one-time workshops, "
        "masterclasses and special classes with guest teachers"
    )
    image_index: Optional[int] = Field(
        description="Number of the attached image that shows THIS event (its own flyer, or the schedule slide "
        "where it is listed). Null if no image shows it."
    )
    is_recurring: bool = Field(description="True for regular classes or nights that repeat (weekly, every Friday...)")
    styles: list[str] = Field(description="Dance styles, lowercase Spanish: salsa, bachata, mambo, champeta, urbano...")
    organizer: Optional[str]
    venue: Optional[str] = Field(description="Venue name if given")
    address: Optional[str]
    area: Optional[str] = Field(description="Bogotá neighborhood or zone if given")
    date: Optional[str] = Field(description="YYYY-MM-DD")
    weekday: Optional[str] = Field(description="Spanish weekday name, lowercase")
    start_time: Optional[str] = Field(description="HH:MM, 24-hour")
    end_time: Optional[str] = Field(description="HH:MM, 24-hour")
    prices: list[Price]
    artists: list[str] = Field(description="Guest teachers, DJs, orchestras, performers")
    activities: list[str] = Field(description="Short Spanish phrases, e.g. 'clase de bachata', 'show'")
    contact: Optional[str] = Field(description="Phone/WhatsApp or @username")
    confidence: Literal["high", "medium", "low"]
    doubts: list[str] = Field(description="Missing or assumed information, in Spanish")


class PostAnalysis(BaseModel):
    is_event_post: bool = Field(description="True if the post announces at least one upcoming one-time event")
    reason: str = Field(description="One short sentence explaining the decision, in Spanish")
    events: list[Event]


PROMPT = """You catalog dance events (salsa, bachata, mambo, etc.) in Bogotá, Colombia, from Instagram posts.

Instagram account: @{account}
Post published: {posted} (Bogotá time)
Today: {today}

Caption:
\"\"\"{caption}\"\"\"

The images (flyer, carousel slides or a video preview frame) are attached and numbered from 0.
For each event, set image_index to the image that actually shows that event. Do not point to a
generic cover slide when another slide shows the event itself.

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


class Extractor:
    def __init__(self):
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self._last_call = 0.0

    def _pace(self):
        wait = config.SECONDS_BETWEEN_GEMINI_CALLS - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def analyze(self, account: str, post: dict, published: datetime, images: list[bytes]) -> tuple[PostAnalysis, str]:
        prompt = PROMPT.format(
            account=account,
            posted=published.astimezone(config.BOGOTA).strftime("%Y-%m-%d %A"),
            today=datetime.now(config.BOGOTA).strftime("%Y-%m-%d %A"),
            caption=post.get("caption") or "(sin texto)",
        )
        parts = []
        for i, image in enumerate(images):
            parts += [f"Image {i}:", types.Part.from_bytes(data=image, mime_type="image/jpeg")]
        parts.append(prompt)
        gen_config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=PostAnalysis)

        for model in config.GEMINI_MODELS:
            for attempt in range(3):
                self._pace()
                try:
                    response = self.client.models.generate_content(model=model, contents=parts, config=gen_config)
                    return response.parsed, model
                except errors.ServerError as e:
                    print(f"     ({model} busy: {e.code}, retrying)")
                    time.sleep(5 * (attempt + 1))
                except errors.ClientError as e:
                    if e.code == 404:
                        break  # model not available to this key
                    if e.code == 429:
                        if attempt == 0:
                            print(f"     ({model} rate limit, waiting 60s)")
                            time.sleep(60)  # per-minute limit: wait for it to reset
                            continue
                        print(f"     ({model} quota used up, trying the next model)")
                        break
                    raise
        raise RuntimeError("Gemini did not respond after several attempts")
