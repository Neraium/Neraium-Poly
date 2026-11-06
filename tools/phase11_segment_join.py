"""Descriptive post-hoc category audit; acquired tags never become model features."""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def compare(models_path, segments_path):
    models = json.loads(models_path.read_text())
    segments = json.loads(segments_path.read_text())
    tags = {r["token_id"]: r["segment"] for r in segments["observations"]}
    groups = defaultdict(list)
    for token, result in models.get("heldout_by_token", {}).items():
        groups[tags.get(token, "Unknown")].append(result)
    rows = []
    for category, items in sorted(groups.items()):
        count = sum(r["count"] for r in items)
        mark_names = sorted(items[0]["metrics"]["horizon_mark"])
        direction_names = sorted(items[0]["metrics"]["directional_probability"])
        rows.append(
            {
                "segment": category,
                "heldout_labels": count,
                "tokens": len(items),
                "heldout_mae": {
                    name: sum(r["metrics"]["horizon_mark"][name]["mae"] * r["count"] for r in items) / count
                    for name in mark_names
                },
                "directional_brier": {
                    name: sum(
                        r["metrics"]["directional_probability"][name]["brier"] * r["count"] for r in items
                    )
                    / count
                    for name in direction_names
                },
                "independent_confidence_interval": None,
                "cost_adjusted_advantage": None,
            }
        )
    assert sum(r["heldout_labels"] for r in rows) == models["results"]["heldout"]["count"]
    return {
        "schema_version": "1.0",
        "hypothesis": "Describe model errors across all available categories; no subgroup selection, fitting or trading rule",
        "dataset_sha256": models["spec"]["dataset_sha256"],
        "source_model_sha256": hashlib.sha256(models_path.read_bytes()).hexdigest(),
        "source_segments_sha256": hashlib.sha256(segments_path.read_bytes()).hexdigest(),
        "source_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "split_intervals": {
            k: models["spec"][k] for k in ["training_interval", "validation_interval", "heldout_interval"]
        },
        "rows": rows,
        "limitations": [
            "Current tags were acquired after model observations; descriptive grouping only, not point-in-time features",
            "Tokens absent from the captured current universe remain Unknown",
            "Quote labels overlap and event independence is unreviewed; confidence intervals and executable advantage unavailable",
        ],
        "certification_authority": False,
        "automatic_promotion": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--segments", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.models, args.segments)
    with args.output.open("x") as handle:
        handle.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
