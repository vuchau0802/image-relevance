import time
from collections.abc import Callable
from typing import TypeVar
import httpx
from pydantic import ValidationError


T = TypeVar("T")


class InvalidModelResponseError(Exception):
    pass


def is_retryable(error: Exception) -> bool:
    # SDK wrappers preserve transport exceptions in their public cause chain.
    pending = [error]
    seen = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        response = getattr(current, "response", None)
        status = getattr(current, "status_code", None)
        if status is None:
            status = getattr(current, "code", None)
        if status is None:
            status = getattr(response, "status_code", None)
        if isinstance(status, int) and status >= 400:
            return status in {408, 429, 500, 502, 503, 504}
        if isinstance(current, (
            httpx.TransportError, TimeoutError, ConnectionError,
            ValidationError, InvalidModelResponseError,
        )):
            return True
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        elif not current.__suppress_context__ and current.__context__ is not None:
            pending.append(current.__context__)
    return False


def run_with_retries(
    operation: Callable[[], T],
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> T:
    """Synchronous retry helper for process_one; workers use persistent jobs."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    if base_delay < 0:
        raise ValueError("base_delay cannot be negative")

    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as error:
            if not is_retryable(error) or attempt == max_attempts:
                raise

            delay = base_delay * (2 ** (attempt - 1))
            time.sleep(delay)

    raise RuntimeError("Retry loop ended unexpectedly")
