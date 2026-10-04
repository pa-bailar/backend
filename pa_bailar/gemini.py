"""Gemini calls within the free quotas.

`ModelPool` calls models in a preferred order, spaces calls per model (requests per minute), stops using a
model when its daily budget is spent, and persists the day's usage so several runs on the same day share
it. Errors: `ExtractionError` (no model could answer now: retry later), `QuotaExhaustedError` (its kind for
when every model is out of today's quota or not offered to this key: nothing failed, the post just waits) and
`RejectedRequestError` (Gemini refused the request itself, or blocked its answer: retrying won't help).
`GeminiKeyError` is apart: the API key itself doesn't work (invalid, expired, revoked), so nothing can be
read until it's replaced. It isn't an `ExtractionError`, so no post is marked as rejected because of it.

A timeout or a dropped connection (httpx's `TransportError`, raised as is by the SDK) is retried like a busy
server (5xx).

A model Gemini says isn't available to this key (404 or 403, e.g. if Google took it out of the free tier) is
skipped for the rest of the day like a spent one, and listed in `unavailable` for the health checks.
"""

import logging
import time
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
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


class QuotaExhaustedError(ExtractionError):
    """Every model asked for is out of today's quota or not available to this key: nothing failed, the work
    waits for a later run."""


class RejectedRequestError(ExtractionError):
    """Gemini refused this request itself (e.g. an image it can't read): retrying won't help."""


class GeminiKeyError(Exception):
    """The API key doesn't work (invalid, expired or revoked): every request fails until it's replaced."""


# Why an answer can come back empty on purpose: retrying the same post gives the same block.
_BLOCKED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY", "RECITATION"}


def quota_day() -> str:
    """Gemini daily quotas reset at midnight Pacific time."""
    return datetime.now(ZoneInfo(config.QUOTA_TIMEZONE)).date().isoformat()


def quota_reset(now: datetime) -> datetime:
    """When Gemini's daily quotas reset next (midnight Pacific), in Bogotá time."""
    pacific = now.astimezone(ZoneInfo(config.QUOTA_TIMEZONE))
    midnight = datetime.combine(pacific.date() + timedelta(days=1), datetime.min.time(), pacific.tzinfo)
    return midnight.astimezone(config.BOGOTA_TZ)


def daily_budget(model: str) -> int:
    limit = config.MODEL_LIMITS[model]
    return max(0, limit.requests_per_day - config.DAILY_BUDGET_MARGIN)


def _is_key_error(error: errors.ClientError) -> bool:
    """Gemini answers an invalid, expired or revoked key with 400 (API_KEY_INVALID) or 401/403."""
    text = str(error).lower()
    return error.code == 401 or (
        error.code in (400, 403)
        and any(sign in text for sign in ("api_key_invalid", "api key not valid", "api key expired"))
    )


def _blocked(response: types.GenerateContentResponse) -> str | None:
    """Why Gemini blocked this answer (a safety filter…), if it did."""
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None and feedback.block_reason:
        return str(getattr(feedback.block_reason, "name", feedback.block_reason))
    for candidate in getattr(response, "candidates", None) or []:
        reason = getattr(candidate.finish_reason, "name", None)
        if reason in _BLOCKED:
            return str(reason)
    return None


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
        self._day = quota_day()
        usage = storage.load_gemini_usage()
        self._used: Counter[str] = Counter(usage.get("requests", {}) if usage.get("day") == self._day else {})
        self._last_call: dict[str, float] = {}
        self.requests_this_run: Counter[str] = Counter()
        self.unavailable: set[str] = set()  # models Gemini said this key can't use (this run)

    def used(self, model: str) -> int:
        """Requests to `model` counted today (this pool's usage file)."""
        return self._used[model]

    def has_budget(self, model: str) -> bool:
        return self._used[model] < daily_budget(model)

    def any_budget(self, models: tuple[str, ...]) -> bool:
        return any(self.has_budget(model) for model in models)

    def _spend(self, model: str) -> None:
        self._used[model] += 1
        self.requests_this_run[model] += 1
        self._persist()

    def _exhaust(self, model: str) -> None:
        self._used[model] = max(self._used[model], daily_budget(model))
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
        failed = False  # a model was tried and failed (busy, bad answer), as opposed to all out of quota
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
                    if reason := _blocked(response):
                        raise RejectedRequestError(f"{model} blocked the answer ({reason})")
                    log.info("    %s returned no valid JSON, retrying", model)
                    failed = True
                except (errors.ServerError, httpx.TransportError) as error:
                    # Busy (5xx), or the network: a timeout or a dropped connection, which the SDK raises as
                    # httpx's own errors (neither an APIError nor an OSError).
                    code = error.code if isinstance(error, errors.ServerError) else type(error).__name__
                    log.info("    %s busy (%s), retrying", model, code)
                    failed = True
                    if attempt < ATTEMPTS_PER_MODEL:
                        time.sleep(SERVER_ERROR_BACKOFF_SECONDS * attempt)
                except errors.ClientError as error:
                    if _is_key_error(error):
                        raise GeminiKeyError(str(error)) from error
                    if error.code in (403, 404):  # not available to this key (e.g. no longer in the free tier)
                        log.warning("    %s is not available to this API key (%s)", model, error.code)
                        self.unavailable.add(model)
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
        if not failed:
            raise QuotaExhaustedError(f"no quota left today ({', '.join(models) or 'no model'})")
        raise ExtractionError(f"no model could answer ({', '.join(models)})")
