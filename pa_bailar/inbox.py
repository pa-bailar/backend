"""The admin inbox: what an issue or a comment in this repository asks for (docs/ADMIN.md). No AI: fixed patterns.

Understood, in the issue form's fields (the form, the admin page), or as plain text in an issue or a comment:
  - a post link alone: "Revisar" (why its event is or isn't on the site);
  - /agregar and a post link: "Agregar" (publish it); /releer and a post link: "Volver a leer" (read it again
    with Gemini even if it was read before and hasn't changed);
  - /cuenta and an @account: add it to the sweeps;
  - /estado: how the sweeps, quotas and accounts are doing;
  - /historia and the ids of story screenshots uploaded from the admin page (then optionally an @account and
    notes): "Agregar historia" (publish the story's events); /ocultar and a story's id (story-…): take it off the
    site again. The admin page writes these as the form's fields (Acción, Capturas, Cuenta, Notas; Historia);
  - /ocultar and an event's id (its link's last part, e.g. programa-intensivo-8-nov): take that event off the site,
    whatever it came from ("Ocultar", the admin page's new series list; form fields Acción and Evento).
In plain text a command is a word starting with "/" at the start of a line: ordinary words never are ("revisar
el estado de…", "agrega esto", "volver a leer"), since some commands spend Gemini or change accounts.txt.
Anything else gets the list of what's understood, but only in the admin's inbox: an issue labelled `admin`
(the form, the admin page) or a text that asks for something (`is_request`). Other issues are left alone.
"""

import re
from dataclasses import dataclass
from typing import Literal

from . import links

Action = Literal["why", "add-post", "add-account", "status", "add-story", "hide-story", "hide-event", "help"]

# The issue form (.github/ISSUE_TEMPLATE/admin.yml) and the admin page write "### Field\n\nvalue".
_FIELD = re.compile(r"^###\s*(?P<name>[^\n]+)\n+(?P<value>.*?)(?=\n###|\Z)", re.MULTILINE | re.DOTALL)
_LINK = re.compile(r"https?://(?:www\.|m\.)?instagram\.com/\S+", re.IGNORECASE)
_HANDLE = re.compile(r"(?<![\w/])@([A-Za-z0-9._]{1,30})")
_UPLOAD_ID = re.compile(r"\b[0-9a-f]{32}\b")  # a screenshot the admin page uploaded (admin-web/src/index.js)
_STORY_ID = re.compile(r"\bstory-[0-9a-f]{16}\b")
# An event's id (ids.py): lowercase words joined by hyphens, like the site's check-data.mjs.
EVENT_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
EVENT_ID_MAX = 120
MAX_SCREENSHOTS = 4
NOTES_MAX = 500
# The form's "Acción" values (and the admin page's, which writes the same body).
_ACTIONS: dict[str, Action] = {
    "revisar": "why",
    "agregar": "add-post",
    "volver a leer": "add-post",  # with `again`
    "agregar cuenta": "add-account",
    "estado": "status",
    "agregar historia": "add-story",
    "ocultar historia": "hide-story",
    "ocultar evento": "hide-event",
}
# Commands in plain text: "/word" at the start of a line (after spaces at most), any case. A quoted line
# ("> /agregar …") isn't one, nor "/agregarlo".
_COMMAND = re.compile(
    r"^[ \t]*/(?P<name>agregar-cuenta|agregar|releer|cuenta|estado|historia|ocultar)(?![\w-])(?P<rest>.*)$",
    re.IGNORECASE | re.MULTILINE,
)

HELP = """Puedo hacer esto (escribe en un issue nuevo o en un comentario; los comandos van al comienzo de una
línea):

- **Revisar** una publicación: pega su enlace de Instagram. Te digo si su evento está en el sitio, y si no, por qué.
- **Agregar** una publicación: `/agregar` y el enlace (y la @cuenta si el enlace no la trae). La leo y publico
  su evento.
- **Volver a leer** una publicación ya leída (por ejemplo, si su evento quedó con datos equivocados): `/releer`
  y el enlace. La leo otra vez aunque no haya cambiado.
- **Agregar una cuenta** a los barridos: `/cuenta @academia`.
- **Estado** de los barridos, Gemini e Instagram: `/estado`.
- **Agregar una historia:** desde la página de administración (comparte las capturas de la historia con PB Admin,
  o elígelas ahí). Aquí: `/historia` y los códigos de las capturas que la página subió (y la @cuenta, y notas).
- **Ocultar una historia** que se publicó: `/ocultar story-…` (el código está en la respuesta).
- **Ocultar un evento** del sitio (venga de publicaciones o de historias): `/ocultar` y su código, la última parte
  de su enlace (`/ocultar programa-intensivo-8-nov`). Los barridos no lo vuelven a publicar.
"""


@dataclass(frozen=True)
class Request:
    action: Action
    link: str | None = None
    account: str | None = None
    again: bool = False  # add-post: read it again even if it was read before and hasn't changed ("Volver a leer")
    images: tuple[str, ...] = ()  # add-story: the uploaded screenshots' ids
    notes: str | None = None  # add-story: the admin's notes (hints for Gemini, never published), one line
    story: str | None = None  # hide-story: "story-<hash>"
    event: str | None = None  # hide-event: the event's id


def _clean(value: str) -> str:
    """A field's value: its first paragraph (the fields are one line; the admin page's closing note
    "_Desde la página de administración._" follows the last one after a blank line)."""
    value = value.strip().split("\n\n", 1)[0].strip()
    return "" if value in ("_No response_", "None") else value


def _first_link(text: str) -> str | None:
    """The first Instagram link in the text (a post's or a profile's), without what follows it."""
    match = _LINK.search(text)
    link = match.group(0).rstrip(").,>") if match else None
    return link if link and (links.post_code(link) or links.account_name(link)) else None


def _one_line(text: str | None) -> str | None:
    """Notes on one line, at most NOTES_MAX characters (they travel as a workflow input)."""
    cleaned = " ".join((text or "").split())[:NOTES_MAX]
    return cleaned or None


def _uploads(text: str) -> tuple[str, ...]:
    """The uploaded screenshots' ids in a text, once each, at most MAX_SCREENSHOTS."""
    return tuple(dict.fromkeys(_UPLOAD_ID.findall(text)))[:MAX_SCREENSHOTS]


def _event_id(text: str) -> str | None:
    """An event's id: the text's first word, if it is one (the event's link works too: its last part)."""
    word = (text.strip().split() or [""])[0].rstrip("/").rsplit("/", 1)[-1]
    return word if EVENT_ID.fullmatch(word) and len(word) <= EVENT_ID_MAX else None


def _hide_event(text: str) -> Request:
    event = _event_id(text)
    return Request("hide-event", event=event) if event else Request("help")


def _story_request(fields: dict[str, str], chosen: str) -> Request:
    """ "Agregar historia" or "Ocultar historia" from the form's fields (the admin page writes them)."""
    if chosen == "ocultar historia":
        story = _STORY_ID.search(fields.get("historia") or "")
        return Request("hide-story", story=story.group(0)) if story else Request("help")
    images = _uploads(fields.get("capturas") or "")
    if not images:
        return Request("help")
    # Only the Cuenta field: an @ in the notes (a teacher, a venue) isn't the story's account.
    account = links.account_name(fields["cuenta"]) if fields.get("cuenta") else None
    return Request("add-story", account=account, images=images, notes=_one_line(fields.get("notas")))


def _story_command(text: str) -> Request | None:
    """ "/historia <ids> [@cuenta] [notas]" or "/ocultar story-…", on one line; None without either."""
    for match in _COMMAND.finditer(text):
        name, rest = match.group("name").lower(), match.group("rest")
        if name == "ocultar":
            story = _STORY_ID.search(rest)
            return Request("hide-story", story=story.group(0)) if story else _hide_event(rest)
        if name == "historia":
            images = _uploads(rest)
            if not images:
                return Request("help")
            handle = _HANDLE.search(rest)
            notes = _HANDLE.sub(" ", _UPLOAD_ID.sub(" ", rest), count=1)
            return Request(
                "add-story", account=handle.group(1).lower() if handle else None, images=images, notes=_one_line(notes)
            )
    return None


def _commands(text: str) -> set[str]:
    """The commands in a text ("agregar", "releer"…), lowercase."""
    return {match.group("name").lower() for match in _COMMAND.finditer(text)}


def parse(text: str) -> Request:
    fields = {m.group("name").strip().lower(): _clean(m.group("value")) for m in _FIELD.finditer(text)}
    link = _first_link(text)
    post = link if link and links.post_code(link) else None

    account = None
    if fields.get("cuenta"):
        account = links.account_name(fields["cuenta"])
    if account is None:
        handle = _HANDLE.search(_LINK.sub(" ", text))
        account = handle.group(1).lower() if handle else None

    if "acción" in fields or "accion" in fields:
        chosen = (fields.get("acción") or fields.get("accion") or "").lower()
        action = _ACTIONS.get(chosen, "help")
        if action in ("add-story", "hide-story"):
            return _story_request(fields, chosen)
        if action == "hide-event":
            return _hide_event(fields.get("evento") or "")
        field_link = _first_link(fields.get("enlace") or "")
        post = field_link or post  # the link alone, never what follows it
        if action in ("why", "add-post") and not (post and links.post_code(post)):
            return Request("help")
        if action == "add-account" and not account:
            return Request("help")
        return Request(action, post if action in ("why", "add-post") else None, account, chosen == "volver a leer")

    story = _story_command(text)
    if story:
        return story
    commands = _commands(text)
    if post and "releer" in commands:
        return Request("add-post", post, account, again=True)
    if post and "agregar" in commands:
        return Request("add-post", post, account)
    if commands & {"cuenta", "agregar-cuenta"}:
        if account is None and link:
            account = links.account_name(link)  # a profile link
        return Request("add-account", account=account) if account else Request("help")
    if "estado" in commands:
        return Request("status")
    if post:
        return Request("why", post, account)
    return Request("help")


def is_request(text: str) -> bool:
    """Whether a text asks the admin tools for something: a request they understand, or a command (one missing
    its link gets the list of what's understood)."""
    return parse(text).action != "help" or bool(_commands(text))
