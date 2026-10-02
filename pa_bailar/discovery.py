"""Find dance academies in Bogotá among the accounts you follow on Instagram.

Input: your Instagram data export ("Followers and following"), HTML or JSON. It stays on your PC
(private/ is git-ignored). For each followed account:
  1. Instagram (Business Discovery): personal or private accounts are rejected → discarded, free.
  2. Local filter: only business accounts with a dance hint in their name, bio or recent captions go on.
  3. Gemini Flash-Lite classifies them: academy / venue / organizer / …, in Bogotá or not.
Results are cached in private/discovery.json, so the tool can stop and resume.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from .models import AccountClassification

DANCE_KEYWORDS = [
    "bail", "danc", "danz", "salsa", "bachat", "kizomba", "zouk", "mambo", "casino", "timba", "merengue",
    "tango", "swing", "champeta", "rumba", "son cubano", "academ", "escuela", "studio", "estudio",
    "ritmo", "latin", "sabor", "social", "salsoteca", "congres", "festival", "fest", "taller", "clase",
    "coreograf", "heels", "urban", "afro", "pista", "rueda",
]  # fmt: skip
RECOMMENDED_KINDS = {"academy", "venue", "organizer", "dance_company"}

CLASSIFY_PROMPT = """You help build a directory of dance academies and dance events in Bogotá, Colombia.
Classify this Instagram business account from its public profile and recent captions.

Username: @{username}
Name: {name}
Bio: \"\"\"{biography}\"\"\"
Website: {website}
Followers: {followers}
Recent captions:
{captions}

Be strict about Bogotá: "yes" only with evidence (Bogotá, BTA, a Bogotá neighborhood or address);
"no" when another city or country is stated; "unknown" otherwise."""


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def dance_score(*texts: str) -> int:
    """How many dance keywords appear in the texts (accent- and case-insensitive)."""
    plain = " ".join(_plain(text) for text in texts)
    return sum(1 for keyword in DANCE_KEYWORDS if keyword in plain)


# ---------- the export ----------


def parse_following(path: Path) -> list[str]:
    """Usernames you follow, from Instagram's data export (following.html or following.json)."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        entries = data.get("relationships_following", data) if isinstance(data, dict) else data
        usernames = []
        for entry in entries:
            values = [item.get("value") for item in entry.get("string_list_data", [])]
            usernames.append(entry.get("title") or next((value for value in values if value), None))
        found = [username for username in usernames if username]
    else:
        found = re.findall(r'href="https://www\.instagram\.com/(?:_u/)?([A-Za-z0-9._]+)/?"', text)
    return list(dict.fromkeys(found))  # unique, in export order


def by_likelihood(usernames: list[str]) -> list[str]:
    """Usernames with dance keywords first, so the useful results arrive early."""
    return sorted(usernames, key=lambda username: -dance_score(username))


# ---------- the cache ----------

Status = Literal["personal", "business"]


class DiscoveredAccount(BaseModel):
    username: str
    status: Status  # personal = Business Discovery can't see it (personal, private or missing)
    profile: dict[str, Any] | None = None
    dance_hint: int = 0  # dance keywords in name, bio and captions
    classification: AccountClassification | None = None
    classified_by: str | None = None


def load_cache(path: Path) -> dict[str, DiscoveredAccount]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {username: DiscoveredAccount.model_validate(item) for username, item in raw.items()}


def save_cache(path: Path, cache: dict[str, DiscoveredAccount]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {username: account.model_dump(mode="json") for username, account in cache.items()}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def profile_hint(profile: dict[str, Any]) -> int:
    captions = [item.get("caption") or "" for item in profile.get("media", {}).get("data", [])]
    return dance_score(
        profile.get("username", ""), profile.get("name") or "", profile.get("biography") or "", *captions
    )


def classify_prompt(profile: dict[str, Any]) -> str:
    captions = [
        f"- {(item.get('caption') or '').replace(chr(10), ' ')[:300]}"
        for item in profile.get("media", {}).get("data", [])
    ]
    return CLASSIFY_PROMPT.format(
        username=profile.get("username", ""),
        name=profile.get("name") or "",
        biography=profile.get("biography") or "",
        website=profile.get("website") or "",
        followers=profile.get("followers_count", "?"),
        captions="\n".join(captions) or "(none)",
    )


# ---------- the report ----------


@dataclass
class ReportRow:
    username: str
    kind: str
    in_bogota: str
    city: str
    styles: str
    announces_events: bool
    followers: int | str
    reason: str


def _row(account: DiscoveredAccount) -> ReportRow:
    c = account.classification
    assert c is not None
    return ReportRow(
        username=account.username,
        kind=c.kind,
        in_bogota=c.in_bogota,
        city=c.city or "",
        styles=", ".join(c.styles),
        announces_events=c.announces_events,
        followers=(account.profile or {}).get("followers_count", ""),
        reason=c.reason,
    )


def is_recommended(c: AccountClassification) -> bool:
    """Worth adding to accounts.txt: an academy, venue, organizer or company in (or likely in) Bogotá."""
    return c.kind in RECOMMENDED_KINDS and c.in_bogota != "no"


def report_sections(cache: dict[str, DiscoveredAccount], already_followed: set[str]) -> dict[str, list[ReportRow]]:
    classified = [a for a in cache.values() if a.classification and a.username not in already_followed]
    recommended = [a for a in classified if is_recommended(a.classification)]
    maybe = [
        a
        for a in classified
        if a not in recommended and a.classification.kind != "not_dance" and a.classification.in_bogota != "no"
    ]

    def order(accounts: list[DiscoveredAccount]) -> list[ReportRow]:
        rank = {"yes": 0, "unknown": 1, "no": 2}
        accounts = sorted(
            accounts,
            key=lambda a: (
                rank[a.classification.in_bogota],
                not a.classification.announces_events,
                -int((a.profile or {}).get("followers_count", 0) or 0),
            ),
        )
        return [_row(account) for account in accounts]

    return {"recommended": order(recommended), "maybe": order(maybe)}


def report_markdown(cache: dict[str, DiscoveredAccount], already_followed: set[str], total: int) -> str:
    sections = report_sections(cache, already_followed)
    personal = sum(1 for a in cache.values() if a.status == "personal")
    business = [a for a in cache.values() if a.status == "business"]
    no_hint = sum(1 for a in business if not a.dance_hint)
    pending_classify = sum(1 for a in business if a.dance_hint and not a.classification)

    def table(rows: list[ReportRow]) -> list[str]:
        lines = [
            "| Account | Type | Bogotá | Styles | Posts events | Followers | Why |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            lines.append(
                f"| [@{r.username}](https://www.instagram.com/{r.username}/) | {r.kind} | {r.in_bogota} "
                f"{('(' + r.city + ')') if r.city and r.in_bogota != 'yes' else ''} | {r.styles} | "
                f"{'yes' if r.announces_events else 'no'} | {r.followers} | {r.reason} |"
            )
        return lines

    return "\n".join(
        [
            "# Dance accounts you follow",
            "",
            f"{len(cache)} of {total} followed accounts checked · {personal} personal/private (skipped) · "
            f"{len(business)} business · {no_hint} with no dance hint (not classified) · "
            f"{pending_classify} waiting for classification.",
            "",
            f"## Recommended ({len(sections['recommended'])})",
            "Academies, venues, organizers and companies in Bogotá (or with no city stated).",
            "",
            *table(sections["recommended"]),
            "",
            f"## Maybe ({len(sections['maybe'])})",
            "Dance-related but not an obvious source of events (teachers, shops, media…).",
            "",
            *table(sections["maybe"]),
            "",
        ]
    )
