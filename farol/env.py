"""Load a local .env without adding a dependency.

Existing process environment wins, so tests and shell overrides stay in charge.
Call this from the API process entrypoint only — not from import of scoring
modules — so pytest cannot accidentally activate live feeds from a developer .env.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from farol.dashboard import ROOT

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
_UNSPECIFIED_HOSTS = {"0.0.0.0", "::", "*", "[::]"}


def load_env(path: Path | None = None) -> Path | None:
    target = path if path is not None else ROOT / ".env"
    if not target.exists():
        return None
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and value and key not in os.environ:
            os.environ[key] = value
    return target


def bind_host() -> str:
    """Loopback by default so the dashboard is reached over RDP, not the public NIC."""
    raw = os.getenv("FAROL_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    if raw.lower() in {"tailscale", "tailnet"}:
        return tailscale_ipv4()
    if raw.strip().lower() in _UNSPECIFIED_HOSTS and os.getenv("FAROL_ALLOW_PUBLIC_BIND", "") != "1":
        raise ValueError(
            "refusing to bind all interfaces; keep FAROL_HOST=127.0.0.1 for RDP, "
            "FAROL_HOST=tailscale for the mesh, or set FAROL_ALLOW_PUBLIC_BIND=1"
        )
    return raw


def bind_port() -> int:
    raw = os.getenv("FAROL_PORT", str(DEFAULT_PORT)).strip() or str(DEFAULT_PORT)
    try:
        port = int(raw)
    except ValueError as error:
        raise ValueError(f"invalid FAROL_PORT {raw!r}") from error
    if not 1 <= port <= 65535:
        raise ValueError(f"FAROL_PORT out of range: {port}")
    return port


def tailscale_ipv4() -> str:
    override = os.getenv("FAROL_TAILSCALE_IPV4", "").strip()
    if override:
        return override
    try:
        completed = subprocess.run(
            ["tailscale", "ip", "-4"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("FAROL_HOST=tailscale but Tailscale IPv4 was not found") from error
    ip = completed.stdout.strip().splitlines()[0].strip() if completed.stdout.strip() else ""
    if not ip:
        raise RuntimeError("FAROL_HOST=tailscale but Tailscale IPv4 was empty")
    return ip
