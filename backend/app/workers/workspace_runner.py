import logging
import signal
import time
from threading import Event

from app.repositories.worker_queue import (
    ReadyWorkspaceJob,
    list_ready_workspace_jobs,
)
from app.workers.dispatcher import dispatch_workspace_job
from app.workers.file_cleanup import process_next_file_cleanup


logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = {
    "idle": 2,
    "deferred": 60,
    "configuration_mismatch": 300,
}


def run_worker(
    stop: Event,
    poll_seconds: float = 2,
) -> None:
    if not 0.1 <= poll_seconds <= 60:
        raise ValueError("poll_seconds must be between 0.1 and 60")

    cooldowns: dict[ReadyWorkspaceJob, float] = {}

    while not stop.is_set():
        now = time.monotonic()
        cooldowns = {
            candidate: deadline
            for candidate, deadline in cooldowns.items()
            if deadline > now
        }

        try:
            cleanup_outcome = process_next_file_cleanup()
            if cleanup_outcome != "idle":
                logger.info("Image file cleanup: %s", cleanup_outcome)
        except Exception as error:
            logger.warning(
                "Image file cleanup failed (%s)",
                type(error).__name__,
            )

        if stop.is_set():
            break

        try:
            candidates = list_ready_workspace_jobs(
                limit=20,
                exclude=set(cooldowns),
            )
        except Exception as error:
            logger.warning(
                "Queue discovery failed (%s); retrying later",
                type(error).__name__,
            )
            stop.wait(max(poll_seconds, 5))
            continue

        for candidate in candidates:
            if stop.is_set():
                break

            try:
                outcome = dispatch_workspace_job(candidate)
            except Exception as error:
                logger.warning(
                    "%s job %s dispatch failed (%s)",
                    candidate.kind,
                    candidate.job_id,
                    type(error).__name__,
                )
                cooldowns[candidate] = time.monotonic() + 30
                continue

            logger.info(
                "%s job %s: %s",
                candidate.kind,
                candidate.job_id,
                outcome,
            )

            delay = COOLDOWN_SECONDS.get(outcome)
            if delay is not None:
                cooldowns[candidate] = time.monotonic() + delay

        stop.wait(poll_seconds)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    stop = Event()

    def request_stop(signum, frame):
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    logger.info("Workspace worker started")
    try:
        run_worker(stop)
    finally:
        logger.info("Workspace worker stopped")


if __name__ == "__main__":
    main()