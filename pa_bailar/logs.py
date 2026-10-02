"""Logging setup shared by the commands."""

import logging

_NOISY = ("httpx", "google_genai", "urllib3")  # libraries that log every HTTP request at INFO


def setup_logging() -> None:
    """Plain messages at INFO; third-party libraries only from WARNING."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)
