from datetime import datetime, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AICall


def finish_ai_call(tenant_id, call_id, *, status, input_tokens=None, output_tokens=None, error_type=None):
    if status not in {"completed", "needs_review", "failed", "interrupted"}:
        raise ValueError("Invalid AI call completion status")
    with SessionLocal.begin() as session:
        call = session.execute(
            select(AICall)
            .where(AICall.tenant_id == tenant_id, AICall.call_id == call_id)
            .with_for_update()
        ).scalar_one()
        call.status = status
        call.input_tokens = input_tokens
        call.output_tokens = output_tokens
        call.error_type = error_type
        call.finished_at = datetime.now(timezone.utc)
