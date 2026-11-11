"""Shared local model profiles for the Python client and PowerShell launcher."""

import json
import os

from farol.dashboard import ROOT

PROFILE_PATH = ROOT / "beast" / "local-models.json"


def profile(name: str | None = None) -> dict:
    payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    selected = name or os.getenv("FAROL_LOCAL_PROFILE", "").strip() or payload["default"]
    if selected not in payload["models"]:
        raise ValueError(f"unknown local model profile {selected!r}; choose gemma or qwen")
    return {"id": selected, **payload["models"][selected]}
