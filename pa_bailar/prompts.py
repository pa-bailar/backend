"""The prompts sent to Gemini: what counts as an event, how to classify and extract it.

Kept apart from the code that calls Gemini, so wording can be tuned without touching the logic.
"""

from .models import STYLES

_POST_CONTEXT = """Instagram account: @{account}
Post published: {published} (Bogotá time)
Today: {today}

Caption:
\"\"\"{caption}\"\"\""""

_EVENT_DEFINITION = """An event is a single DANCE occasion on a specific date that anyone can attend. An event over
several consecutive days (a congress, a festival weekend, an intensive "del 7 al 11", "10, 11 y 12 de octubre")
is ONE event, from its first to its last day.

What counts:
- socials and parties: "social", "noche de salsa/bachata", "rumba", "fiesta", "previa", anniversaries
  ("aniversario"), Halloween or holiday parties; concerts and live bands for social or partner dancing (a
  salsa orchestra, a bachata or merengue band, son, timba, kizomba, tango, champeta…); dance congresses
  and festivals; competitions and battles ("concurso", "batalla"); shows and galas;
- one-time workshops: "taller", "masterclass", "clase especial", "clase única", "clase abierta" on a given
  date, "bootcamp", "intensivo", a class with a guest teacher.

What does NOT count:
- anything that isn't about dancing, even when a dance academy or venue hosts it or posts it: drawing,
  painting, theater, music or singing lessons, yoga, pilates, fitness without dancing, markets, talks,
  sports (e.g. "taller de dibujo", "semillero de creación de personajes"). It's a dance event only if
  dancing is what people come to do or watch;
- concerts and music festivals that aren't for social or partner dancing: electronic (EDM, techno, house),
  rock, pop, indie, reggaeton or urbano mass concerts, and general music festivals (e.g. "EDC", "Estéreo
  Picnic", a pop or rock band's tour), even when a promoter or venue that also hosts dance events posts
  them. A concert or festival counts only when it's for social or partner dancing (salsa, bachata, merengue,
  son, timba, kizomba, tango, champeta…): a salsa orchestra's concert, or a dance festival with socials and
  workshops;
- regular classes and courses: schedules ("horarios"), "todos los jueves", "cada viernes", "inscripciones
  abiertas", "cursos", "niveles", monthly fees ("mensualidad"), and programs spread over several weeks
  (e.g. "sábados 10, 17 y 24"), unless each date is a separate occasion (e.g. three socials, each with
  its own theme);
- things that already happened: recaps ("gracias a todos", "así se vivió"), photos or videos of past
  events, results;
- student showcases, wedding choreographies ("coreografía de boda"), tutorials, challenges, motivational
  posts, merchandise, and ads without a specific date;
- posts announcing that an event is cancelled or postponed without a new date (a postponed event with
  its new date does count, with the new date);
- events in another city or country, when the post says so (teachers and artists travel: "taller en
  Medellín", "gira por México"). With no city stated, the event is in Bogotá.
A post can mix both (e.g. the weekly schedule plus one special social): only the one-time dance events
count."""

_TYPES_AND_STYLES = f"""Event type, by the main purpose of the event:
- social: socials, parties, "noche de…", anniversaries, Halloween/fiestas. A social that starts with a
  short class is still a social.
- workshop: taller, masterclass, clase especial or única, bootcamp, intensivo, class with a guest teacher.
- concert: live band or orchestra.
- congress: a dance congress or encuentro ("congreso", "congress", "encuentro", "weekender"), usually over
  several days (set date and end_date) with workshops, socials, shows and often competitions, with national
  and international artists and passes ("full pass"). Several workshops as part of one congress are the
  congress, not workshops. If the post announces a congress without exact dates (only "en noviembre"), it
  has no date.
- festival: a festival of music or dance more broadly (e.g. "Salsa al Parque"), not a congress.
- competition: concurso, competencia, batalla. show: a performance or gala without social dancing.
- other: anything else.

Dance styles: only from this list: {", ".join(STYLES)}.
- Salsa: "salsa cubana" for casino, rueda or timba; "salsa en línea" for on1, on2, mambo or
  New York / Los Angeles style; "salsa caleña" for estilo caleño. Plain "salsa" when the variant isn't said.
- Bachata: "bachata sensual" or "bachata dominicana" (tradicional) when said; otherwise plain "bachata".
- Other styles stay general (reguetón and hip hop are "urbano"; rumba and afrobeat are "afro").
- Use the flyer, the caption and the hashtags. Don't guess styles that aren't mentioned or shown."""

TRIAGE_PROMPT = f"""You screen Instagram posts of dance academies, organizers and artists in Bogotá, Colombia.

{_POST_CONTEXT}

The first image of the post (flyer, slide or video frame) is attached.

{_EVENT_DEFINITION}

Does this post announce at least one upcoming event, one that hasn't ended: its date, or its last day for
an event over several days, is today or later? A post whose events all ended before today is false (posts
can be weeks old). When unsure, answer true: a later step checks the details, but a post wrongly answered
false is lost."""

EXTRACTION_PROMPT = f"""You catalog dance events in Bogotá, Colombia, from Instagram posts.

{_POST_CONTEXT}

The images (flyer, carousel slides or a video preview frame) are attached and numbered from 0.
For each event, set image_index to the image that actually shows that event. Do not point to a
generic cover slide when another slide shows the event itself.
Several events may share the same image when that image announces all of them (e.g. a monthly schedule).

KNOWN EVENTS already announced by this account in earlier posts (id | date, or first → last day | start time |
title):
{{known_events}}
Academies often announce the same event several times: a flyer, then a video, a reminder or a second
flyer. If an event in this post is one of the known events (same occasion, even if the title or wording
differs, e.g. "este sábado" vs the date), set same_as to that event's id and still fill in every detail
you can see. A post presenting a teacher, an artist or one night of a congress or festival announces that
same congress or festival: one event with its dates, linked by same_as when it's known. Otherwise set same_as
to null.

{_EVENT_DEFINITION}
(Mark is_recurring=true for any regular or weekly event you include.)

{_TYPES_AND_STYLES}

Rules:
- A post can contain several events (e.g. a monthly schedule): return each one separately. A flyer listing
  different events is one event per occasion.
- date: the event's day, or its FIRST day for an event over several consecutive days. end_date: its LAST
  day ("NOV 13-15 2026" → date 2026-11-13, end_date 2026-11-15; "31 Oct, 1 y 2 Nov" → 2026-10-31 and
  2026-11-02). end_date is null for a one-day event, including a night that goes on past midnight.
- Never return one event per day of an event over several days. But the same workshop or social on separate,
  non-consecutive dates or at different venues is one event per date.
- Times of an event over several days: start_time is the first day's start, end_time the last day's end;
  null when the post only gives a schedule per day.
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

# A story, from screenshots (stories.py): one request for all of them. Dates are copied as printed, and worked
# out in code (stories.resolve_date). The admin's notes stand in for a caption.
STORY_PROMPT = f"""You catalog dance events in Bogotá, Colombia, from screenshots of ONE Instagram story.

The screenshots are attached, numbered from 0; several are slides of the same story.
Taken: {{taken}} (Bogotá time)
Today: {{today}}
Account given by the site's admin: {{account}}

They are phone screenshots: ignore Instagram's interface (the progress bars, the avatar and the account's
name at the top, the reply bar, hearts and buttons at the bottom) and anything of the phone's. Read the
story's own content: the flyer, its text and its stickers.

Notes from the site's admin, trusted (they may complete or correct what the story shows; never publish them as
text of their own):
\"\"\"{{notes}}\"\"\"

KNOWN EVENTS already announced by this account (id | date, or first → last day | start time | title):
{{known_events}}
If an event in this story is one of them (same occasion, even if worded differently), set same_as to its id.

Besides the events, read:
- account_in_image: the username at the top of the story, next to the avatar, exactly as shown (with "…" when
  it's cut off). Null if it isn't visible.
- reshared_from: when the story shows another account's post or story as a card (with that account's
  @username on the card), that username. The event is that account's.
- mentions_in_image: @usernames in mention stickers or written on the story (teachers, DJs, venues), without
  the "@". They are NOT the story's account.
- location_sticker: the text of a location sticker, if any (it's usually the venue).
- story_age: how long ago it was posted, as shown next to the username ("5 h", "32 min").
- images: one entry per screenshot, with content_box around the story's own content (the flyer, photo or
  video frame), without Instagram's interface: [ymin, xmin, ymax, xmax] from 0 to 1000. A full-screen flyer
  goes from just below the header to just above the reply bar. Null when that screenshot shows no event.

{_EVENT_DEFINITION}
For stories, one exception: a social or party night that repeats every week ("todos los viernes", "cada
sábado") counts: set weekly=true and its weekday (only its next date is published). Regular classes and
courses still don't count (is_recurring=true).

Dates: copy what's printed, don't work them out (that's done later):
- day, month: as printed ("SÁB 12 OCT" → day 12, month 10, weekday "sábado"). year: only if printed, never
  guessed. end_day and end_month: the last day of an event over several consecutive days ("13-15 NOV").
- weekday: the weekday printed or meant ("este sábado" → "sábado"), Spanish, lowercase.
- relative_day: "hoy" for "hoy" or "esta noche", "mañana" for "mañana"; otherwise null.
- date_text: the date exactly as printed. All null when the story gives no date.

{_TYPES_AND_STYLES}

Rules:
- A story can announce several events (e.g. a weekend's schedule): return each one, each with image_index,
  the screenshot that shows it best.
- Prices: '15K' or '15 mil' = 15000.
- contact: an @username, a website or a phone number ('WhatsApp ' before a number marked as WhatsApp).
- Write extracted text (title, activities, doubts) in Spanish as it appears.
- Never invent data. Leave unknown fields empty.
- confidence: high when the date (and time, if any) are printed explicitly; medium when something is implied
  (e.g. "este sábado"); low when the date itself is unclear.
- doubts: only important gaps or assumptions, one short phrase each (e.g. "sin precio")."""
