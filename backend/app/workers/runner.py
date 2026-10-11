import argparse
import hashlib
import json
import time

from PIL import Image as PillowImage

from app.config import PROJECT_ROOT, get_settings
from app.repositories.jobs import (
    StaleClaimError,
    claim_next_item,
    complete_claim,
    fail_claim,
    get_job_summary,
    recover_expired_claims,
)
from app.services.retries import is_retryable
from app.services.vision import process_image


def verify_file(claimed):
    image_path = (PROJECT_ROOT / claimed.file_path).resolve()
    images_folder = (PROJECT_ROOT / "data" / "images").resolve()

    if not image_path.is_relative_to(images_folder):
        raise ValueError("Image path is outside the corpus folder")

    checksum = hashlib.sha256(image_path.read_bytes()).hexdigest()

    if checksum != claimed.checksum:
        raise ValueError("Image file differs from its registered checksum")

    return image_path


def process_claim(claimed, settings):
    """Return True after saving a result; False after a failed attempt."""
    print(
        f"Processing {claimed.image_id}, "
        f"attempt {claimed.attempt}"
    )

    try:
        image_path = verify_file(claimed)

        with PillowImage.open(image_path) as image:
            image.verify()

        result = process_image(
            image_path,
            tenant_id=claimed.tenant_id,
            job_id=claimed.job_id,
            job_item_id=claimed.item_id,
            attempt=claimed.attempt,
        )

        verify_file(claimed)

        complete_claim(
            claimed,
            result,
            vision_model=settings.vision_model,
        )

        print(
            f"{claimed.image_id}: {result.status}; "
            f"subject={result.metadata.subject}"
        )
        return True

    except StaleClaimError:
        print("Ownership expired; result was not saved.")
        return False

    except Exception as error:
        try:
            fail_claim(
                claimed,
                error,
                retryable=is_retryable(error),
            )
            print(
                f"{claimed.image_id}: "
                f"attempt failed ({type(error).__name__})"
            )
        except StaleClaimError:
            print("Ownership expired; recovery will handle the item.")

        return False


def main():
    parser = argparse.ArgumentParser(
        description="Process a limited number of job items."
    )
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--tenant-id", default="demo")
    parser.add_argument("--max-items", type=int, default=1)
    args = parser.parse_args()

    if not 1 <= args.max_items <= 50:
        parser.error("--max-items must be between 1 and 50")

    settings = get_settings()
    attempts_started = 0

    for index in range(args.max_items):
        recovery = recover_expired_claims(
            args.tenant_id,
            args.job_id,
        )
        print("Recovery:", json.dumps(recovery))

        claimed = claim_next_item(
            args.tenant_id,
            args.job_id,
            lease_seconds=120,
        )

        if claimed is None:
            print("No item is ready for processing.")
            break

        attempts_started += 1
        succeeded = process_claim(claimed, settings)

        if not succeeded:
            print("Stopping this run after an unsuccessful attempt.")
            break

        if index + 1 < args.max_items:
            time.sleep(2)

    print(f"Attempts started this run: {attempts_started}")

    summary = get_job_summary(
        args.tenant_id,
        args.job_id,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()