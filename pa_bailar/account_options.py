"""What accounts.txt says about an account besides its name: whether it's a bar, and which styles to look for.

A line is the username, then optional words (docs/ARCHITECTURE.md, section 6.1):

    galeriacafelibro        bar                      # what it is, for whoever reads the list
    ritmomoderno            bar solo:salsa,bachata

- `bar`: a bar or club, open every week. Its regular nights aren't events: the prompts ask for its special
  occasions only (prompts.BAR_RULES), its events carry `bar: true` (the site can hide them), and its first sweep
  isn't deeper than the regular one (its old posts are past nights).
- `solo:<styles>`: a general bar or club that also holds salsa or bachata nights: only those count. A post whose
  caption names none of those styles is left out before any Gemini request (`mentions_focus`, free), and the
  prompts ask for those styles only (prompts.FOCUS_RULES).
"""

from dataclasses import dataclass

from .text import fold

# The words a caption uses for each style a `solo:` account can be limited to (accents and case ignored).
FOCUS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "salsa": ("salsa", "salser", "timba", "casino", "son cubano", "pachanga", "boogaloo", "mambo"),
    "bachata": ("bachat",),
    "merengue": ("merengue",),
    "kizomba": ("kizomba", "semba", "urban kiz"),
    "tango": ("tango", "milonga"),
}


@dataclass(frozen=True)
class AccountOptions:
    bar: bool = False
    focus: tuple[str, ...] = ()  # only events of these styles (keys of FOCUS_KEYWORDS); empty: every style


def parse_line(line: str) -> tuple[str, AccountOptions] | None:
    """One accounts.txt line → (username, options); None for blank lines and comments ("#" to the end of the line,
    also after an account). Unknown words fail loudly, so a typo can't silently sweep an account without its limits."""
    words = line.split("#", 1)[0].split()
    if not words:
        return None
    username, bar = words[0].lstrip("@"), False
    focus: tuple[str, ...] = ()
    for word in words[1:]:
        if word == "bar":
            bar = True
        elif word.startswith("solo:"):
            focus = tuple(style for style in word.removeprefix("solo:").split(",") if style)
            unknown = [style for style in focus if style not in FOCUS_KEYWORDS]
            if unknown or not focus:
                raise ValueError(f"accounts.txt, @{username}: unknown style in {word!r} ({', '.join(FOCUS_KEYWORDS)})")
        else:
            raise ValueError(f"accounts.txt, @{username}: unknown word {word!r} (expected `bar` or `solo:<styles>`)")
    return username, AccountOptions(bar=bar, focus=focus)


def mentions_focus(caption: str | None, focus: tuple[str, ...]) -> bool:
    """Whether a caption names one of the account's styles (always true without a focus)."""
    if not focus:
        return True
    text = fold(caption)
    return any(keyword in text for style in focus for keyword in FOCUS_KEYWORDS[style])
