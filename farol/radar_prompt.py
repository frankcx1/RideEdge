"""Lossless encoding of the radar's existing model-facing evidence projection."""
import copy
import json


def encode(payload: dict) -> str:
    """Share repeated source names/timestamps without dropping evidence or options.

    This encodes the existing bounded model projection, not raw provider records.
    Named dictionaries keep source identity and exact timestamp offsets inspectable.
    No ranking, selection, new time assumptions or token-based pruning occurs here.
    """
    data = copy.deepcopy(payload)
    places = data.get("places", {})
    if places:
        columns = list(next(iter(places.values())))
        if all(set(row) == set(columns) for row in places.values()):
            data["place_columns"] = columns
            data["places"] = {key: [row[column] for column in columns] for key, row in places.items()}
    intervals = data.get("intervals", [])
    if all(all(set(row) == {"id", "evidence"} for row in slot["options"])
           and len({row["id"] for row in slot["options"]}) == len(slot["options"]) for slot in intervals):
        for slot in intervals:
            slot["options"] = {row["id"]: row["evidence"] for row in slot["options"]}
        data["option_format"] = "Each interval's options map allowed place IDs to evidence IDs."
    evidence = data["evidence"].values()
    references = {}
    for fields, table_name, prefix in ((["source"], "sources", "s"),
                                        (["starts_at", "ends_at"], "times", "t")):
        values = sorted({row[field] for row in evidence for field in fields if isinstance(row.get(field), str)})
        table = {f"{prefix}{index}": value for index, value in enumerate(values)}
        aliases = {value: key for key, value in table.items()}
        for row in evidence:
            for field in fields:
                if isinstance(row.get(field), str):
                    row[field] = aliases[row[field]]
        data[table_name] = table
        references["evidence." + "/".join(fields)] = f"Look up the reference ID in {table_name}; values are unchanged."
    data["references"] = references
    # Share layouts for records with the same optional fields. The first value
    # selects a column list; remaining values follow it. Missing keys stay absent
    # and explicit nulls stay null; no source text or candidate is shortened.
    if data["evidence"]:
        layouts, layout_ids, rows = {}, {}, {}
        for eid, row in data["evidence"].items():
            columns = tuple(sorted(row))
            layout_id = layout_ids.setdefault(columns, f"l{len(layout_ids)}")
            layouts[layout_id] = list(columns)
            rows[eid] = [layout_id, *[row[column] for column in columns]]
        data["evidence_layouts"] = layouts
        data["evidence"] = rows
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
