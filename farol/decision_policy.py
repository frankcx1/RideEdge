"""Small owned YAML policy, validated before use; never loads external AI text."""
from functools import lru_cache
import hashlib
from pathlib import Path

import yaml

PATH = Path(__file__).with_name("decision_policy.yaml")


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key, value in node.value:
        key = loader.construct_object(key, deep=deep)
        if not isinstance(key, str):
            raise ValueError("Decision-policy keys must be strings")
        if key in result:
            raise ValueError("Duplicate decision-policy key")
        result[key] = loader.construct_object(value, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


@lru_cache(maxsize=4)
def parse(raw):
    policy = yaml.load(raw, Loader=UniqueLoader)
    required = {"version", "mode", "review_interval_minutes", "now_route_minutes", "event_preposition_minutes",
                "continuous_remaining_minutes", "closing_tail_minutes", "hysteresis_points",
                "model_timeout_seconds", "model_output_tokens", "input_token_ceiling", "system_instruction"}
    if not isinstance(policy, dict) or set(policy)-{"positioning_fallback_enabled"} != required:
        raise ValueError("Decision policy has missing or unknown fields")
    # Backward-compatible while the old service is still running. The owned gate
    # and revised instruction are deployed together after client validation.
    policy.setdefault("positioning_fallback_enabled", False)
    if not isinstance(policy["mode"], str) or policy["mode"] not in {"off", "shadow", "live"}:
        raise ValueError("Invalid decision-policy mode")
    if type(policy["positioning_fallback_enabled"]) is not bool:
        raise ValueError("Positioning fallback gate must be boolean")
    bounds = {"review_interval_minutes": (5, 60), "now_route_minutes": (1, 30), "event_preposition_minutes": (0, 30),
              "continuous_remaining_minutes": (0, 60), "closing_tail_minutes": (0, 45),
              "hysteresis_points": (0, 10), "model_timeout_seconds": (30, 240),
              "model_output_tokens": (256, 2000), "input_token_ceiling": (512, 6500)}
    for key, (low, high) in bounds.items():
        if type(policy[key]) not in (int, float) or not low <= policy[key] <= high:
            raise ValueError("Invalid decision-policy bound: " + key)
        if key != "hysteresis_points" and type(policy[key]) is not int:
            raise ValueError("Decision-policy bound must be an integer: " + key)
    if not isinstance(policy["system_instruction"], str) or not 20 <= len(policy["system_instruction"]) <= 4000:
        raise ValueError("Invalid policy instruction")
    if not isinstance(policy["version"], str) or not 1 <= len(policy["version"]) <= 80:
        raise ValueError("Invalid policy version")
    return {**policy, "sha256": hashlib.sha256(raw).hexdigest()}


def load():
    return dict(parse(PATH.read_bytes()))


def status():
    try:
        p = load()
        return {k: p[k] for k in ("version", "mode", "sha256", "positioning_fallback_enabled", "review_interval_minutes", "now_route_minutes",
                "event_preposition_minutes", "continuous_remaining_minutes", "hysteresis_points",
                "model_timeout_seconds", "input_token_ceiling", "system_instruction")}
    except (OSError, ValueError, yaml.YAMLError):
        return {"mode": "off", "error": "Owned policy invalid; legacy control retained"}


def interval_seconds():
    return int(status().get("review_interval_minutes", 15) * 60)
