"""LLM client (owned by M4; used by M1's metadata extractor, M2's data generator and M3's workflow).

* Ollama (local) is the default, called with a JSON schema in `format` so the
  model is constrained to valid structure.
* Every response is validated with Pydantic; invalid JSON is retried with the
  validation error fed back (7B models are unreliable at JSON - guide 5.1).
* Optional cloud fallback (OpenAI-compatible) behind CLOUD_FALLBACK=true.
* MOCK_LLM=true routes each task to a deterministic Python responder so the
  whole pipeline runs and is testable without a model.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Optional, Type

import httpx
from pydantic import BaseModel, ValidationError

from shared.config import settings

log = logging.getLogger(__name__)
_MOCKS: dict[str, Callable[[dict], dict]] = {}


def register_mock(task: str):
    def deco(fn: Callable[[dict], dict]):
        _MOCKS[task] = fn
        return fn
    return deco


class LLMError(RuntimeError):
    pass


@lru_cache(maxsize=8)
def _can_think(ollama_url: str, model: str) -> bool:
    """Reasoning models (qwen3, deepseek-r1...) think before answering unless told not to."""
    try:
        r = httpx.post(f"{ollama_url}/api/show", json={"model": model}, timeout=5)
        r.raise_for_status()
        return "thinking" in r.json().get("capabilities", [])
    except (httpx.HTTPError, ValueError):
        return False


@dataclass
class LLMResult:
    data: Any
    calls: int = 0
    tokens: int = 0
    model: str = ""


def _extract_json(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    return t[start:end + 1] if start != -1 and end != -1 else t


def _strict_schema(schema: Type[BaseModel]) -> dict:
    """The model's JSON schema with every field required. Fields with defaults are optional in
    the Pydantic schema, and constrained decoding then lets a model stop at `{}` - which reads
    as "no answer" - unless it is forced to fill each field in."""
    js = schema.model_json_schema()
    for obj in [js, *js.get("$defs", {}).values()]:
        if obj.get("type") == "object" and obj.get("properties"):
            obj["required"] = list(obj["properties"])
    return js


class LLMClient:
    @property
    def model_name(self) -> str:
        return "mock" if settings.mock_llm else settings.llm_model

    def chat_json(self, task: str, system: str, user: str, schema: Type[BaseModel],
                  mock_context: Optional[dict] = None, temperature: float = 0.0) -> LLMResult:
        if settings.mock_llm:
            fn = _MOCKS.get(task)
            if fn is None:
                raise LLMError(f"No mock responder registered for task '{task}'")
            return LLMResult(data=schema.model_validate(fn(mock_context or {})), model="mock")

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        calls = tokens = 0
        last_err: Optional[Exception] = None
        for attempt in range(settings.llm_max_retries + 1):
            try:
                content, used = self._ollama(messages, schema, temperature)
            except httpx.HTTPError as e:            # Ollama down: no point retrying JSON
                last_err = e
                break
            calls += 1
            tokens += used
            try:
                data = schema.model_validate_json(_extract_json(content))
                return LLMResult(data=data, calls=calls, tokens=tokens, model=settings.llm_model)
            except (ValidationError, ValueError) as e:
                last_err = e
                log.warning("task=%s attempt=%d invalid JSON: %s", task, attempt, str(e)[:200])
                messages = messages[:2] + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"That JSON was invalid: {str(e)[:500]}. "
                                                "Reply again with ONLY a JSON object matching the schema."},
                ]

        if settings.cloud_fallback and settings.cloud_base_url:
            try:
                content, used = self._cloud(messages[:2], schema, temperature)
                data = schema.model_validate_json(_extract_json(content))
                return LLMResult(data=data, calls=calls + 1, tokens=tokens + used,
                                 model=f"cloud:{settings.cloud_model}")
            except Exception as e:  # noqa: BLE001
                last_err = e
        raise LLMError(f"task={task} failed: {last_err}")

    # ------------------------------------------------------------------ #
    def _ollama(self, messages: list[dict], schema: Type[BaseModel], temperature: float):
        body = {"model": settings.llm_model, "messages": messages, "stream": False,
                "format": _strict_schema(schema), "options": {"temperature": temperature},
                "keep_alive": settings.llm_keep_alive}
        if _can_think(settings.ollama_url, settings.llm_model):
            # off by default: hidden reasoning tokens are most of the response time
            body["think"] = settings.llm_think
        r = httpx.post(f"{settings.ollama_url}/api/chat", json=body, timeout=settings.llm_timeout)
        r.raise_for_status()
        j = r.json()
        used = int(j.get("prompt_eval_count", 0)) + int(j.get("eval_count", 0))
        return j["message"]["content"], used

    def _cloud(self, messages: list[dict], schema: Type[BaseModel], temperature: float):
        sys = messages[0]["content"] + "\nJSON schema:\n" + json.dumps(schema.model_json_schema())
        r = httpx.post(
            f"{settings.cloud_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.cloud_api_key}"},
            json={"model": settings.cloud_model, "temperature": temperature,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": sys}, messages[1]]},
            timeout=settings.llm_timeout,
        )
        r.raise_for_status()
        j = r.json()
        return j["choices"][0]["message"]["content"], int(j.get("usage", {}).get("total_tokens", 0))

    def health(self) -> dict:
        if settings.mock_llm:
            return {"status": "ok", "mode": "mock", "model": "mock"}
        try:
            r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=5)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
            ok = any(n.startswith(settings.llm_model) for n in names)
            return {"status": "ok" if ok else "model_missing", "mode": "ollama",
                    "model": settings.llm_model, "available": names}
        except httpx.HTTPError as e:
            return {"status": "down", "mode": "ollama", "model": settings.llm_model, "error": str(e)}
