"""The text on a flyer, by OCR, in rows as laid out: RapidOCR (PaddleOCR's models on ONNX, on the CPU, ~0.5 s an
image). A lighter model reads text about as well as Flash but assigns it worse (a calendar cell's act given to every
night: @elgocepagano, 5 Oct 2026); rows keep together what's printed together ("10 | Acere"). It misreads stylized
digits and script fonts, so it goes with the image, never instead of it (prompts.OCR_NOTE), and the checks look for
dates and times in it (checks.py). Optional: without `rapidocr` installed, there's no OCR text (available())."""

from collections.abc import Sequence
from functools import cache
from typing import Any

from . import config

Box = Sequence[Sequence[float]]  # four corners (x, y), as RapidOCR gives them


def available() -> bool:
    try:
        import rapidocr  # noqa: F401
    except ImportError:
        return False
    return True


@cache
def _engine() -> Any:
    from rapidocr import RapidOCR

    return RapidOCR()


def rows(image: bytes) -> list[str]:
    """The image's text, one row per line of print, its pieces left to right joined with " | "."""
    result = _engine()(image)
    if result.boxes is None:
        return []
    return group_rows(list(zip(result.boxes, result.txts, result.scores, strict=True)))


def group_rows(found: list[tuple[Box, str, float]]) -> list[str]:
    """Pieces of text into rows: pieces whose vertical middles are within OCR_ROW_OVERLAP of a line's height of the
    row's first piece share its row. Pieces read with a confidence under OCR_MIN_SCORE are left out (stray marks on
    a photo read as letters)."""
    pieces = []
    for box, text, score in found:
        if score < config.OCR_MIN_SCORE or not text.strip():
            continue
        ys = [point[1] for point in box]
        pieces.append((sum(ys) / len(ys), min(point[0] for point in box), max(ys) - min(ys), text.strip()))
    pieces.sort()
    grouped: list[list[tuple[float, float, float, str]]] = []
    for piece in pieces:
        first = grouped[-1][0] if grouped else None
        if first and abs(piece[0] - first[0]) < config.OCR_ROW_OVERLAP * max(piece[2], first[2]):
            grouped[-1].append(piece)
        else:
            grouped.append([piece])
    return [" | ".join(text for _, _, _, text in sorted(row, key=lambda piece: piece[1])) for row in grouped]
