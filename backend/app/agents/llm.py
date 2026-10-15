"""One small wrapper around the Anthropic SDK for every agent.

    llm = LLM()                                   # reads the key for LLM_PROVIDER from the env / repo-root .env
    dna = await llm.json(model=WORKER_MODEL, system=..., prompt=..., schema=ThesisDraft, on_retry=cb)
    found = await llm.search(model=WORKER_MODEL, system=..., prompt=..., max_uses=5)

- Agents name a ROLE (ORCHESTRATOR_MODEL / WORKER_MODEL / EXTRACT_MODEL); the model id is read from
  MODEL_ORCHESTRATOR / MODEL_WORKER / MODEL_EXTRACT at call time (default claude-haiku-5-5, see
  config.model_for). A literal model id is passed through unchanged.
- Structured output goes through `client.beta.messages.parse(output_format=Model)`, so the reply is
  validated against the Pydantic schema. If it still doesn't validate, the agent gets ONE repair attempt
  with the validation error (docs/ARCHITECTURE.md).
- Server-side refusal fallbacks (`fallbacks="default"`) are only sent to the models that accept them
  (Fable 5.1 / Opus 5.5 / Opus 5 / Sonnet 5.5). Haiku 5.5 has no server-side fallback, so it gets neither
  the beta nor the parameter.
- Thinking is left adaptive (the default on current models; never `budget_tokens`); depth is set with
  `output_config.effort`. RUN_PROFILE=fast (the default) turns thinking off (`thinking: {type: disabled}`): Haiku
  answers ~8x faster that way. RUN_PROFILE=thorough leaves it adaptive. No temperature/top_p/top_k (Haiku 5.5 rejects non-default values) and no prefill.
- Web search: `web_search_20260209` (dynamic filtering) on Opus/Sonnet 4.6+, the basic
  `web_search_20250305` on every other model (Haiku included).
- LLM_PROVIDER=deepseek: the same SDK pointed at DEEPSEEK_BASE_URL. JSON comes from the schema in the
  prompt (no structured-output feature there) and there is no server web search: `search()` raises
  LLMError and the agents fall back to reading pages directly.
- Retries: the SDK retries once quietly; on top of that we retry rate limits, overloads, 5xx and network
  errors with backoff and call `on_retry(attempt, reason)` so the feed can show "Retrying".
- Errors become `LLMError` (gave up) or `LLMUnavailable` (no key / key rejected / no network), both with a
  plain-English message.

Tests pass a fake client: `LLM(client=FakeAnthropic(...))`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from .. import config

log = logging.getLogger("bellwether.llm")

# Roles, resolved to a model id at call time (config.model_for). Agents pass these as `model=`.
ORCHESTRATOR_MODEL = "role:orchestrator"
WORKER_MODEL = "role:worker"
EXTRACT_MODEL = "role:extract"

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models that accept the `fallbacks: "default"` server-side refusal fallback (Claude API).
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
WEB_SEARCH_TOOL_TYPE = "web_search_20260209"  # dynamic filtering (Opus/Sonnet 4.6 and later)
WEB_SEARCH_BASIC_TYPE = "web_search_20250305"  # every other model, Haiku included
_DYNAMIC_SEARCH_MODELS = ("claude-fable-", "claude-mythos-", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7",
                          "claude-opus-4-6", "claude-sonnet-5", "claude-sonnet-4-6")

MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 2.0  # tests set this to 0
REQUEST_TIMEOUT_S = 180.0

T = TypeVar("T", bound=BaseModel)

# Running token tally per model id for this process (read by the health/cost checks and logged per call).
USAGE: dict[str, dict[str, int]] = {}


def _note_usage(resp: Any) -> None:
    usage = getattr(resp, "usage", None)
    model = getattr(resp, "model", None)
    if usage is None or not isinstance(model, str):
        return
    row = USAGE.setdefault(model, {"calls": 0, "input": 0, "output": 0, "searches": 0})
    tin = int(getattr(usage, "input_tokens", 0) or 0) + int(getattr(usage, "cache_read_input_tokens", 0) or 0)         + int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    tout = int(getattr(usage, "output_tokens", 0) or 0)
    stu = getattr(usage, "server_tool_use", None)
    searches = int(getattr(stu, "web_search_requests", 0) or 0) if stu is not None else 0
    row["calls"] += 1
    row["input"] += tin
    row["output"] += tout
    row["searches"] += searches
    log.info("model call model=%s in=%d out=%d searches=%d", model, tin, tout, searches)


RetryHook = Callable[[int, str], Any]


class LLMError(Exception):
    """A model call gave up. `str(exc)` is plain English."""


class LLMUnavailable(LLMError):
    """No usable connection to Claude at all (missing or rejected key, network down)."""

    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


@dataclass
class SearchHit:
    url: str
    title: str
    page_age: Optional[str] = None


@dataclass
class SearchOutcome:
    text: str  # the model's written findings (untrusted: derived from web pages)
    hits: list[SearchHit] = field(default_factory=list)
    quotes: list[dict] = field(default_factory=list)  # [{"url", "title", "cited_text"}] from citations
    error: Optional[str] = None  # server-side search error code, if any
    searches: int = 0


def resolve_model(model: str) -> str:
    """A role ("role:worker") -> the configured model id; a literal id passes through."""
    if model.startswith("role:"):
        return config.model_for(model.split(":", 1)[1])
    return model


def search_tool_type(model_id: str) -> str:
    return WEB_SEARCH_TOOL_TYPE if model_id.startswith(_DYNAMIC_SEARCH_MODELS) else WEB_SEARCH_BASIC_TYPE


class LLM:
    def __init__(self, client: Any = None, provider: str | None = None):
        self._client = client
        self.provider = provider or config.llm_provider()

    @property
    def client(self) -> Any:
        if self._client is None:
            key = config.llm_key()
            if not key:
                name = "DeepSeek" if self.provider == "deepseek" else "Anthropic"
                raise LLMUnavailable(f"No {name} API key is set, so the live agents can't start.",
                                     reason="no_api_key")
            kw: dict[str, Any] = {"api_key": key, "max_retries": 1, "timeout": REQUEST_TIMEOUT_S}
            if self.provider == "deepseek":
                kw["base_url"] = config.deepseek_base_url()
            self._client = anthropic.AsyncAnthropic(**kw)
        return self._client

    # ------------------------------------------------------------------
    # Request plumbing
    # ------------------------------------------------------------------

    def _base(self, model: str, effort: str, max_tokens: int, system: str) -> dict:
        model = resolve_model(model)
        kw: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "system": system}
        if self.provider == "deepseek":
            return kw  # no effort setting and no server-side fallbacks there
        kw["output_config"] = {"effort": effort}
        if not config.cap("thinking"):  # RUN_PROFILE=fast: no extended thinking (Haiku: ~25s -> ~3s per call)
            kw["thinking"] = {"type": "disabled"}
        if model in _FALLBACK_MODELS:  # on a policy decline, the API re-runs on a fallback model
            kw["betas"] = [FALLBACK_BETA]
            kw["fallbacks"] = "default"
        return kw

    async def _with_retries(self, call: Callable[[], Awaitable[Any]], on_retry: Optional[RetryHook]) -> Any:
        last = "an unknown problem"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = await call()
                _note_usage(resp)
                return resp
            except anthropic.AuthenticationError:
                raise LLMUnavailable("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in .env.",
                                     reason="bad_api_key")
            except anthropic.PermissionDeniedError:
                raise LLMUnavailable("The Anthropic API key isn't allowed to use this model.",
                                     reason="permission_denied")
            except anthropic.NotFoundError:
                raise LLMError("The requested Claude model wasn't found.")
            except anthropic.BadRequestError as exc:
                log.warning("bad request: %s", getattr(exc, "message", exc))
                raise LLMError("Claude couldn't accept the request.")
            except anthropic.RateLimitError:
                last = "Claude is busy right now"
            except anthropic.APIStatusError as exc:
                if exc.status_code < 500:
                    raise LLMError("Claude couldn't accept the request.")
                last = "Claude is having a temporary problem"
            except anthropic.APIConnectionError:  # includes APITimeoutError
                last = "couldn't reach Claude"
                if attempt == MAX_ATTEMPTS:
                    raise LLMUnavailable("Couldn't reach Claude. Check the internet connection.",
                                         reason="no_connection")
            if attempt < MAX_ATTEMPTS:
                if on_retry is not None:
                    res = on_retry(attempt, last)
                    if asyncio.iscoroutine(res):
                        await res
                await asyncio.sleep(BACKOFF_BASE_S * (2 ** (attempt - 1)) + random.uniform(0, BACKOFF_BASE_S / 4))
        raise LLMError(f"Gave up after {MAX_ATTEMPTS} tries: {last}.")

    @staticmethod
    def _check_stop(resp: Any) -> None:
        if getattr(resp, "stop_reason", None) == "refusal":
            raise LLMError("Claude declined this request.")

    # ------------------------------------------------------------------
    # Structured output
    # ------------------------------------------------------------------

    async def json(self, *, model: str, system: str, prompt: str, schema: type[T], effort: str = "medium",
                   max_tokens: int = 16000, on_retry: Optional[RetryHook] = None) -> T:
        """Ask for a reply that validates against `schema`. One repair attempt on a validation error."""
        client = self.client
        base = self._base(model, effort, max_tokens, system)
        if self.provider == "deepseek":
            return await self._json_from_text(client, base, prompt, schema, on_retry)
        messages: list[dict] = [{"role": "user", "content": prompt}]
        problem = ""
        for repair in (False, True):
            msgs = messages if not repair else [
                {"role": "user", "content": prompt + "\n\nYour previous answer didn't match the required "
                 f"format ({problem}). Answer again, following the schema exactly."}]
            try:
                resp = await self._with_retries(
                    lambda: client.beta.messages.parse(messages=msgs, output_format=schema, **base), on_retry)
            except (ValidationError, ValueError) as exc:  # the SDK validates while parsing
                problem = _short(exc)
                continue
            self._check_stop(resp)
            parsed = getattr(resp, "parsed_output", None)
            if isinstance(parsed, schema):
                return parsed
            if getattr(resp, "stop_reason", None) == "max_tokens":
                problem = "the answer was cut off; keep it shorter"
                continue
            text = _text_of(resp)  # a fake client or an older SDK may hand back plain text
            try:
                return schema.model_validate_json(text)
            except (ValidationError, ValueError) as exc:
                problem = _short(exc)
        raise LLMError("Claude's answer didn't have the expected shape, even after a second try.")

    async def _json_from_text(self, client: Any, base: dict, prompt: str, schema: type[T],
                              on_retry: Optional[RetryHook]) -> T:
        """Providers without structured outputs: put the JSON schema in the prompt and validate the reply."""
        shape = json.dumps(schema.model_json_schema(), separators=(",", ":"))
        ask = (prompt + "\n\nReply with ONE JSON object only (no prose, no code fences) that matches this "
               f"JSON schema:\n{shape}")
        problem = ""
        for repair in (False, True):
            content = ask if not repair else (ask + "\n\nYour previous answer didn't match the required "
                                              f"format ({problem}). Answer again, following the schema exactly.")
            resp = await self._with_retries(
                lambda: client.messages.create(messages=[{"role": "user", "content": content}], **base), on_retry)
            self._check_stop(resp)
            try:
                return schema.model_validate_json(_strip_fences(_text_of(resp)))
            except (ValidationError, ValueError) as exc:
                problem = _short(exc)
        raise LLMError("The model's answer didn't have the expected shape, even after a second try.")

    async def text(self, *, model: str, system: str, prompt: str, effort: str = "low", max_tokens: int = 4000,
                   on_retry: Optional[RetryHook] = None) -> str:
        client = self.client
        base = self._base(model, effort, max_tokens, system)
        api = client.messages if self.provider == "deepseek" else client.beta.messages
        resp = await self._with_retries(
            lambda: api.create(messages=[{"role": "user", "content": prompt}], **base), on_retry)
        self._check_stop(resp)
        return _text_of(resp).strip()

    # ------------------------------------------------------------------
    # Web search (Claude's server-side tool)
    # ------------------------------------------------------------------

    async def search(self, *, model: str, system: str, prompt: str, max_uses: int = 5, effort: str = "medium",
                     max_tokens: int = 16000, allowed_domains: list[str] | None = None,
                     on_retry: Optional[RetryHook] = None, max_continuations: int = 3) -> SearchOutcome:
        if self.provider == "deepseek":  # no server-side web search: the agents read pages directly instead
            raise LLMError("Web search isn't available with this model provider")
        client = self.client
        base = self._base(model, effort, max_tokens, system)
        tool: dict[str, Any] = {"type": search_tool_type(base["model"]), "name": "web_search",
                                "max_uses": max_uses}
        if allowed_domains:
            tool["allowed_domains"] = allowed_domains
        messages: list[dict] = [{"role": "user", "content": prompt}]
        out = SearchOutcome(text="")
        texts: list[str] = []
        for _ in range(max_continuations + 1):
            resp = await self._with_retries(
                lambda: client.beta.messages.create(messages=messages, tools=[tool], **base), on_retry)
            self._check_stop(resp)
            _collect_search(resp, out, texts)
            if getattr(resp, "stop_reason", None) != "pause_turn":
                break
            # A long server-tool turn paused: send it back so Claude continues where it stopped.
            messages = [messages[0], {"role": "assistant", "content": resp.content}]
        out.text = "\n".join(t for t in texts if t).strip()
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        errs = exc.errors()[:3]
        return "; ".join(f"{'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg')}" for e in errs)
    return str(exc)[:200]


def _strip_fences(text: str) -> str:
    """The JSON object inside a reply that may carry code fences or a sentence around it."""
    t = text.strip()
    start, end = t.find("{"), t.rfind("}")
    return t[start:end + 1] if start != -1 and end > start else t


def _text_of(resp: Any) -> str:
    return "".join(getattr(b, "text", "") or "" for b in getattr(resp, "content", []) or []
                   if getattr(b, "type", None) == "text")


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _collect_search(resp: Any, out: SearchOutcome, texts: list[str]) -> None:
    seen = {h.url for h in out.hits}
    for block in getattr(resp, "content", []) or []:
        btype = _get(block, "type")
        if btype == "server_tool_use":
            out.searches += 1
        elif btype == "web_search_tool_result":
            content = _get(block, "content")
            if isinstance(content, list):  # success: a list of results
                for r in content:
                    url = _get(r, "url")
                    if url and url not in seen:
                        seen.add(url)
                        out.hits.append(SearchHit(url=url, title=_get(r, "title") or url,
                                                  page_age=_get(r, "page_age")))
            else:  # error: an object with error_code
                out.error = _get(content, "error_code") or "search_error"
        elif btype == "text":
            texts.append(_get(block, "text") or "")
            for c in _get(block, "citations") or []:
                url = _get(c, "url")
                if url:
                    out.quotes.append({"url": url, "title": _get(c, "title") or url,
                                       "cited_text": (_get(c, "cited_text") or "")[:400]})


def dumps(obj: Any) -> str:
    """Compact JSON for prompts."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)
