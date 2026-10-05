"""The last resort: models outside Gemini, on OpenAI-compatible chat APIs (config.EXTERNAL_PROVIDERS: Groq, then
OpenRouter), used only when Gemini is out of quota for a step (extraction.py).

`ExternalTier.generate(contents, schema)` takes what `gemini.ModelPool.generate` takes (the prompt's text and images,
a Pydantic schema) and returns the same: the parsed answer and the model that gave it, recorded as
"<provider>:<model>" ("groq:qwen/qwen3.8-27b"). It fails fast, so a run never waits on it:
  - providers in order, each only with its key set; within one, its models in order. One request per model and
    post, a short timeout, no retries: a busy answer (a provider's 429, a 5xx, a timeout) or one that isn't the
    schema's JSON goes on to the next model, and when none answers, the post waits for the next run;
  - OpenRouter's routing: one request names the models of the same output mode (`models`), and OpenRouter tries
    them in order itself. Structured models get the schema as `response_format` (strict) and
    `provider.require_parameters`, so only providers honoring it serve them; the others get JSON mode and the schema
    in the prompt. Every answer is checked against the Pydantic schema;
  - each provider's limits: requests per minute (short pauses), a daily budget of requests (and of tokens, for
    Groq) under the free limits, shared by the day's runs (state/external_usage.json, saved with the sweep state; the
    day is UTC's), and for Groq its tokens per minute: each request's tokens are estimated (its text / 4, 2,048 per
    image, an answer) and kept in a one-minute window. When the window is full for longer than
    EXTERNAL_MAX_WAIT_SECONDS, the provider is skipped for that post. Groq takes at most 3 images: the first ones,
    as many as its per-minute tokens allow;
  - per run: a model that fails twice (busy, a timeout, invalid JSON) is set aside for the rest of the run, and a
    provider that refuses the key (401), wants credit (402) or blocks the request (403) is turned off for the run,
    each with one warning. `outcomes` counts what each model did, for the run's statistics and the health checks.
"""

import base64
import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from google.genai import types
from pydantic import BaseModel, ValidationError

from . import config, storage
from .config import ExternalModel, ExternalProvider
from .gemini import ExtractionError, QuotaExhaustedError

log = logging.getLogger(__name__)

SCHEMA_INSTRUCTION = "\n\nAnswer with only a JSON object (no other text) following this JSON schema:\n"
REFUSALS = {401: "the key was refused", 402: "the account needs credit", 403: "the request was blocked"}
FAILURES = ("busy", "invalid", "unavailable")  # count toward setting a model aside for the run
MAX_ROUTED_MODELS = 3  # OpenRouter's `models` takes at most 3
_THINKING = re.compile(r"<think>.*?</think>", re.DOTALL)  # some models think out loud before the JSON
_IMAGE_LABEL = re.compile(r"^(Image|Screenshot) \d+:$")  # extraction.py's label before each image
_DAILY_LIMIT = ("per day", "per-day", "(rpd)", "(tpd)")  # a 429 for the provider's own daily limit


def usage_day(now: datetime | None = None) -> str:
    """The providers' free daily limits reset at midnight UTC."""
    return (now or datetime.now(UTC)).astimezone(UTC).date().isoformat()


def usage_reset(now: datetime) -> datetime:
    """When the providers' daily limits reset next (midnight UTC), in Bogotá time."""
    midnight = datetime.combine(now.astimezone(UTC).date() + timedelta(days=1), datetime.min.time(), UTC)
    return midnight.astimezone(config.BOGOTA_TZ)


def recorded_name(provider: str, model: str) -> str:
    """The model as a post's record names it: "openrouter:qwen/qwen3.8-27b:free"."""
    return f"{provider}:{model}"


def is_external(model: str | None) -> bool:
    return bool(model) and any(str(model).startswith(f"{p.name}:") for p in config.EXTERNAL_PROVIDERS)


@dataclass(frozen=True)
class Unit:
    """One request: a provider and the model(s) it names (several only with OpenRouter's routing)."""

    provider: ExternalProvider
    models: tuple[ExternalModel, ...]

    @property
    def label(self) -> str:
        return recorded_name(self.provider.name, "|".join(model.name for model in self.models))

    @property
    def structured(self) -> bool:
        return self.models[0].structured


def units(provider: ExternalProvider) -> list[Unit]:
    """The requests a provider is asked in, in order: one per model, or with routing one per output mode."""
    if not provider.routing:
        return [Unit(provider, (model,)) for model in provider.models]
    by_mode: dict[bool, list[ExternalModel]] = {}
    for model in provider.models:
        by_mode.setdefault(model.structured, []).append(model)
    return [Unit(provider, tuple(models[:MAX_ROUTED_MODELS])) for models in by_mode.values()]


class NoAnswerError(Exception):
    """A request gave no answer. `kind`: busy, invalid (not the schema's JSON), unavailable (404: the model is gone or
    no longer free), skipped (its limits: not tried), refused (401, 402, 403: the provider is off for the run) or
    spent (its daily limit)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def parse_answer[T: BaseModel](text: str | None, schema: type[T]) -> T:
    """The schema's object from a model's answer: plain JSON, in a ```json fence, after its thinking or with words
    around it. Raises NoAnswerError("invalid") when there's no valid object."""
    text = _THINKING.sub("", text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise NoAnswerError("invalid", "no JSON object in the answer")
    try:
        return schema.model_validate_json(text[start : end + 1])
    except ValidationError as error:
        raise NoAnswerError(
            "invalid", f"the answer doesn't follow the schema ({error.error_count()} errors)"
        ) from error


def _estimate(characters: int, images: int) -> int:
    return characters // 4 + images * config.EXTERNAL_IMAGE_TOKENS + config.EXTERNAL_ANSWER_TOKENS


def request_parts(
    contents: list[types.PartUnionDict], schema: type[BaseModel], structured: bool, provider: ExternalProvider
) -> tuple[list[dict[str, Any]], int]:
    """Gemini's contents as one chat message's parts, and the request's estimated tokens. Only the images the
    provider takes (its cap, and for a token-limited one as many as fit in a minute's tokens), each with its label.
    Without structured output, the schema goes at the end of the text. Raises NoAnswerError("skipped") when even the
    text and one image don't fit."""
    items: list[tuple[str, Any]] = []
    for item in contents:
        if isinstance(item, str):
            items.append(("text", item))
        elif isinstance(item, types.Part) and item.inline_data and item.inline_data.data:
            mime = item.inline_data.mime_type or "image/jpeg"
            items.append(("image", f"data:{mime};base64,{base64.b64encode(item.inline_data.data).decode()}"))
        elif isinstance(item, types.Part) and item.text:
            items.append(("text", item.text))
        else:
            raise TypeError(f"can't send {type(item).__name__} to an external provider")
    if not structured:
        items.append(("text", SCHEMA_INSTRUCTION + json.dumps(schema.model_json_schema(), separators=(",", ":"))))

    images = sum(1 for kind, _ in items if kind == "image")
    characters = sum(len(value) for kind, value in items if kind == "text")
    allowed = images if provider.max_images is None else min(images, provider.max_images)
    if provider.tokens_per_minute is not None:
        room = provider.tokens_per_minute - _estimate(characters, 0)
        allowed = min(allowed, max(0, room // config.EXTERNAL_IMAGE_TOKENS))
        if (images and not allowed) or room < 0:
            raise NoAnswerError("skipped", f"too large for {provider.name}'s tokens per minute")

    parts: list[dict[str, Any]] = []
    sent = 0
    for kind, value in items:
        if kind == "image" and sent >= allowed:
            if parts and parts[-1]["type"] == "text" and _IMAGE_LABEL.match(parts[-1]["text"]):
                parts.pop()  # its label goes with it
            continue
        if kind == "image":
            sent += 1
            parts.append({"type": "image_url", "image_url": {"url": value}})
        else:
            parts.append({"type": "text", "text": value})
    return parts, _estimate(characters, sent)


def _classify(reply: httpx.Response, provider: ExternalProvider) -> str:
    """What an error answer means: refused (the key, credit), unavailable (404: the model is gone, or no longer free),
    spent (its own daily limit), skipped (too many tokens for its limits: not a failure) or busy (a provider
    rate-limited upstream, a 5xx, anything else)."""
    if reply.status_code in REFUSALS:
        return "refused"
    if reply.status_code == 404:
        return "unavailable"
    text = reply.text.lower()
    if reply.status_code == 429 and any(sign in text for sign in _DAILY_LIMIT):
        return "spent"
    if reply.status_code == 413 or (reply.status_code == 429 and provider.tokens_per_minute and "token" in text):
        return "skipped"
    return "busy"


@dataclass
class ExternalReport:
    """The last resort in a run: what each request unit did (`outcomes`: answered, busy, invalid, skipped, refused,
    spent), the ones set aside (`quarantined`) and the providers turned off (`problems`: why). Empty when unused."""

    outcomes: dict[str, dict[str, int]] = field(default_factory=dict)
    quarantined: list[str] = field(default_factory=list)
    problems: dict[str, str] = field(default_factory=dict)


@dataclass
class _Usage:
    """A provider's use today: requests, (estimated, then real) tokens and the answers per model."""

    requests: int = 0
    tokens: int = 0
    answered: Counter[str] = field(default_factory=Counter)


class ExternalTier:
    """Calls the external providers in order, within their limits, failing fast."""

    def __init__(
        self,
        keys: dict[str, str | None] | None = None,
        http: httpx.Client | None = None,
        providers: tuple[ExternalProvider, ...] | None = None,
    ):
        """`keys` (provider name → key) and `http` (an httpx.MockTransport) are for tests; by default the keys come
        from the environment."""
        self.providers = providers if providers is not None else config.EXTERNAL_PROVIDERS
        self._keys = keys if keys is not None else {p.name: config.optional_env(p.key_env) for p in self.providers}
        self._http = http or httpx.Client(timeout=config.EXTERNAL_TIMEOUT_SECONDS)
        self._day = usage_day()
        saved = storage.load_external_usage()
        saved_providers = saved.get("providers", {}) if saved.get("day") == self._day else {}
        self._usage = {
            name: _Usage(item.get("requests", 0), item.get("tokens", 0), Counter(item.get("answered", {})))
            for name, item in saved_providers.items()
        }
        self._last_call: dict[str, float] = {}
        self._window: dict[str, list[list[float]]] = {}  # provider → [moment, tokens] in the last minute
        self._failures: Counter[str] = Counter()
        self.requests_this_run: Counter[str] = Counter()  # per provider
        self.outcomes: dict[str, Counter[str]] = {}  # per request unit (Unit.label): answered, busy, invalid…
        self.quarantined: set[str] = set()  # units set aside for the rest of the run
        self.problems: dict[str, str] = {}  # provider → why it's off for the rest of the run

    # ---------- what's left ----------

    def usage(self, provider: str) -> _Usage:
        return self._usage.setdefault(provider, _Usage())

    def has_budget(self, provider: ExternalProvider) -> bool:
        usage = self.usage(provider.name)
        tokens_left = provider.daily_tokens is None or usage.tokens < provider.daily_tokens
        return usage.requests < provider.daily_requests and tokens_left

    def usable(self, provider: ExternalProvider) -> bool:
        """Its key is set, it wasn't turned off this run, and it has budget left today."""
        return bool(self._keys.get(provider.name)) and provider.name not in self.problems and self.has_budget(provider)

    def available(self) -> bool:
        """Some provider could still answer (a model not set aside, with budget)."""
        return any(
            self.usable(provider) and any(unit.label not in self.quarantined for unit in units(provider))
            for provider in self.providers
        )

    def report(self) -> ExternalReport:
        return ExternalReport(
            outcomes={label: dict(counts) for label, counts in self.outcomes.items()},
            quarantined=sorted(self.quarantined),
            problems=dict(self.problems),
        )

    # ---------- asking ----------

    def generate[T: BaseModel](self, contents: list[types.PartUnionDict], schema: type[T]) -> tuple[T, str]:
        """The first answer from the providers and models in order, and its model ("<provider>:<model>"). Raises
        ExtractionError when they failed, QuotaExhaustedError when none could be asked (no key, no budget, set
        aside, its limits)."""
        failed = False
        for provider in self.providers:
            for unit in units(provider):
                if not self.usable(provider):
                    break
                if unit.label in self.quarantined:
                    continue
                try:
                    return self._ask(unit, contents, schema, quarantine=True)
                except NoAnswerError as miss:
                    log.info("    %s: no answer (%s: %s)", unit.label, miss.kind, miss)
                    failed = failed or miss.kind in FAILURES
        if failed:
            raise ExtractionError("no external model could answer")
        raise QuotaExhaustedError("no external model available")

    def generate_with[T: BaseModel](
        self, provider_name: str, model_name: str, contents: list[types.PartUnionDict], schema: type[T]
    ) -> tuple[T, str]:
        """One model of one provider, whatever happened before in the run (the bake-off). Its output mode comes
        from the config; a model not listed there gets JSON mode. Raises ExtractionError (QuotaExhaustedError when
        it couldn't be asked)."""
        provider = next((p for p in self.providers if p.name == provider_name), None)
        if provider is None:
            raise ValueError(f"unknown provider {provider_name!r}")
        model = next((m for m in provider.models if m.name == model_name), ExternalModel(model_name))
        if not self.usable(provider):
            raise QuotaExhaustedError(f"{provider_name}: no key, turned off or no budget left today")
        try:
            return self._ask(Unit(provider, (model,)), contents, schema, quarantine=False)
        except NoAnswerError as miss:
            error = QuotaExhaustedError if miss.kind in ("spent", "refused") else ExtractionError
            raise error(f"{miss.kind}: {miss}") from miss

    def _ask[T: BaseModel](
        self, unit: Unit, contents: list[types.PartUnionDict], schema: type[T], quarantine: bool
    ) -> tuple[T, str]:
        """One request, its outcome counted; what its failure means for the provider or the model."""
        outcomes = self.outcomes.setdefault(unit.label, Counter())
        try:
            answer, model = self._request(unit, contents, schema)
        except NoAnswerError as miss:
            outcomes[miss.kind] += 1
            if miss.kind == "refused":
                self.problems[unit.provider.name] = str(miss)
                log.warning(
                    "    %s: %s; not used again this run (check %s)", unit.provider.name, miss, unit.provider.key_env
                )
            elif miss.kind == "spent":
                self.usage(unit.provider.name).requests = unit.provider.daily_requests
                self._persist()
            elif miss.kind in FAILURES and quarantine:
                # A model that's gone won't come back within the run: set aside at once.
                self._failures[unit.label] += (
                    1 if miss.kind != "unavailable" else config.EXTERNAL_FAILURES_TO_QUARANTINE
                )
                if self._failures[unit.label] >= config.EXTERNAL_FAILURES_TO_QUARANTINE:
                    self.quarantined.add(unit.label)
                    log.warning(
                        "    %s failed %s times: set aside for the rest of the run",
                        unit.label,
                        self._failures[unit.label],
                    )
            raise
        outcomes["answered"] += 1
        return answer, recorded_name(unit.provider.name, model)

    def _request[T: BaseModel](self, unit: Unit, contents: list[types.PartUnionDict], schema: type[T]) -> tuple[T, str]:
        provider = unit.provider
        parts, estimate = request_parts(contents, schema, unit.structured, provider)
        usage = self.usage(provider.name)
        if provider.daily_tokens is not None and usage.tokens + estimate > provider.daily_tokens:
            raise NoAnswerError("skipped", f"{provider.name}'s daily tokens are used")
        self._wait_for_tokens(provider, estimate)
        self._pace(provider)
        self._spend(provider, estimate)
        try:
            reply = self._http.post(provider.url, json=self._body(unit, parts, schema), headers=self._headers(provider))
        except httpx.TransportError as error:  # a timeout or a dropped connection
            raise NoAnswerError("busy", f"no answer ({type(error).__name__})") from error
        if reply.status_code != 200:
            raise NoAnswerError(_classify(reply, provider), f"{reply.status_code}: {reply.text[:200]}")
        try:
            payload = reply.json()
            if not isinstance(payload, dict):
                raise TypeError("not an object")
        except (ValueError, TypeError) as error:
            raise NoAnswerError("invalid", "the reply isn't JSON") from error
        if payload.get("error"):  # some failures come back as 200 with an error inside
            raise NoAnswerError("busy", f"error in the answer: {str(payload['error'])[:200]}")
        self._count_tokens(provider, estimate, payload.get("usage"))
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise NoAnswerError("invalid", "no message in the answer") from error
        answer = parse_answer(text, schema)
        model = str(payload.get("model") or unit.models[0].name)
        usage.answered[model] += 1
        self._persist()
        return answer, model

    def _body(self, unit: Unit, parts: list[dict[str, Any]], schema: type[BaseModel]) -> dict[str, Any]:
        names = [model.name for model in unit.models]
        body: dict[str, Any] = {"model": names[0], "messages": [{"role": "user", "content": parts}]}
        if unit.provider.routing and len(names) > 1:
            body["models"] = names
        if unit.structured:
            schema_format = {"name": schema.__name__, "strict": True, "schema": schema.model_json_schema()}
            body["response_format"] = {"type": "json_schema", "json_schema": schema_format}
            if unit.provider.routing:
                body["provider"] = {"require_parameters": True}  # only providers that honor the schema
        else:
            body["response_format"] = {"type": "json_object"}
        return body

    def _headers(self, provider: ExternalProvider) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._keys.get(provider.name)}"}
        if provider.routing:  # OpenRouter's app attribution
            headers |= {"HTTP-Referer": config.SITE_URL, "X-Title": "Pa Bailar"}
        return headers

    # ---------- limits ----------

    def _pace(self, provider: ExternalProvider) -> None:
        """Requests spaced to the per-minute limit: a pause of a few seconds at most."""
        interval = 60 / provider.requests_per_minute + config.PACING_MARGIN_SECONDS
        last = self._last_call.get(provider.name)
        if last is not None and (wait := interval - (time.monotonic() - last)) > 0:
            time.sleep(wait)
        self._last_call[provider.name] = time.monotonic()

    def _wait_for_tokens(self, provider: ExternalProvider, estimate: int) -> None:
        """Room in the minute's tokens: waits for it if it comes soon, else NoAnswerError("skipped")."""
        if provider.tokens_per_minute is None:
            return
        now = time.monotonic()
        window = [entry for entry in self._window.get(provider.name, []) if now - entry[0] < 60]
        self._window[provider.name] = window
        excess = sum(entry[1] for entry in window) + estimate - provider.tokens_per_minute
        if excess <= 0:
            return
        freed = 0.0
        for moment, tokens in window:  # oldest first: when enough of them leave the minute
            freed += tokens
            if freed >= excess:
                wait = 60 - (now - moment)
                break
        else:
            wait = 60.0
        if wait > config.EXTERNAL_MAX_WAIT_SECONDS:
            raise NoAnswerError("skipped", f"{provider.name}'s tokens for this minute are used")
        time.sleep(wait)

    def _spend(self, provider: ExternalProvider, estimate: int) -> None:
        usage = self.usage(provider.name)
        usage.requests += 1
        usage.tokens += estimate
        self.requests_this_run[provider.name] += 1
        if provider.tokens_per_minute is not None:
            self._window.setdefault(provider.name, []).append([time.monotonic(), float(estimate)])
        self._persist()

    def _count_tokens(self, provider: ExternalProvider, estimate: int, reported: Any) -> None:
        """The request's real tokens, when the answer says, in place of the estimate."""
        real = reported.get("total_tokens") if isinstance(reported, dict) else None
        if not isinstance(real, int):
            return
        self.usage(provider.name).tokens += real - estimate
        if window := self._window.get(provider.name):
            window[-1][1] = float(real)

    def _persist(self) -> None:
        """Save today's use, so later runs on the same day share the budgets."""
        providers = {
            name: {"requests": usage.requests, "tokens": usage.tokens, "answered": dict(usage.answered)}
            for name, usage in self._usage.items()
        }
        storage.save_external_usage({"day": self._day, "providers": providers})
