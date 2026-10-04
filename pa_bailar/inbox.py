"""The admin inbox: what an issue or a comment in this repository asks for (docs/ADMIN.md). No AI: fixed patterns.

Understood, in the issue form's fields (the form, the admin page), or as plain text in an issue or a comment:
  - a post link alone: "Revisar" (why its event is or isn't on the site);
  - /agregar and a post link: "Agregar" (publish it); /releer and a post link: "Volver a leer" (read it again
    with Gemini even if it was read before and hasn't changed);
  - /cuenta and an @account: add it to the sweeps;
  - /estado: how the sweeps, quotas and accounts are doing.
In plain text a command is a word starting with "/" at the start of a line: ordinary words never are ("revisar
el estado de…", "agrega esto", "volver a leer"), since some commands spend Gemini or change accounts.txt.
Anything else gets the list of what's understood, but only in the admin's inbox: an issue labelled `admin`
(the form, the admin page) or a text that asks for something (`is_request`). Other issues are left alone.
"""

import re
from dataclasses import dataclass
from typing import Literal

from . import links

Action = Literal["why", "add-post", "add-account", "status", "help"]

# The issue form (.github/ISSUE_TEMPLATE/admin.yml) and the admin page write "### Field\n\nvalue".
_FIELD = re.compile(r"^###\s*(?P<name>[^\n]+)\n+(?P<value>.*?)(?=\n###|\Z)", re.MULTILINE | re.DOTALL)
_LINK = re.compile(r"https?://(?:www\.|m\.)?instagram\.com/\S+", re.IGNORECASE)
_HANDLE = re.compile(r"(?<![\w/])@([A-Za-z0-9._]{1,30})")
# The form's "Acción" values (and the admin page's, which writes the same body).
_ACTIONS: dict[str, Action] = {
    "revisar": "why",
    "agregar": "add-post",
    "volver a leer": "add-post",  # with `again`
    "agregar cuenta": "add-account",
    "estado": "status",
}
# Commands in plain text: "/word" at the start of a line (after spaces at most), any case. A quoted line
# ("> /agregar …") isn't one, nor "/agregarlo".
_COMMAND = re.compile(
    r"^[ \t]*/(?P<name>agregar-cuenta|agregar|releer|cuenta|estado)(?![\w-])", re.IGNORECASE | re.MULTILINE
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
"""


@dataclass(frozen=True)
class Request:
    action: Action
    link: str | None = None
    account: str | None = None
    again: bool = False  # add-post: read it again even if it was read before and hasn't changed ("Volver a leer")


def _clean(value: str) -> str:
    value = value.strip()
    return "" if value in ("_No response_", "None") else value


def _first_link(text: str) -> str | None:
    """The first Instagram link in the text (a post's or a profile's), without what follows it."""
    match = _LINK.search(text)
    link = match.group(0).rstrip(").,>") if match else None
    return link if link and (links.post_code(link) or links.account_name(link)) else None


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
        field_link = _first_link(fields.get("enlace") or "")
        post = field_link or post  # the link alone, never what follows it
        if action in ("why", "add-post") and not (post and links.post_code(post)):
            return Request("help")
        if action == "add-account" and not account:
            return Request("help")
        return Request(action, post if action in ("why", "add-post") else None, account, chosen == "volver a leer")

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
