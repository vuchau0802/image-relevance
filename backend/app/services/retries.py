import time
from collections.abc import Callable
from typing import TypeVar
from google.genai._gaos.lib.compat_errors import APIConnectionError
import httpx
from pydantic import ValidationError


T = TypeVar("T")


class InvalidModelResponseError(Exception):
    pass


def is_retryable(error: Exception) -> bool:
    if isinstance(
        error,
        (
            APIConnectionError,
            httpx.TransportError,
            TimeoutError,
            ValidationError,
            InvalidModelResponseError,
        ),
    ):
        return True

    # Support status information exposed by different SDK errors.
    response = getattr(error, "response", None)
    status = getattr(error, "status_code", None)

    if status is None:
        status = getattr(error, "code", None)

    if status is None:
        status = getattr(response, "status_code", None)

    return status in {408, 429, 500, 502, 503, 504}


def run_with_retries(
    operation: Callable[[], T],
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> T:
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