"""Local OpenAI-compatible llama-server client for Farol narration.

Used by Qwen narration while browsing and driving, plus explicit model evaluations.
No web tools or persisted prompts/receipts. Radar prompts include the current
origin for local reasoning; the client sends them only to the configured model
endpoint. Python validates scores, choices and factual claims.
"""

from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from farol.adapters.base import FeedError
from farol.grok import extract_json_object, extract_text

DEFAULT_URL = "http://127.0.0.1:1234/v1/chat/completions"
DEFAULT_MODEL = "qwen3.8-27b"

# llama.cpp enforces this shape while decoding. Factual faithfulness is still
# checked separately; valid JSON alone does not make a recommendation correct.
NARRATION_SCHEMA = {
    "type": "object",
    "properties": {
        **{key: {"type": "string"} for key in (
            "headline", "spoken", "shift_rationale", "now_move",
        )},
        "risks": {"type": "array", "items": {"type": "string"}},
        "opportunity_notes": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "required": ["headline", "spoken", "shift_rationale", "now_move", "risks", "opportunity_notes"],
    "additionalProperties": False,
}


def local_url() -> str:
    return os.getenv("FAROL_LOCAL_URL", DEFAULT_URL).strip() or DEFAULT_URL


def local_model() -> str:
    from farol.local_models import profile
    from farol.shift import active, status

    if active():
        loaded = status().get("model")
        if loaded:
            return str(loaded)
    return os.getenv("FAROL_LOCAL_MODEL", "").strip() or profile()["alias"]


def complete(
    *,
    system: str,
    user: str,
    cache_key: str,
    timeout: float | None = None,
    endpoint: str | None = None,
    model_name: str | None = None,
    model_profile: str | None = None,
    response_schema: dict | None = None,
    enable_thinking: bool | None = None,
    max_tokens: int | None = None,
    metric_workload: str = "application",
    input_token_ceiling: int | None = None,
) -> tuple[dict, str, str]:
    """POST /v1/chat/completions. Returns (openai-shaped payload, mode, fetched_at)."""
    del cache_key
    settings = generation_settings(model_profile, model_name or local_model())
    thinking = settings["enable_thinking"] if enable_thinking is None else enable_thinking
    budget = settings["reasoning_budget"] if thinking else 0
    tokens = settings["max_tokens"] if max_tokens is None else max_tokens
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    schema = response_schema or NARRATION_SCHEMA
    measurement = None
    is_qwen = model_profile == "qwen" if model_profile else "qwen" in (model_name or local_model()).casefold()
    if is_qwen:
        from farol.prompt_budget import enforce
        measurement = enforce(messages, schema, thinking=thinking, output_tokens=tokens)
        if input_token_ceiling is not None and measurement["input_tokens"] > input_token_ceiling:
            from farol.prompt_budget import PromptBudgetExceeded
            raise PromptBudgetExceeded("Owned policy input ceiling exceeded; no model request sent")
    body = json.dumps(
        {
            "model": model_name or local_model(),
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": tokens,
            "response_format": {"type": "json_object", "schema": schema},
            "chat_template_kwargs": {"enable_thinking": thinking},
            "reasoning_format": "deepseek",
            "reasoning_budget": budget,
        }
    ).encode("utf-8")
    request = Request(
        endpoint or local_url(),
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    request_started = time.monotonic()
    try:
        with urlopen(request, timeout=timeout or settings["timeout_seconds"]) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        raise FeedError(f"local brain: {error}") from error
    from datetime import UTC, datetime

    from farol.model_metrics import record, receipt
    seconds = time.monotonic() - request_started
    record(payload, seconds, model_name or local_model(), metric_workload)

    if measurement is not None:
        payload["rideedge_prompt_budget"] = measurement

    # Only an explicit, context-local recording capture retains these texts.
    from farol.recording_capture import retain
    retain(json.loads(body), payload, receipt(payload, seconds, model_name or local_model(), metric_workload))

    return payload, "live", datetime.now(UTC).isoformat()


def generation_settings(name: str | None = None, alias: str | None = None) -> dict:
    from farol.local_models import profile

    if name is None and alias:
        for candidate in ("gemma", "qwen"):
            if profile(candidate)["alias"] == alias:
                name = candidate
                break
    selected = profile(name)
    return {key: selected[key] for key in (
        "enable_thinking", "reasoning_budget", "max_tokens", "timeout_seconds",
    )}


def narration_from_payload(payload: dict) -> dict:
    text = extract_text(payload)
    if not text:
        message = ((payload.get("choices") or [{}])[0].get("message") or {})
        text = str(message.get("content") or "")
    return extract_json_object(text)
