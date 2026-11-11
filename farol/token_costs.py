"""Read-only cloud-spend comparison. No cloud requests or claimed total savings."""
from datetime import UTC, datetime
import math

OPENAI = "https://developers.openai.com/api/docs/pricing"
CLAUDE = "https://platform.claude.com/docs/en/about-claude/pricing"
GEMINI = "https://ai.google.dev/gemini-api/docs/pricing"


def rate_cards(now=None):
    today = (now or datetime.now(UTC)).date().isoformat()
    promo = today < "2026-12-01"
    return {"verified_on": "2026-10-31", "currency": "USD", "unit": "per million tokens",
        "tier": "Standard, uncached text, short context; no batch discounts or tool fees",
        "research_basis": "EdgeForward model-assumptions-research-2026-10-14.md; rates rechecked against primary pages",
        "rates": [
            {"id": "gpt-6-astra", "input": 10, "output": 50, "url": OPENAI},
            {"id": "gpt-6.1-sol", "input": 2, "output": 10, "url": OPENAI},
            {"id": "gpt-6-luna", "input": .10, "output": .50, "url": OPENAI},
            {"id": "Claude Fable 5.1", "input": 10, "output": 50, "url": CLAUDE},
            {"id": "Claude Opus 5.5", "input": 4, "output": 20, "url": CLAUDE},
            {"id": "Claude Sonnet 5.5", "input": 2, "output": 10, "url": CLAUDE},
            {"id": "Gemini 4 Argon", "input": 2 if promo else 4, "output": 10 if promo else 20,
             "url": GEMINI, "note": "Introductory rates through 2026-11-30; published doubling on 2026-12-01."}],
        "limits": "Local token counts are a workload proxy, not a cloud bill. Tokenizers, reasoning length and answer quality differ. Cache/batch discounts, taxes, tools, hardware, electricity and data feeds are excluded."}


def estimate(input_tokens, output_tokens, input_rate, output_rate, interval_minutes, duration_seconds=0, contexts=1):
    values = [input_tokens, output_tokens, input_rate, output_rate, interval_minutes, duration_seconds, contexts]
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values) or interval_minutes <= 0 or contexts < 1:
        raise ValueError("Invalid calculator input")
    reviews = 3600 / (interval_minutes*60 + duration_seconds)
    per_review = (input_tokens*input_rate + output_tokens*output_rate)/1_000_000
    return {"per_review_usd": per_review, "reviews_per_hour_per_context": reviews,
            "per_hour_usd": per_review*reviews*contexts, "local_token_fee_usd": 0,
            "label": "Estimated cloud API spend avoided; not net operating savings"}
