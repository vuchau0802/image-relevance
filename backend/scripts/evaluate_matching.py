"""Evaluate cached rankings without calling Gemini or tuning thresholds."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.services.ranking import rank_post_images


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def evaluate_group(cases, tenant_id, ranker=rank_post_images):
    rows = []
    seen = set()
    for case in cases:
        post_id = case["post_id"]
        acceptable = case["acceptable_image_ids"]
        if post_id in seen:
            raise ValueError(f"Duplicate evaluation post: {post_id}")
        seen.add(post_id)
        result = ranker(tenant_id=tenant_id, post_id=post_id, top=1)
        if result["status"] not in {"matched", "no_confident_match"}:
            raise ValueError(
                f"Cannot evaluate {post_id}: {result['status']}"
            )
        predictions = result["results"]
        matched = result["status"] == "matched"
        if matched != bool(predictions):
            raise ValueError(f"Inconsistent ranking response for {post_id}")
        best = predictions[0] if predictions else None
        correct_match = (
            matched and best["image_id"] in acceptable
        )
        passed = (
            correct_match if acceptable else not matched
        )
        rows.append({
            "post_id": post_id,
            "acceptable_image_ids": acceptable,
            "expected_status": "matched" if acceptable else "no_confident_match",
            "actual_status": result["status"],
            "actual_image_id": best["image_id"] if best else None,
            "similarity": best["similarity"] if best else None,
            "reason": result["reason"],
            "passed": passed,
        })

    if not rows:
        raise ValueError("Evaluation cases must not be empty")
    positives = [row for row in rows if row["acceptable_image_ids"]]
    negatives = [row for row in rows if not row["acceptable_image_ids"]]
    accepted = [row for row in rows if row["actual_status"] == "matched"]
    correct = sum(row["passed"] for row in accepted)
    return {
        "total": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "matchable_cases": len(positives),
        "correct_top_matches": sum(row["passed"] for row in positives),
        "no_match_cases": len(negatives),
        "correct_rejections": sum(row["passed"] for row in negatives),
        "accepted_predictions": len(accepted),
        "incorrect_acceptances": len(accepted) - correct,
        "false_rejections": sum(
            row["actual_status"] == "no_confident_match" for row in positives
        ),
        "accepted_top_precision": correct / len(accepted) if accepted else None,
        "rows": rows,
    }


def main():
    sources = {}
    for name in ("calibration", "evaluation"):
        raw = (PROJECT_ROOT / "data" / f"{name}.json").read_bytes()
        sources[name] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "cases": json.loads(raw.decode("utf-8-sig")),
        }

    calibration = sources["calibration"]["cases"]
    if not calibration or any(case.get("reviewed") is not True for case in calibration):
        raise ValueError("All calibration cases must be reviewed")
    for case in calibration:
        ids = case["acceptable_image_ids"]
        expected = case["expected_status"]
        if expected not in {"match", "no_confident_match"} or (
            (expected == "match") != bool(ids)
        ):
            raise ValueError(f"Inconsistent calibration label: {case['id']}")

    calibration_cases = [
        {"post_id": case["id"], "acceptable_image_ids": case["acceptable_image_ids"]}
        for case in calibration
    ]
    regression_cases = [
        {
            "post_id": case["post_id"],
            "acceptable_image_ids": (
                [case["correct_image_id"]]
                if case["correct_image_id"] is not None else []
            ),
        }
        for case in sources["evaluation"]["cases"]
    ]
    if {case["post_id"] for case in calibration_cases} & {
        case["post_id"] for case in regression_cases
    }:
        raise ValueError("Calibration and regression post IDs overlap")

    settings = get_settings()
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tenant_id": "demo",
        "model": settings.embedding_model,
        "dimensions": settings.embedding_dimensions,
        "task_type": "SEMANTIC_SIMILARITY",
        "min_match_similarity": settings.min_match_similarity,
        "label_file_sha256": {
            name: source["sha256"] for name, source in sources.items()
        },
        "limitation": (
            "Calibration and development-influenced regression examples; "
            "not independent held-out accuracy. No threshold tuning is performed."
        ),
        "calibration": evaluate_group(calibration_cases, "demo"),
        "regression": evaluate_group(regression_cases, "demo"),
    }
    output = PROJECT_ROOT / "data" / "processed" / "matching_evaluation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Threshold: {report['min_match_similarity']}")
    for name in ("calibration", "regression"):
        group = report[name]
        print(f"{name.capitalize()}: {group['passed']} / {group['total']}")
    print(f"Saved report: {output}")


if __name__ == "__main__":
    main()
