"""The pre-filter: a rule, no AI, that tells a post obviously announcing no event before the triage spends a Gemini
request on it (the owner, 9 Oct 2026: save requests without ever missing an event).

A post is "obviously not an event" only on conservative evidence, all of it:
  - its caption names nothing an announcement names: no date, day, weekday, month or relative day ("hoy", "mañana",
    "este finde"), no time, no price or sale, no event word (social, taller, fiesta, concierto…), no invitation ("te
    esperamos", "nos vemos"), no venue or address, no link, phone or sign-up (CAPTION_SIGNALS);
  - and its images say nothing either: a flyer may carry everything while the caption says "🔥". Only OCR text
    rules an image out (ocr.py): each image read, none with a signal, a digit or more than a few letters
    (config.PREFILTER_MAX_IMAGE_LETTERS; a flyer always has text, a photo of dancers hardly any). Without OCR (it isn't
    in the sweep's requirements: models of ~31 MB from modelscope.cn on first use), or with more images than
    config.PREFILTER_MAX_IMAGES, the images aren't ruled out and the post is read.
So what's left is a photo or a video's frame with no text and a caption that says nothing of an event (a thank-you, a
meme without words, a dancer's photo). Few posts qualify, on purpose: a false "skip" loses an event for good, a false
"read" costs one triage request.

It runs in shadow first (config.PREFILTER_MODE): its verdict is recorded next to Gemini's and nothing is skipped.

The word lists are the pre-filter's own and broad on purpose: any hint means the post is read. They're matched whole
(folded: no accents, no case, Instagram's fancy fonts as plain letters: text.fold), and inside hashtags as parts of
words ("#socialdesalsa"). The dates, times and prices are the rule checks' (checks.py), with text.PRICE_WORDS."""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from . import checks, config, ocr
from .text import fold

# Kinds of event and what announcements call them, Spanish (Colombian) and English, folded. Not "baile"/"bailar":
# every dance post says them; the image check stands behind a caption without these.
_EVENT_WORDS = {
    *("social", "sociales", "taller", "talleres", "workshop", "workshops", "clase", "clases", "curso", "cursos"),
    *("masterclass", "masterclasses", "bootcamp", "intensivo", "intensiva", "seminario", "laboratorio", "ciclo"),
    *("fiesta", "fiestas", "rumba", "rumbas", "party", "parties", "concierto", "conciertos", "recital", "congreso"),
    *("congresos", "congress", "festival", "festivales", "fest", "encuentro", "encuentros", "evento", "eventos"),
    *("event", "events", "show", "shows", "gala", "competencia", "competition", "campeonato", "championship"),
    *("concurso", "batalla", "battle", "torneo", "presentacion", "presentaciones", "muestra", "lanzamiento"),
    *("aniversario", "anniversary", "cumpleanos", "celebracion", "celebramos", "tardeo", "tardeos", "matine"),
    *("matinee", "milonga", "milongas", "practica", "practicas", "salsoteca", "verbena", "bailaton", "noche"),
    *("noches", "night", "nights", "jornada", "toque", "vivo", "live", "dj", "orquesta", "sesion", "sesiones"),
    *("convocatoria", "audicion", "audiciones", "casting", "inscripcion", "inscripciones", "inscribete"),
    *("inscribanse", "inscribirte", "cupo", "cupos", "reserva", "reservas", "reservar", "reservacion"),
    *("reservaciones", "entrada", "entradas", "ticket", "tickets", "gratis", "gratuito", "gratuita", "free"),
    *("invitado", "invitada", "invitados", "invitadas", "invitamos", "invita", "invitacion", "esperamos"),
    *("vente", "ven", "vengan", "acompananos", "asiste", "agenda", "agendate", "proximamente", "pronto"),
    *("regresa", "vuelve", "volvemos", "llega", "llegamos", "anuncio", "anunciamos", "cartelera", "programacion"),
    *("lineup", "apertura", "inauguracion", "abrimos", "temporada", "edicion", "halloween", "navidad", "novena"),
    *("feria", "carnaval", "festividad", "parche", "plan", "planazo", "rumbear", "parrandear", "tour", "gira"),
}
# Days, relative days and months as words, whatever is around them: "todos los sábados" (a regular night: the triage
# tells), "mañana", "finde". Short forms flyers print ("SÁB", "VIE"); "mar" (martes or marzo, or the sea) too.
_TIME_WORDS = {
    *("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "sabados", "domingo", "domingos"),
    *("lun", "mar", "mie", "mier", "jue", "vie", "sab", "dom"),
    *("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "tonight", "today"),
    *("tomorrow", "weekend", "hoy", "manana", "finde", "semana", "puente", "festivo", "feriado", "proximo"),
    *("proxima", "tarde", "medianoche", "mediodia", "horario", "horarios", "fecha", "fechas", "dia", "dias"),
    *("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "setiembre"),
    *("octubre", "noviembre", "diciembre", "ene", "feb", "abr", "may", "jun", "jul", "ago", "sep", "sept", "set"),
    *("oct", "nov", "dic", "january", "february", "march", "april", "june", "july", "august", "september"),
    *("october", "november", "december", "pm", "am", "hrs", "horas"),
}
# Where and how to go or ask: an address, a venue, a link, a phone.
_PLACE_WORDS = {
    *("lugar", "direccion", "ubicacion", "ubicados", "sede", "sedes", "calle", "carrera", "cra", "cr", "kr", "kra"),
    *("cl", "cll", "avenida", "av", "diagonal", "dg", "transversal", "tv", "barrio", "piso", "local", "teatro"),
    *("auditorio", "coliseo", "plaza", "parque", "estadio", "link", "bio", "linktree", "whatsapp", "wpp", "info"),
    *("informes", "informacion", "dm", "md", "escribenos", "contactanos", "contacto", "boleteria", "taquilla"),
}
# Phrases (folded), as whole words: invitations and dates the words alone don't catch.
_PHRASES = re.compile(
    r"\b(?:nos vemos|los esperamos|las esperamos|te esperamos|no te lo pierdas|no te la pierdas|no faltes"
    r"|save the date|fin de semana|esta noche|este (?:viernes|sabado|domingo|jueves)|join us|line up"
    r"|(?:el|este|del|al|desde el|hasta el|a partir del) (?:3[01]|[12]\d|0?[1-9])\b)"
)
# Stems found inside hashtags ("#socialdesalsa", "#rumbaenbogota", "#sabadodesalsa").
_HASHTAG_STEMS = (
    *("social", "taller", "workshop", "clase", "fiesta", "rumba", "party", "concierto", "congres", "festival"),
    *("fest", "evento", "event", "show", "noche", "night", "milonga", "practica", "salsoteca", "tardeo"),
    *("bootcamp", "masterclass", "gala", "competencia", "encuentro", "aniversario", "envivo", "live", "hoy"),
    *("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo", "finde", "weekend", "agenda"),
)
_HASHTAG = re.compile(r"#(\w+)")
# Emoji announcements use for when, where and how much: calendars, clocks, pins, tickets, money.
_EMOJI = re.compile(
    "[\U0001f4c5\U0001f4c6\U0001f5d3⏰⏱⏲⌚⏳⌛\U0001f550-\U0001f567\U0001f4cd\U0001f4cc"
    "\U0001f5fa\U0001f3df\U0001f3ab\U0001f39f\U0001f4b5\U0001f4b2\U0001f4b0\U0001f4b8\U0001f4b3\U0001f4de\U0001f4f2]"
)
_LINK = re.compile(r"https?://|www\.|\.com\b|\.co\b|wa\.me|bit\.ly|linktr\.ee")
_ADDRESS = re.compile(r"(?:#|n[o°º]\.?)\s?\d")  # "#36-15", "No. 82"
_PHONE = re.compile(r"\+?\d[\d \-]{6,}\d")  # "+57 300 123 4567", "3001234567"
_WORD = re.compile(r"[a-z]+")

ImageText = Callable[[bytes], str | None]  # an image's text by OCR; None when there's no OCR


@dataclass(frozen=True)
class Verdict:
    """What the pre-filter says of a post: skip it (obviously no event) or read it, and why (in Spanish, for the post's
    record). `text_silent`: its caption names nothing of an event, so the verdict rests on its images (shadow data:
    how often an event is all in the image)."""

    skip: bool
    reason: str
    text_silent: bool


def signal(text: str | None) -> str | None:
    """The first thing in a text that an event's announcement would name, as said in the post's record ("palabra de
    evento «social»", "fecha", "hora"); None when it names nothing of one."""
    if not text or not text.strip():
        return None
    folded = fold(text)
    words = set(_WORD.findall(folded))
    for table, what in ((_EVENT_WORDS, "palabra de evento"), (_TIME_WORDS, "día u hora"), (_PLACE_WORDS, "lugar")):
        if found := sorted(words & table):
            return f"{what} «{found[0]}»"
    checks_found = (
        (checks.names_a_date(text), "fecha"),
        (bool(checks.times(text)), "hora"),
        (checks.names_a_price(text), "precio"),
    )
    for found_it, what in checks_found:
        if found_it:
            return what
    patterns = (
        (_PHRASES, "frase de invitación o fecha"),
        (_EMOJI, "emoji de fecha, lugar o precio"),
        (_LINK, "enlace"),
        (_ADDRESS, "dirección"),
        (_PHONE, "teléfono"),
    )
    for pattern, what in patterns:
        if match := pattern.search(folded):
            return f"{what} «{match.group(0)}»"
    for tag in _HASHTAG.findall(folded):
        if stem := next((stem for stem in _HASHTAG_STEMS if stem in tag), None):
            return f"hashtag «#{tag}» ({stem})"
    return None


def _letters(text: str) -> int:
    return sum(1 for char in text if char.isalpha())


def image_text(image: bytes) -> str | None:
    """An image's text by OCR (ocr.rows, joined by lines); None without OCR installed."""
    if not ocr.available():
        return None
    return "\n".join(ocr.rows(image))


def judge(caption: str | None, images: Sequence[bytes], read_text: ImageText | None = None) -> Verdict:
    """The pre-filter's verdict on a post: its caption, then its images (`read_text`: how an image's text is read,
    image_text unless given)."""
    read_text = read_text or image_text
    if found := signal(caption):
        return Verdict(False, f"el texto lo sugiere: {found}", text_silent=False)
    if len(images) > config.PREFILTER_MAX_IMAGES:
        return Verdict(False, f"texto sin señales; {len(images)} imágenes, más de las que revisa", text_silent=True)
    for number, image in enumerate(images, start=1):
        text = read_text(image)
        if text is None:
            return Verdict(False, "texto sin señales; imagen sin revisar (sin OCR)", text_silent=True)
        if found := signal(text):
            return Verdict(False, f"texto sin señales; la imagen {number} lo sugiere: {found}", text_silent=True)
        if any(char.isdigit() for char in text):  # a date or a time in a font OCR half reads ("Previa | 19")
            return Verdict(False, f"texto sin señales; la imagen {number} tiene números", text_silent=True)
        if (letters := _letters(text)) > config.PREFILTER_MAX_IMAGE_LETTERS:
            return Verdict(False, f"texto sin señales; la imagen {number} tiene texto ({letters} letras)", True)
    return Verdict(True, "ni el texto ni las imágenes dicen nada de un evento", text_silent=True)
