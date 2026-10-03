"""The admin inbox: what an issue or a comment in this repository asks for (docs/ADMIN.md). No AI: fixed patterns.

Understood (in the issue form's fields, or as plain text in an issue or a comment):
  - a post link: "Revisar" (why its event is or isn't on the site), or "Agregar" (publish it)
  - "Agregar cuenta" with an @account: add it to the sweeps
  - "Estado" or /estado: how the sweeps, quotas and accounts are doing
Anything else gets the list of what's understood.
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
_ACTIONS: dict[str, Action] = {
    "revisar": "why",
    "agregar": "add-post",
    "agregar cuenta": "add-account",
    "estado": "status",
}

HELP = """Puedo hacer esto (escribe en un issue nuevo o en un comentario):

- **Revisar** una publicación: pega su enlace de Instagram. Te digo si su evento está en el sitio, y si no, por qué.
- **Agregar** una publicación: `/agregar` y el enlace (y la @cuenta si el enlace no la trae). La leo y publico
  su evento.
- **Agregar una cuenta** a los barridos: `/cuenta @academia`.
- **Estado** de los barridos, Gemini e Instagram: `/estado`.
"""


@dataclass(frozen=True)
class Request:
    action: Action
    link: str | None = None
    account: str | None = None


def _clean(value: str) -> str:
    value = value.strip()
    return "" if value in ("_No response_", "None") else value


def parse(text: str) -> Request:
    fields = {m.group("name").strip().lower(): _clean(m.group("value")) for m in _FIELD.finditer(text)}
    link_match = _LINK.search(text)
    link = link_match.group(0).rstrip(").,>") if link_match else None
    if link and not links.post_code(link) and not links.account_name(link):
        link = None

    account = None
    if fields.get("cuenta"):
        account = links.account_name(fields["cuenta"])
    if account is None:
        handle = _HANDLE.search(_LINK.sub(" ", text))
        account = handle.group(1).lower() if handle else None

    if "acción" in fields or "accion" in fields:
        action = _ACTIONS.get((fields.get("acción") or fields.get("accion") or "").lower(), "help")
        field_link = _LINK.search(fields.get("enlace") or "")
        post = field_link.group(0) if field_link else link  # the link alone, never what follows it
        if action in ("why", "add-post") and not (post and links.post_code(post)):
            return Request("help")
        if action == "add-account" and not account:
            return Request("help")
        return Request(action, post if action in ("why", "add-post") else None, account)

    lowered = text.lower()
    if re.search(r"(^|\s)/?estado\b", lowered) and not link:
        return Request("status")
    if re.search(r"(^|\s)/(cuenta|agregar-cuenta)\b|agregar (la )?cuenta", lowered):
        if account is None and link:
            account = links.account_name(link)
        return Request("add-account", account=account) if account else Request("help")
    if link and links.post_code(link):
        # "agregar", "agrega", "agrégalo", "publica", "publícalo"…
        action = "add-post" if re.search(r"(^|\s)/?agr[eé]g|\bpubl[ií]c", lowered) else "why"
        return Request(action, link, account)
    return Request("help")
