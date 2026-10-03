"""The prompts sent to Gemini: what counts as an event, how to classify and extract it.

Kept apart from the code that calls Gemini, so wording can be tuned without touching the logic.
"""

from .models import STYLES

_POST_CONTEXT = """Instagram account: @{account}
Post published: {published} (Bogotá time)
Today: {today}

Caption:
\"\"\"{caption}\"\"\""""

_EVENT_DEFINITION = """What counts as an event (one-time, with a specific date):
- socials, parties, anniversaries, concerts, festivals, competitions, shows;
- one-time workshops, masterclasses and special classes with guest teachers.
What does NOT count:
- anything that isn't about dancing, even when a dance academy or venue hosts it or posts it: drawing,
  painting, theater, music lessons, yoga, markets, talks, sports (e.g. "taller de dibujo" at an academy);
- regular classes and courses, weekly or recurring nights;
- recaps of past events, student showcases, wedding choreographies, tutorials, motivational posts,
  general ads without a specific date;
- posts announcing that an event is cancelled or postponed without a new date (a postponed event with
  its new date does count, with the new date)."""

TRIAGE_PROMPT = f"""You screen Instagram posts of dance academies in Bogotá, Colombia.

{_POST_CONTEXT}

The first image of the post (flyer, slide or video frame) is attached.

{_EVENT_DEFINITION}

Does this post announce at least one upcoming event, one whose date is today or later? A post whose
events all took place before today is false (posts can be weeks old). When unsure, answer true: a later
step checks the details, but a post wrongly answered false is lost."""

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
- If the weekday and the date disagree, trust the date written with numbers and set confidence to low.
- Prices: '15K' or '15 mil' = 15000.
- contact: an @username, a website or a phone number. If the flyer or the caption marks the number
  as WhatsApp (the word, or the green WhatsApp icon next to it), write 'WhatsApp ' before it, e.g.
  'WhatsApp 3001234567'; the site then opens a chat. Otherwise just the number.
- Write extracted text (title, activities, doubts) in Spanish as it appears.
- Never invent data. Leave unknown fields empty.
- confidence: high when the date (and time, if any) are written explicitly; medium when you had to infer
  something (e.g. the date from "este sábado"); low when the date itself is uncertain or contradictory.
  The website asks visitors to confirm in the post when it's low.
- doubts: only important gaps or assumptions, one short phrase each (e.g. "sin precio")."""
