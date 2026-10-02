"""Text helpers shared by matching, normalization, ids and discovery."""

import unicodedata


def fold(text: str | None) -> str:
    """Lowercase, no accents, single spaces: 'Salsa  Caleña' → 'salsa calena'. For comparing, not showing."""
    decomposed = unicodedata.normalize("NFKD", (text or "").casefold())
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).split())
