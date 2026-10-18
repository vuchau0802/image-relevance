import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess

from app.config import PROJECT_ROOT
from app.database import SessionLocal
from app.models import Post
from app.repositories.embedding_jobs import snapshot_inputs
from app.schemas.post import PostInput
from scripts.evaluate_matching import evaluate_group
from scripts.seed_heldout import load_frozen_cases


def verify_baseline_code(baseline):
    commit = baseline["code_commit"]

    if not isinstance(commit, str) or not re.fullmatch(
        r"[0-9a-fA-F]{40,64}", commit
    ):
        raise ValueError("Invalid baseline commit")

    protected_paths = [
        "backend/app",
        "backend/requirements.txt",
    ]

    comparison = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            commit,
            "--",
            *protected_paths,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
    )

    if comparison.returncode != 0:
        raise ValueError(
            "Implementation differs from the frozen baseline, "
            "or Git could not verify it"
        )

    untracked = subprocess.run(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            *protected_paths,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    if untracked.stdout.strip():
        raise ValueError(
            "Untracked implementation files prevent baseline verification"
        )


def verify_stored_posts(posts):
    with SessionLocal() as session:
        for expected in posts:
            record = session.get(
                Post,
                ("demo", expected.id),
            )

            if record is None:
                raise ValueError(
                    f"Evaluation post is missing: {expected.id}"
                )

            actual = PostInput(
                id=record.id,
                title=record.title,
                content=record.content,
                required_subject=record.required_subject,
            )

            if actual != expected:
                raise ValueError(
                    f"Stored post differs from frozen text: {expected.id}"
                )

        snapshots = snapshot_inputs(session, "demo")

    evaluated_ids = {post.id for post in posts}

    return [
        {
            "source_type": source_type,
            "source_id": source_id,
            "input_hash": prepared.input_hash,
        }
        for source_type, source_id, prepared in snapshots
        if source_type == "image" or source_id in evaluated_ids
    ]


def add_rates(group):
    def ratio(numerator, denominator):
        return numerator / denominator if denominator else None

    return {
        **group,
        "top1_match_rate": ratio(
            group["correct_top_matches"],
            group["matchable_cases"],
        ),
        "coverage": ratio(
            group["accepted_predictions"],
            group["total"],
        ),
        "correct_no_match_rejection_rate": ratio(
            group["correct_rejections"],
            group["no_match_cases"],
        ),
    }


def main():
    output = (
        PROJECT_ROOT
        / "data"
        / "processed"
        / "heldout_evaluation.json"
    )

    if output.exists():
        raise FileExistsError(
            "The first evaluation report already exists. "
            "Preserve it; do not overwrite it."
        )

    cases, baseline, posts = load_frozen_cases()
    verify_baseline_code(baseline)
    snapshots = verify_stored_posts(posts)

    image_ids = {
        item["source_id"]
        for item in snapshots
        if item["source_type"] == "image"
    }

    for case in cases:
        if not set(case["acceptable_image_ids"]) <= image_ids:
            raise ValueError(
                f"Referenced completed images are missing: {case['id']}"
            )

    evaluation_cases = [
        {
            "post_id": case["id"],
            "acceptable_image_ids": case["acceptable_image_ids"],
        }
        for case in cases
    ]

    # Uses cached rankings only. Incomplete rankings abort the report.
    group = add_rates(evaluate_group(
        evaluation_cases,
        tenant_id="demo",
    ))

    snapshot_bytes = json.dumps(
        sorted(
            snapshots,
            key=lambda item: (
                item["source_type"],
                item["source_id"],
            ),
        ),
        sort_keys=True,
    ).encode("utf-8")

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "baseline": baseline,
        "source_snapshot_sha256": hashlib.sha256(
            snapshot_bytes
        ).hexdigest(),
        "source_snapshots": snapshots,
        "limitation": (
            "Assistant-authored new queries, user-reviewed labels, "
            "and the existing development corpus. "
            "Not an independently authored benchmark."
        ),
        "evaluation": group,
    }

    output.parent.mkdir(parents=True, exist_ok=True)

    # Exclusive creation preserves any existing first-run report.
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")

    print(f"Threshold: {baseline['min_match_similarity']}")
    print(f"Cases passed: {group['passed']} / {group['total']}")
    print(
        "Correct top matches: "
        f"{group['correct_top_matches']} / "
        f"{group['matchable_cases']}"
    )
    print(
        "Accepted top-prediction precision: "
        f"{group['accepted_top_precision']}"
    )
    print(f"Coverage: {group['coverage']}")
    print(
        "Correct no-match rejections: "
        f"{group['correct_rejections']} / "
        f"{group['no_match_cases']}"
    )
    print(f"False rejections: {group['false_rejections']}")
    print(
        f"Incorrect acceptances: {group['incorrect_acceptances']}"
    )
    print(f"Saved report: {output}")


if __name__ == "__main__":
    main()