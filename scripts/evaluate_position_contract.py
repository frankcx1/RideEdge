"""Evaluate the strict positioning contract against the six frozen public starts.

Offline by default; --run enables six cooperative local-model calls. No retries,
provider calls, phone changes or production publication. Existing results frozen.
"""

import argparse
import json
from pathlib import Path

from farol import local, local_runtime, prompt_budget, radar
from farol import position_contract as contract
from farol.besttime import save
from farol.env import load_env
from scripts.research_seattle_positions import ORIGINS

DIRECTORY = Path(".cache/research/seattle-positions-2026-10-26/analysis-final")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument(
        "--repair",
        action="store_true",
        help="One correction of rejected answers; preserves first results",
    )
    args = parser.parse_args()
    load_env()
    requests = []
    suffix = "contract-repair" if args.repair else "contract"
    for aid in ORIGINS:
        if (DIRECTORY / f"{aid}-{suffix}-result.json").exists():
            continue
        if args.repair:
            previous = json.loads(
                (DIRECTORY / f"{aid}-contract-result.json").read_text(encoding="utf-8")
            )
            if not previous["validation_error"]:
                continue
            original = json.loads(
                (DIRECTORY / f"{aid}-contract-input.json").read_text(encoding="utf-8")
            )
            ledger = json.loads(
                (DIRECTORY / f"{aid}-contract-ledger.json").read_text(encoding="utf-8")
            )
            user = json.dumps(
                {
                    "evidence": json.loads(original["user"]),
                    "previous_answer": previous["answer"],
                    "validation_error": previous["validation_error"],
                    "task": "Correct the rejected decision once using the same evidence. You may reconsider any choice. No preferred destination is supplied.",
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            spec, aliases = original["schema"], original["aliases"]
            budget = prompt_budget.enforce(
                [{"role": "system", "content": contract.SYSTEM}, {"role": "user", "content": user}],
                spec,
                thinking=False,
                output_tokens=400,
            )
            save(
                DIRECTORY / f"{aid}-{suffix}-input.json",
                {
                    "system": contract.SYSTEM,
                    "user": user,
                    "schema": spec,
                    "budget": budget,
                    "aliases": aliases,
                    "mode": "historical replay only",
                },
            )
            requests.append((aid, ledger, user, spec, aliases))
            print(aid, budget["input_tokens"], flush=True)
            continue
        source = json.loads((DIRECTORY / f"{aid}-model-input.json").read_text(encoding="utf-8"))
        briefs = json.loads((DIRECTORY / f"{aid}-briefs.json").read_text(encoding="utf-8"))
        ledger = contract.build(source, briefs, enabled=True)
        data, aliases = contract.model_data(ledger)
        spec = contract.schema(ledger)
        for field in ("support_ids", "alternative_support_ids"):
            spec["properties"][field]["items"]["enum"] = [
                aliases[e] for e in spec["properties"][field]["items"]["enum"] if e in aliases
            ] or ["none"]
        user = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        budget = prompt_budget.enforce(
            [{"role": "system", "content": contract.SYSTEM}, {"role": "user", "content": user}],
            spec,
            thinking=False,
            output_tokens=400,
        )
        save(DIRECTORY / f"{aid}-contract-ledger.json", ledger)
        save(
            DIRECTORY / f"{aid}-contract-input.json",
            {
                "system": contract.SYSTEM,
                "user": user,
                "schema": spec,
                "budget": budget,
                "aliases": aliases,
                "mode": "historical replay only",
            },
        )
        requests.append((aid, ledger, user, spec, aliases))
        print(aid, budget["input_tokens"], flush=True)
    if not args.run or not requests:
        return
    endpoint, alias = local_runtime.settings()
    with local_runtime.session(endpoint, alias, job_kind="radar-plan"):
        for aid, ledger, user, spec, aliases in requests:
            raw, mode, at = local.complete(
                system=contract.SYSTEM,
                user=user,
                cache_key=suffix + "-study-" + aid,
                endpoint=endpoint,
                model_name=alias,
                model_profile="qwen",
                response_schema=spec,
                enable_thinking=False,
                max_tokens=400,
                timeout=50,
            )
            answer = local.narration_from_payload(raw)
            reverse = {v: k for k, v in aliases.items()}
            translated = {
                **answer,
                **{
                    key: [reverse.get(e, e) for e in answer.get(key, [])]
                    for key in ("support_ids", "alternative_support_ids")
                },
            }
            try:
                card = contract.validate(
                    ledger, translated, now=radar.stamp(ledger["decision_time"])
                )
                error = None
            except ValueError as exc:
                card, error = None, str(exc)
            save(
                DIRECTORY / f"{aid}-{suffix}-result.json",
                {
                    "raw_result": raw,
                    "answer": answer,
                    "translated": translated,
                    "card": card,
                    "validation_error": error,
                    "mode": mode,
                    "at": at,
                    "replay_note": "Validated against frozen decision time; never current driver guidance",
                },
            )
            print(
                json.dumps({"origin": aid, "answer": answer, "card": card, "error": error}),
                flush=True,
            )
    save(DIRECTORY / f"{suffix}-cleanup.json", local_runtime.cleanup_status())


if __name__ == "__main__":
    main()
