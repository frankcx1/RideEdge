"""Shared SpaceXAI / xAI Grok 4.6 client.

Testing-phase default: cloud Grok, no local model. SuperGrok app access is not
an API key — set XAI_API_KEY from https://console.x.ai.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime

from farol.adapters.base import fetch_json

API_URL = "https://api.x.ai/v1/responses"
DEFAULT_MODEL = "grok-4.6"
DEFAULT_TTL_SECONDS = 20 * 60
DEFAULT_TIMEOUT_SECONDS = 90


def api_key() -> str:
    return os.getenv("XAI_API_KEY", "").strip()


def model() -> str:
    return os.getenv("FAROL_GROK_MODEL", DEFAULT_MODEL)


def brain_name() -> str:
    return os.getenv("FAROL_BRAIN", "qwen").strip().lower() or "qwen"


def require_cloud_enabled() -> None:
    """Old cloud tools are opt-in only; local AI never falls back to xAI."""
    if brain_name() != "grok":
        from farol.adapters.base import FeedError

        raise FeedError("Cloud AI is disabled; Farol uses the configured local narrator")


def ttl_seconds() -> float:
    try:
        return max(60.0, float(os.getenv("FAROL_GROK_TTL_SECONDS", str(DEFAULT_TTL_SECONDS))))
    except ValueError:
        return float(DEFAULT_TTL_SECONDS)


def cache_bucket(moment: datetime | None = None) -> str:
    """Floor a timestamp to FAROL_GROK_TTL_SECONDS so polls share one paid call."""
    now = moment or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    step = max(60, int(ttl_seconds()))
    epoch = int(now.timestamp())
    return str(epoch - epoch % step)


def timeout_seconds() -> float:
    try:
        return max(15.0, float(os.getenv("FAROL_GROK_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))))
    except ValueError:
        return float(DEFAULT_TIMEOUT_SECONDS)


def reasoning_effort(kind: str = "research") -> str:
    if kind == "brain":
        return os.getenv("FAROL_GROK_BRAIN_REASONING", "high")
    return os.getenv("FAROL_GROK_REASONING", "low")


def extract_text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"]
    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            chunks.append(content)
            continue
        for part in content or []:
            if isinstance(part, dict):
                text = part.get("text") or part.get("output_text") or ""
                if text:
                    chunks.append(text)
            elif isinstance(part, str):
                chunks.append(part)
    if chunks:
        return "\n".join(chunks)
    choices = payload.get("choices") or []
    if choices:
        message = (choices[0] or {}).get("message") or {}
        if isinstance(message.get("content"), str):
            return message["content"]
    return ""


def extract_json_object(text: str) -> dict:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Grok response did not contain a JSON object")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Grok JSON root must be an object")
    return payload


def complete(
    *,
    system: str,
    user: str,
    cache_key: str,
    prompt_cache_key: str,
    tools: list[dict] | None = None,
    reasoning: str = "low",
    timeout: float | None = None,
) -> tuple[dict, str, str]:
    """POST /v1/responses. Returns (payload, mode, fetched_at)."""
    require_cloud_enabled()
    key = api_key()
    if not key:
        raise RuntimeError("XAI_API_KEY is not set")
    body: dict = {
        "model": model(),
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "reasoning": {"effort": reasoning},
        "prompt_cache_key": prompt_cache_key,
    }
    if tools:
        body["tools"] = tools
    return fetch_json(
        API_URL,
        cache_key=cache_key,
        ttl_seconds=ttl_seconds(),
        timeout=timeout if timeout is not None else timeout_seconds(),
        method="POST",
        body=body,
        headers={"Authorization": f"Bearer {key}"},
    )
