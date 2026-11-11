"""Compare saved local-model runs only when their inputs and checks match."""

import argparse
import hashlib
import html
import json
from collections import Counter
from pathlib import Path

from farol.live_simulation import save


def signature(report: dict) -> str:
    frozen = {key: report[key] for key in ("snapshot_sha256", "prompt_sha256", "grader_sha256")}
    frozen["guard_sha256"] = report["code_sha256"]["farol/narration_contract.py"]
    frozen["brain_sha256"] = report["code_sha256"]["farol/brain.py"]
    frozen["cases"] = [(row["id"], row["prompt_payload"], row["required_any"], row["check_claim_contract"])
                       for row in report["cases"]]
    return hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()


def compare(reports: list[dict]) -> dict:
    if len(reports) < 2 or len({signature(row) for row in reports}) != 1:
        raise ValueError("Comparison requires at least two runs with identical snapshots, prompts, guards, and cases")
    trials = [[(row["case"], row["repeat"]) for row in report["results"]] for report in reports]
    if any(row != trials[0] for row in trials):
        raise ValueError("Runs must contain the same cases and repeat counts")
    rows = []
    for report in reports:
        if not report.get("summary"):
            raise ValueError("Run is incomplete")
        results = report["results"]
        case_ids = [case["id"] for case in report["cases"]]
        counts = Counter((row["case"], row["repeat"]) for row in results)
        repeats = max((row["repeat"] for row in results), default=0)
        expected = {(ident, repeat) for ident in case_ids for repeat in range(1, repeats + 1)}
        if not expected or set(counts) != expected or any(count != 1 for count in counts.values()):
            raise ValueError("Run must contain every case exactly once per repeat")
        if report["summary"]["total"] != len(results):
            raise ValueError("Run summary does not match its results")
        rows.append({
            "model": report["profile"]["label"], "profile": report["profile"]["id"],
            **report["summary"], "generation_settings": report["generation_settings"],
            "manual_review": report.get("manual_review", {}),
            "reasoning_observed": sum(row.get("reasoning_present", False) for row in report["results"]),
            "raw_failures": [{"case": row["case"], "repeat": row["repeat"], "errors": row["errors"]}
                             for row in report["results"] if row["errors"]],
        })
    return {"input_signature": signature(reports[0]), "models": rows,
            "scope": "Same captured inputs and guard. Raw passes measure strict claim-contract compliance; valid paraphrases can fail. Guarded passes do not count as raw model successes. Manual review is still required.",
            "timing": "Complete HTTP response seconds, including reasoning. Warm cache may affect timing. Model-specific reasoning/token budgets are disclosed below."}


def render(comparison: dict, destination: Path) -> None:
    def esc(value):
        return html.escape(str(value), quote=True)
    rows = "".join(
        f"<tr><td>{esc(row['model'])}</td><td>{row['passed']}/{row['total']}</td>"
        f"<td>{row['guarded_passed']}/{row['total']}</td><td>{row['guard_interventions']}</td>"
        f"<td>{esc(row.get('manual_review', {}).get('factual_error_responses', 'not reviewed'))}</td>"
        f"<td>{row['median_seconds']}s</td><td>{row['max_seconds']}s</td>"
        f"<td>{row['reasoning_observed']}/{row['total']}</td></tr>" for row in comparison["models"])
    document = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Farol model comparison</title><style>body{background:#101820;color:#e7eff5;font:16px/1.6 system-ui;margin:32px auto;padding:0 20px;max-width:1100px}'
        'table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:12px;border-bottom:1px solid #39505f}.scroll{overflow:auto}'
        'pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#192a36;padding:20px;border-radius:10px}h1{font-size:34px}a{color:#92e4ce}</style>'
        '<h1>Gemma and Qwen: correctness first</h1>'
        f"<p>{esc(comparison['scope'])}</p><p>{esc(comparison['timing'])}</p>"
        '<div class="scroll"><table><thead><tr><th>Model</th><th>Raw checks</th><th>After guard</th><th>Guard changed</th><th>Factual / unsupported (review)</th><th>Median</th><th>Slowest</th><th>Reasoning observed</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></div>'
        '<p>Both runs passed the input-signature check: the snapshot, model prompt, claim guard, and case expectations match.</p>'
        f"<details><summary>Settings, failed checks, and reproducibility</summary><pre>{esc(json.dumps(comparison, indent=2))}</pre></details></html>"
    )
    destination.write_text(document, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare([json.loads(path.read_text(encoding="utf-8")) for path in args.reports])
    result["reports"] = [str(path.resolve()) for path in args.reports]
    save(args.output, result)
    render(result, args.output.with_suffix(".html"))
    print(json.dumps({"report": str(args.output.with_suffix('.html')), "models": result["models"]}))


if __name__ == "__main__":
    main()
