import argparse
import json

from app.config import get_settings
from app.repositories.embedding_jobs import (
    EmbeddingClaim,
    StaleEmbeddingClaimError,
    claim_next_embedding_item,
    complete_embedding_claim,
    fail_embedding_claim,
    get_embedding_job_summary,
    recover_expired_embedding_claims,
    release_unstarted_embedding_claim,
)
from app.repositories.usage import EmbeddingBudgetExceededError
from app.services.embedding_text import EMBEDDING_TASK_TYPE
from app.services.embeddings import get_or_create_embedding
from app.services.retries import is_retryable


def process_embedding_claim(claim: EmbeddingClaim) -> bool:
    label = (
        f"{claim.key.source_type}:{claim.key.source_id}"
    )

    try:
        result = get_or_create_embedding(
            claim.key,
            claim.prepared,
            job_id=claim.job_id,
            job_item_id=claim.item_id,
            attempt=claim.attempt,
        )

        complete_embedding_claim(
            claim,
            cache_hit=result.cache_hit,
        )

    except EmbeddingBudgetExceededError:
        try:
            release_unstarted_embedding_claim(claim)
        except StaleEmbeddingClaimError:
            print(f"{label}: claim expired before budget release")
        else:
            print(
                f"{label}: embedding allowance unavailable; "
                "item remains pending and attempt count restored"
            )

        return False

    except StaleEmbeddingClaimError:
        print(
            f"{label}: claim expired or ownership changed; "
            "completion was not recorded"
        )
        return False

    except Exception as error:
        error_type = type(error).__name__

        try:
            status = fail_embedding_claim(
                claim,
                retryable=is_retryable(error),
                error_type=error_type,
            )
        except StaleEmbeddingClaimError:
            print(
                f"{label}: {error_type}; "
                "claim ownership is no longer valid"
            )
        else:
            print(
                f"{label}: {error_type}; item status={status}"
            )

        return False

    print(
        f"{label}: completed; cache_hit={result.cache_hit}"
    )
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", default="demo")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--max-items", type=int, default=1)
    args = parser.parse_args()

    if not 1 <= args.max_items <= 1000:
        parser.error("--max-items must be between 1 and 1000")

    settings = get_settings()

    try:
        summary = get_embedding_job_summary(
            args.tenant_id,
            args.job_id,
        )
    except ValueError as error:
        parser.exit(1, f"{error}\n")

    # Check configuration before acquiring any claim.
    if (
        summary["model"] != settings.embedding_model
        or summary["dimensions"]
        != settings.embedding_dimensions
        or summary["task_type"] != EMBEDDING_TASK_TYPE
    ):
        parser.exit(
            1,
            "Job configuration differs from current embedding "
            "settings. Restore its settings or create a new job.\n",
        )

    recovery = recover_expired_embedding_claims(
        args.tenant_id,
        args.job_id,
    )
    print(f"Recovery: {json.dumps(recovery)}")

    claims_acquired = 0

    for _ in range(args.max_items):
        claim = claim_next_embedding_item(
            args.tenant_id,
            args.job_id,
        )

        if claim is None:
            print("No ready embedding items.")
            break

        claims_acquired += 1
        print(
            f"Processing {claim.key.source_type}:"
            f"{claim.key.source_id}, attempt {claim.attempt}"
        )

        if not process_embedding_claim(claim):
            print("Stopping after an unsuccessful attempt.")
            break

    print(f"Claims acquired this run: {claims_acquired}")
    print(json.dumps(
        get_embedding_job_summary(
            args.tenant_id,
            args.job_id,
        ),
        indent=2,
    ))


if __name__ == "__main__":
    main()