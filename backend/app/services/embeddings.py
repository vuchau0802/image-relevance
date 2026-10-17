from contextlib import suppress
from dataclasses import dataclass
import hashlib
import logging
from uuid import uuid4

from google import genai
from google.genai import types

from app.config import get_settings
from app.repositories.ai_calls import finish_ai_call
from app.repositories.embeddings import (
    get_cached_embedding,
    save_cached_embedding,
)
from app.repositories.usage import reserve_embedding_call
from app.schemas.embedding import EmbeddingCacheKey
from app.services.embedding_text import PreparedEmbeddingInput
from app.services.embedding_vectors import (
    InvalidEmbeddingError,
    normalize_embedding,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    cache_hit: bool
    call_id: str | None


def get_or_create_embedding(
    key: EmbeddingCacheKey,
    prepared: PreparedEmbeddingInput,
    *,
    job_id: str | None = None,
    job_item_id: str | None = None,
    attempt: int | None = None,
) -> EmbeddingResult:
    attribution = (job_id, job_item_id, attempt)

    if any(value is not None for value in attribution):
        if (
            not isinstance(job_id, str)
            or not job_id.strip()
            or len(job_id) > 36
            or not isinstance(job_item_id, str)
            or not job_item_id.strip()
            or len(job_item_id) > 36
            or isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or attempt < 1
        ):
            raise ValueError(
                "Job attribution requires valid job_id, "
                "job_item_id, and a positive integer attempt"
)
    settings = get_settings()

    actual_hash = hashlib.sha256(
        prepared.text.encode("utf-8")
    ).hexdigest()

    if not prepared.text.strip():
        raise ValueError("Embedding text must not be blank")

    if (
        actual_hash != prepared.input_hash
        or actual_hash != key.input_hash
    ):
        raise ValueError("Embedding text and input hash differ")

    if (
        key.model != settings.embedding_model
        or key.dimensions != settings.embedding_dimensions
    ):
        raise ValueError(
            "Embedding key differs from configured model or dimensions"
        )

    cached = get_cached_embedding(key)

    if cached is not None:
        return EmbeddingResult(
            vector=cached,
            cache_hit=True,
            call_id=None,
        )

    call_id = str(uuid4())

    reserve_embedding_call(
        tenant_id=key.tenant_id,
        daily_limit=settings.embedding_daily_call_limit,
        call_record={
            "tenant_id": key.tenant_id,
            "call_id": call_id,
            "job_id": job_id,
            "job_item_id": job_item_id,
            "attempt": attempt,
            "image_id": (
                key.source_id
                if key.source_type == "image"
                else None
            ),
            "post_id": (
                key.source_id
                if key.source_type == "post"
                else None
            ),
            "operation": "embedding",
            "model": key.model,
            "status": "started",
            "estimated_cost_usd": 0.0,
            "cost_basis": (
                "Configured free-tier estimate; not verified billing"
            ),
        },
    )

    client = None

    try:
        client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(),
            http_options=types.HttpOptions(
                timeout=60_000,
                retry_options=types.HttpRetryOptions(attempts=0),
            ),
        )

        response = client.models.embed_content(
            model=key.model,
            contents=prepared.text,
            config=types.EmbedContentConfig(
                task_type=key.task_type,
                output_dimensionality=key.dimensions,
            ),
        )

        embeddings = response.embeddings

        if not embeddings or len(embeddings) != 1:
            raise InvalidEmbeddingError(
                "Expected exactly one embedding"
            )

        values = embeddings[0].values

        if values is None:
            raise InvalidEmbeddingError(
                "Embedding response contains no vector"
            )

        vector = normalize_embedding(values, key.dimensions)

    except BaseException as error:
        status = (
            "interrupted"
            if isinstance(error, (KeyboardInterrupt, SystemExit))
            else "failed"
        )

        try:
            finish_ai_call(
                key.tenant_id,
                call_id,
                status=status,
                error_type=type(error).__name__,
            )
        except Exception:
            logger.error(
                "Embedding audit finalization failed for call %s",
                call_id,
            )

        raise

    else:
        finish_ai_call(
            key.tenant_id,
            call_id,
            status="completed",
        )

    finally:
        if client is not None:
            with suppress(Exception):
                client.close()

    save_cached_embedding(key, vector)

    # Read the stored value because another request may have
    # inserted this exact cache key first.
    stored = get_cached_embedding(key)

    if stored is None:
        raise RuntimeError(
            "Embedding was not available after saving"
        )

    return EmbeddingResult(
        vector=stored,
        cache_hit=False,
        call_id=call_id,
    )