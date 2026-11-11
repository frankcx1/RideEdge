"""Check staged text or an explicit package for known private values; print paths only.

This supplements human review, especially for screenshots and unknown binary formats.
It never modifies files or uploads them. Local .env and origin values are used only
as comparison inputs and are never printed.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def private_values(root: Path) -> set[str]:
    values = set()
    env = root / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            key, sep, raw = line.partition("=")
            value = raw.strip().strip("\"'")
            if sep and re.search(r"KEY|TOKEN|SECRET|PASSWORD", key, re.IGNORECASE) and len(value) >= 12:
                values.add(value)
    zones = root / "fixtures" / "zones.json"
    if zones.exists():
        origin = json.loads(zones.read_text(encoding="utf-8-sig")).get("origin", {})
        label = origin.get("label", "")
        if len(label) >= 12 and re.search(r"\d", label):
            values.add(label)
        for key in ("latitude", "longitude", "lat", "lon"):
            value = origin.get(key)
            if isinstance(value, (int, float)):
                values.update((str(value), f"{value:.3f}", f"{value:.4f}"))
    return values


def findings(data: bytes, known: set[str]) -> set[str]:
    text = data.decode("utf-8", errors="replace")
    issues = set()
    if any((re.search(r"(?<![\d.])" + re.escape(value) + r"(?![\d.])", text)
            if re.fullmatch(r"-?\d+\.\d+", value) else value in text) for value in known):
        issues.add("known private value")
    if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", text):
        issues.add("private key")
    if re.search(r"\bAIza[0-9A-Za-z_-]{30,}\b", text):
        issues.add("Google credential")
    if re.search(r"\b(?:sk-|ghp_|gho_)[A-Za-z0-9_-]{24,}\b", text):
        issues.add("credential pattern")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    known = private_values(ROOT)
    if args.paths:
        files = [p for arg in args.paths for p in (arg.rglob("*") if arg.is_dir() else [arg]) if p.is_file()]
        inputs = [(str(p), p.read_bytes()) for p in files]
    else:
        names = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"], cwd=ROOT).decode().split("\0")
        inputs = [(name, subprocess.check_output(["git", "show", f":{name}"], cwd=ROOT)) for name in names if name]
    failures = 0
    for name, data in inputs:
        issues = findings(name.encode() + b"\n" + data, known)
        if issues:
            failures += 1
            print(f"REVIEW {name}: {', '.join(sorted(issues))}")
    print(f"Checked {len(inputs)} files; {failures} require review. Binary/image privacy still requires human review.")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
