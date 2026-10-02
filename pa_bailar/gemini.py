"""Gemini calls within the free quotas.

`ModelPool` calls models in a preferred order, spaces calls per model (requests per minute), stops using a
model when its daily budget is spent, and persists the day's usage so several runs on the same day share
it. Errors: `ExtractionError` (no model could answer now: retry later) and `RejectedRequestError` (Gemini
refused the request itself: retrying won't help).
"""

import logging
import time
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from . import config, storage

log = logging.getLogger(__name__)

ATTEMPTS_PER_MODEL = 3
SERVER_ERROR_BACKOFF_SECONDS = 5  # multiplied by the attempt number
RATE_LIMIT_WAIT_SECONDS = 60  # per-minute quotas reset within a minute


class ExtractionError(RuntimeError):
    """No Gemini model could answer (all out of quota, unavailable or failing). Worth retrying later."""


class RejectedRequestError(ExtractionError):
    """Gemini refused this request itself (e.g. an image it can't read): retrying won't help."""


def _quota_day() -> str:
    """Gemini daily quotas reset at midnight Pacific time."""
    return datetime.now(ZoneInfo(config.QUOTA_TIMEZONE)).date().isoformat()


def _daily_budget(model: str) -> int:
    limit = config.MODEL_LIMITS[model]
    return max(0, limit.requests_per_day - config.DAILY_BUDGET_MARGIN)


def _is_daily_quota_error(error: errors.ClientError) -> bool:
    text = str(error).lower()
    return "per day" in text or "perday" in text or "daily" in text


class ModelPool:
    """Calls Gemini models in a preferred order while respecting each one's quotas."""

    def __init__(self, api_key: str, client: genai.Client | None = None):
        """`client` is for tests; by default a Gemini client with a request timeout."""
        self._client = client or genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=config.GEMINI_TIMEOUT_SECONDS * 1000)
        )
        self._day = _quota_day()
        usage = storage.load_gemini_usage()
        self._used: Counter[str] = Counter(usage.get("requests", {}) if usage.get("day") == self._day else {})
        self._last_call: dict[str, float] = {}
        self.requests_this_run: Counter[str] = Counter()

    def has_budget(self, model: str) -> bool:
        return self._used[model] < _daily_budget(model)

    def any_budget(self, models: tuple[str, ...]) -> bool:
        return any(self.has_budget(model) for model in models)

    def _spend(self, model: str) -> None:
        self._used[model] += 1
        self.requests_this_run[model] += 1
        self._persist()

    def _exhaust(self, model: str) -> None:
        self._used[model] = max(self._used[model], _daily_budget(model))
        self._persist()

    def _persist(self) -> None:
        """Save today's usage, so later runs on the same quota day share the budget."""
        storage.save_gemini_usage({"day": self._day, "requests": dict(self._used)})

    def _pace(self, model: str) -> None:
        interval = 60 / config.MODEL_LIMITS[model].requests_per_minute + config.PACING_MARGIN_SECONDS
        wait = interval - (time.monotonic() - self._last_call.get(model, 0.0))
        if wait > 0:
            time.sleep(wait)
        self._last_call[model] = time.monotonic()

    def generate[T: BaseModel](
        self,
        models: tuple[str, ...],
        contents: types.ContentListUnionDict,
        schema: type[T],
        thinking: types.ThinkingLevel | None = None,
    ) -> tuple[T, str]:
        """The parsed answer of the first model in `models` that can give one, and that model's name.

        `thinking` lowers how much the model reasons before answering (faster, fewer tokens) for simple
        decisions; None keeps the model's default. Temperature stays at the default, as Google advises for
        Gemini 3 models.
        """
        generation_config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            thinking_config=types.ThinkingConfig(thinking_level=thinking) if thinking else None,
            # We pass no tools; disabling this also silences the SDK's warning about it.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        for model in models:
            for attempt in range(1, ATTEMPTS_PER_MODEL + 1):
                if not self.has_budget(model):
                    log.info("    %s: daily budget used up, skipping", model)
                    break
                self._pace(model)
                self._spend(model)
                try:
                    response = self._client.models.generate_content(
                        model=model, contents=contents, config=generation_config
                    )
                    if isinstance(response.parsed, schema):
                        return response.parsed, model
                    log.info("    %s returned no valid JSON, retrying", model)
                except errors.ServerError as error:
                    log.info("    %s busy (%s), retrying", model, error.code)
                    if attempt < ATTEMPTS_PER_MODEL:
                        time.sleep(SERVER_ERROR_BACKOFF_SECONDS * attempt)
                except errors.ClientError as error:
                    if error.code == 404:  # model not available to this key
                        log.warning("    %s is not available to this API key", model)
                        self._exhaust(model)
                        break
                    if error.code == 429 and (attempt > 1 or _is_daily_quota_error(error)):
                        log.info("    %s daily quota used up, trying the next model", model)
                        self._exhaust(model)
                        break
                    if error.code == 429:
                        log.info("    %s per-minute limit, waiting %ss", model, RATE_LIMIT_WAIT_SECONDS)
                        time.sleep(RATE_LIMIT_WAIT_SECONDS)
                        continue
                    # Any other 4xx is about the request itself (e.g. an unreadable image): permanent.
                    raise RejectedRequestError(f"{model} rejected the request: {error}") from error
        raise ExtractionError(f"no model could answer ({', '.join(models)})")
