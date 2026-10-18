import argparse
import json

from app.repositories.context import (
    get_current_image_context,
    get_current_post_context,
)
from app.services.context_guard import assess_context
from app.services.ranking import rank_post_images


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", default="demo")
    parser.add_argument("--post-id", required=True)
    parser.add_argument("--version", default="manual-v2-pilot")
    args = parser.parse_args()

    requirements = get_current_post_context(
        args.tenant_id, args.post_id, args.version
    )

    if requirements is None:
        parser.exit(1, "Current reviewed post context is missing.\n")

    result = rank_post_images(
        tenant_id=args.tenant_id,
        post_id=args.post_id,
        top=50,
    )

    checks = []
    supported = []
    has_unknown = False

    for candidate in result["results"]:
        evidence = get_current_image_context(
            args.tenant_id,
            candidate["image_id"],
            args.version,
        )

        decision = assess_context(
            requirements,
            evidence if evidence is not None else [],
        )

        checks.append({
            "image_id": candidate["image_id"],
            "context_status": decision.status,
            "reasons": list(decision.reasons),
        })

        if decision.matches:
            supported.append(candidate)
        elif decision.status == "unknown":
            has_unknown = True

    # Preserve incomplete and unsupported results from the original ranker.
    if result["status"] == "matched":
        if has_unknown:
            result["status"] = "incomplete"
            result["reason"] = (
                "Some threshold-passing candidates lack sufficient "
                "reviewed context evidence."
            )
            supported = []
        elif supported:
            result["reason"] = (
                "Images passed subject, similarity, and context checks."
            )
        else:
            result["status"] = "no_confident_match"
            result["reason"] = (
                "All threshold-passing candidates contradicted "
                "the required context."
            )

    result["results"] = supported
    result["context_version"] = args.version
    result["context_checks"] = checks
    result["scope"] = "Development pilot; not held-out evaluation."

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()