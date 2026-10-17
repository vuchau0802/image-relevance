import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from app import config, database
from app.repositories import embedding_jobs, jobs
from app.services.embedding_text import prepare_input
from scripts import demo_status, prepare_demo as preparation


def readiness(*, ready=False, image_pending=False):
    return {
        "ready": ready,
        "source_issues": (
            [{
                "source_type": "image",
                "source_id": "img_001",
                "reason": "status=pending",
            }]
            if image_pending else []
        ),
        "missing_current_embeddings": (
            [] if ready else [{
                "source_type": "post",
                "source_id": "post_001",
            }]
        ),
    }


@pytest.fixture
def preparation_context(monkeypatch):
    run_module = Mock()
    run_command = Mock(
        return_value=SimpleNamespace(returncode=0)
    )
    status = Mock(return_value=readiness(ready=True))

    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = (
        "existing-vision-job"
    )
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session

    create_vision = Mock(return_value="new-vision-job")
    create_embedding = Mock(return_value="embedding-job")
    snapshots = Mock(return_value=[
        (
            "post",
            "post_001",
            prepare_input("Subject: red fox"),
        )
    ])

    monkeypatch.setattr(
        preparation, "run_module", run_module
    )
    monkeypatch.setattr(
        preparation.subprocess, "run", run_command
    )
    monkeypatch.setattr(
        demo_status, "get_demo_readiness", status
    )
    monkeypatch.setattr(
        database, "SessionLocal", factory
    )
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            embedding_model="test-model",
            embedding_dimensions=2,
        ),
    )
    monkeypatch.setattr(
        jobs, "create_processing_job", create_vision
    )
    monkeypatch.setattr(
        embedding_jobs,
        "create_embedding_job",
        create_embedding,
    )
    monkeypatch.setattr(
        embedding_jobs, "snapshot_inputs", snapshots
    )

    return SimpleNamespace(
        run_module=run_module,
        run_command=run_command,
        status=status,
        session=session,
        create_vision=create_vision,
        create_embedding=create_embedding,
    )


def called_modules(ctx):
    return [
        call.args[0]
        for call in ctx.run_module.call_args_list
    ]


def test_ready_demo_does_not_run_workers(preparation_context):
    ctx = preparation_context

    assert preparation.prepare_demo(3, 10) is True

    assert called_modules(ctx) == [
        "alembic",
        "scripts.seed_images",
        "scripts.seed_posts",
    ]
    ctx.create_vision.assert_not_called()
    ctx.create_embedding.assert_not_called()


def test_failed_dataset_verification_runs_downloader(
    preparation_context,
):
    ctx = preparation_context
    ctx.run_command.side_effect = [
        SimpleNamespace(returncode=0),  # Docker startup
        SimpleNamespace(returncode=1),  # Dataset verification
    ]

    assert preparation.prepare_demo(3, 10) is True

    assert "scripts.download_dataset" in called_modules(ctx)


def test_missing_embeddings_run_bounded_worker(
    preparation_context,
):
    ctx = preparation_context
    ctx.status.side_effect = [
        readiness(),
        readiness(ready=True),
    ]

    assert preparation.prepare_demo(3, 10) is True

    ctx.run_module.assert_any_call(
        "app.workers.embedding_runner",
        "--job-id",
        "embedding-job",
        "--max-items",
        "10",
    )
    ctx.create_vision.assert_not_called()

    arguments = ctx.create_embedding.call_args.kwargs
    assert arguments["tenant_id"] == "demo"
    assert arguments["idempotency_key"].startswith(
        "demo-embeddings-"
    )


def test_unfinished_vision_stops_before_embedding_creation(
    preparation_context,
):
    ctx = preparation_context
    ctx.status.side_effect = [
        readiness(image_pending=True),
        readiness(image_pending=True),
    ]

    assert preparation.prepare_demo(3, 10) is False

    ctx.run_module.assert_any_call(
        "app.workers.runner",
        "--job-id",
        "existing-vision-job",
        "--max-items",
        "3",
    )
    ctx.create_vision.assert_not_called()
    ctx.create_embedding.assert_not_called()


def test_vision_then_embeddings_can_finish_preparation(
    preparation_context,
):
    ctx = preparation_context
    ctx.status.side_effect = [
        readiness(image_pending=True),
        readiness(),
        readiness(ready=True),
    ]

    assert preparation.prepare_demo(3, 10) is True

    modules = called_modules(ctx)
    assert modules.index("app.workers.runner") < modules.index(
        "app.workers.embedding_runner"
    )


def test_incomplete_embeddings_do_not_report_success(
    preparation_context,
):
    ctx = preparation_context
    ctx.status.side_effect = [
        readiness(),
        readiness(),
    ]

    assert preparation.prepare_demo(3, 10) is False


def test_worker_process_failure_propagates(
    preparation_context,
):
    ctx = preparation_context
    ctx.status.return_value = readiness()

    def run_module(module, *arguments):
        if module == "app.workers.embedding_runner":
            raise subprocess.CalledProcessError(
                1, ["fake-worker"]
            )

    ctx.run_module.side_effect = run_module

    with pytest.raises(subprocess.CalledProcessError):
        preparation.prepare_demo(3, 10)