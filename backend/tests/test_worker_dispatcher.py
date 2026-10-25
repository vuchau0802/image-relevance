from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from app.repositories.worker_queue import ReadyWorkspaceJob
from app.workers import dispatcher


@pytest.fixture
def dispatch_context(monkeypatch):
    settings = SimpleNamespace(
        vision_model="test-vision",
        embedding_model="test-embedding",
        embedding_dimensions=2,
    )
    monkeypatch.setattr(
        dispatcher, "get_settings", lambda: settings
    )

    vision_claim = object()
    embedding_claim = object()

    ctx = SimpleNamespace(
        settings=settings,
        vision_claim=vision_claim,
        embedding_claim=embedding_claim,
        vision_recover=Mock(),
        vision_acquire=Mock(return_value=vision_claim),
        vision_process=Mock(return_value=True),
        embedding_summary=Mock(return_value={
            "model": "test-embedding",
            "dimensions": 2,
            "task_type": "SEMANTIC_SIMILARITY",
        }),
        embedding_recover=Mock(),
        embedding_acquire=Mock(return_value=embedding_claim),
        embedding_process=Mock(return_value=True),
    )

    monkeypatch.setattr(
        dispatcher.jobs,
        "recover_expired_claims",
        ctx.vision_recover,
    )
    monkeypatch.setattr(
        dispatcher.jobs,
        "claim_next_item",
        ctx.vision_acquire,
    )
    monkeypatch.setattr(
        dispatcher, "process_claim", ctx.vision_process
    )

    monkeypatch.setattr(
        dispatcher.embedding_jobs,
        "get_embedding_job_summary",
        ctx.embedding_summary,
    )
    monkeypatch.setattr(
        dispatcher.embedding_jobs,
        "recover_expired_embedding_claims",
        ctx.embedding_recover,
    )
    monkeypatch.setattr(
        dispatcher.embedding_jobs,
        "claim_next_embedding_item",
        ctx.embedding_acquire,
    )
    monkeypatch.setattr(
        dispatcher,
        "process_embedding_claim",
        ctx.embedding_process,
    )

    return ctx


@pytest.mark.parametrize("succeeded", [True, False])
def test_dispatches_one_vision_item_in_order(
    dispatch_context, succeeded
):
    ctx = dispatch_context
    ctx.vision_process.return_value = succeeded

    timeline = Mock()
    timeline.attach_mock(ctx.vision_recover, "recover")
    timeline.attach_mock(ctx.vision_acquire, "acquire")
    timeline.attach_mock(ctx.vision_process, "process")

    result = dispatcher.dispatch_workspace_job(
        ReadyWorkspaceJob("vision", "ws_owner", "vision-job")
    )

    assert result == ("processed" if succeeded else "deferred")
    assert timeline.mock_calls == [
        call.recover("ws_owner", "vision-job"),
        call.acquire("ws_owner", "vision-job"),
        call.process(ctx.vision_claim, ctx.settings),
    ]
    ctx.embedding_summary.assert_not_called()
    ctx.embedding_process.assert_not_called()


@pytest.mark.parametrize("succeeded", [True, False])
def test_dispatches_one_embedding_item_in_order(
    dispatch_context, succeeded
):
    ctx = dispatch_context
    ctx.embedding_process.return_value = succeeded

    timeline = Mock()
    timeline.attach_mock(ctx.embedding_summary, "summary")
    timeline.attach_mock(ctx.embedding_recover, "recover")
    timeline.attach_mock(ctx.embedding_acquire, "acquire")
    timeline.attach_mock(ctx.embedding_process, "process")

    result = dispatcher.dispatch_workspace_job(
        ReadyWorkspaceJob("embedding", "ws_owner", "embedding-job")
    )

    assert result == ("processed" if succeeded else "deferred")
    assert timeline.mock_calls == [
        call.summary("ws_owner", "embedding-job"),
        call.recover("ws_owner", "embedding-job"),
        call.acquire("ws_owner", "embedding-job"),
        call.process(ctx.embedding_claim),
    ]
    ctx.vision_acquire.assert_not_called()
    ctx.vision_process.assert_not_called()


@pytest.mark.parametrize("kind", ["vision", "embedding"])
def test_no_available_claim_returns_idle(dispatch_context, kind):
    ctx = dispatch_context
    ctx.vision_acquire.return_value = None
    ctx.embedding_acquire.return_value = None

    result = dispatcher.dispatch_workspace_job(
        ReadyWorkspaceJob(kind, "ws_owner", "test-job")
    )

    assert result == "idle"
    ctx.vision_process.assert_not_called()
    ctx.embedding_process.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "different-model"),
        ("dimensions", 3),
        ("task_type", "RETRIEVAL_DOCUMENT"),
    ],
)
def test_embedding_configuration_mismatch_prevents_claim(
    dispatch_context, field, value
):
    ctx = dispatch_context
    ctx.embedding_summary.return_value[field] = value

    result = dispatcher.dispatch_workspace_job(
        ReadyWorkspaceJob("embedding", "ws_owner", "test-job")
    )

    assert result == "configuration_mismatch"
    ctx.embedding_recover.assert_not_called()
    ctx.embedding_acquire.assert_not_called()
    ctx.embedding_process.assert_not_called()


def test_unknown_job_kind_is_rejected(dispatch_context):
    ctx = dispatch_context

    with pytest.raises(ValueError, match="Unsupported"):
        dispatcher.dispatch_workspace_job(
            ReadyWorkspaceJob("unknown", "ws_owner", "test-job")
        )

    ctx.vision_acquire.assert_not_called()
    ctx.embedding_acquire.assert_not_called()
    ctx.vision_process.assert_not_called()
    ctx.embedding_process.assert_not_called()