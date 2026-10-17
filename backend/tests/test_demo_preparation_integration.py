"""Fresh miniature corpus through real persistence/workers; fake provider only."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image as PillowImage
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import config, database
from app.models import AICall, EmbeddingJob, EmbeddingJobItem, Image, JobItem, Post
from app.repositories import ai_calls, embedding_jobs, embeddings, jobs, usage
from app.schemas.image import ImageMetadata
from app.services import embeddings as embedding_service
from app.services import image_files, ranking, vision
from app.workers import embedding_runner, runner
from scripts import demo_status, prepare_demo, seed_images, seed_posts


pytestmark = pytest.mark.integration


@pytest.fixture
def fresh_demo(monkeypatch, tmp_path):
    connection = database.engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        # Never erase another test's committed data to simulate freshness.
        with factory() as session:
            assert session.scalar(select(Image.id).where(Image.tenant_id == "demo").limit(1)) is None
            assert session.scalar(select(Post.id).where(Post.tenant_id == "demo").limit(1)) is None
            assert session.scalar(select(EmbeddingJob.id).where(EmbeddingJob.tenant_id == "demo").limit(1)) is None

        data = tmp_path / "data"
        image_directory = data / "images"
        image_directory.mkdir(parents=True)
        PillowImage.new("RGB", (8, 8), "orange").save(image_directory / "img_test.jpg")
        (data / "manifest.json").write_text(json.dumps([{
            "id": "img_test",
            "filename": "img_test.jpg",
            "source_url": "https://example.com/image",
            "creator": "Test fixture",
            "license_url": "https://example.com/license",
        }]), encoding="utf-8")
        (data / "posts.json").write_text(json.dumps([
            {
                "id": "post_fox",
                "title": "Red foxes outdoors",
                "content": "A red fox standing outdoors.",
                "required_subject": "red fox",
            },
            {
                "id": "post_penguin",
                "title": "Emperor penguins",
                "content": "Emperor penguins standing on Antarctic ice.",
                "required_subject": "emperor penguin",
            },
        ]), encoding="utf-8")

        settings = SimpleNamespace(
            gemini_api_key=SimpleNamespace(get_secret_value=lambda: "fake-test-key"),
            vision_model="test-vision",
            min_classification_confidence=0.7,
            vision_daily_call_limit=10,
            embedding_model="test-embedding",
            embedding_dimensions=2,
            embedding_daily_call_limit=10,
            min_match_similarity=0.85,
        )
        for module in (
            database, ai_calls, embedding_jobs, embeddings, jobs, usage,
            seed_images, seed_posts, demo_status, ranking,
        ):
            monkeypatch.setattr(module, "SessionLocal", factory)
        for module in (
            config, embedding_jobs, embedding_service, vision,
            runner, embedding_runner, demo_status, ranking,
        ):
            monkeypatch.setattr(module, "get_settings", lambda: settings)
        for module in (seed_images, seed_posts, demo_status, image_files):
            monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)

        metadata = ImageMetadata(
            subject="red fox", category="animal", attributes=["orange fur"],
            caption="A red fox standing outdoors.", confidence=0.99,
        )
        vision_response = SimpleNamespace(
            output_text=metadata.model_dump_json(),
            usage=SimpleNamespace(total_input_tokens=10, total_output_tokens=10),
        )
        client = Mock()
        client.interactions.create.return_value = vision_response
        client.models.embed_content.return_value = SimpleNamespace(
            embeddings=[SimpleNamespace(values=[1.0, 0.0])]
        )
        # Both services use this shared google.genai module.
        monkeypatch.setattr(vision.genai, "Client", Mock(return_value=client))
        monkeypatch.setattr(
            prepare_demo.subprocess, "run",
            Mock(return_value=SimpleNamespace(returncode=0)),
        )

        def dispatch(module, *arguments):
            if module == "alembic":
                # The integration runner has already migrated the test DB.
                assert arguments == ("upgrade", "head")
            elif module == "scripts.seed_images":
                seed_images.main()
            elif module == "scripts.seed_posts":
                seed_posts.main()
            elif module in {"app.workers.runner", "app.workers.embedding_runner"}:
                with monkeypatch.context() as invocation:
                    invocation.setattr("sys.argv", [module, *arguments])
                    if module == "app.workers.runner":
                        runner.main()
                    else:
                        embedding_runner.main()
            else:
                raise AssertionError(f"Unexpected external command: {module}")

        monkeypatch.setattr(prepare_demo, "run_module", dispatch)
        yield SimpleNamespace(
            factory=factory, settings=settings, client=client,
            vision_response=vision_response,
        )
    finally:
        transaction.rollback()
        connection.close()


def test_fresh_corpus_preparation_produces_rankable_data(fresh_demo):
    ctx = fresh_demo
    assert prepare_demo.prepare_demo(1, 10) is True
    assert demo_status.get_demo_readiness()["ready"] is True

    fox = ranking.rank_post_images("demo", "post_fox")
    penguin = ranking.rank_post_images("demo", "post_penguin")
    assert fox["status"] == "matched"
    assert fox["results"][0]["image_id"] == "img_test"
    assert penguin["status"] == "no_confident_match"
    assert penguin["results"] == []
    assert ctx.client.interactions.create.call_count == 1
    assert ctx.client.models.embed_content.call_count == 3

    with ctx.factory() as session:
        calls = session.scalars(select(AICall).where(AICall.tenant_id == "demo")).all()
        assert len(calls) == 4
        assert all(call.status == "completed" for call in calls)
        assert all(call.job_id and call.job_item_id and call.attempt == 1 for call in calls)

    # A repeated preparation must not generate additional provider requests.
    assert prepare_demo.prepare_demo(1, 10) is True
    assert ctx.client.interactions.create.call_count == 1
    assert ctx.client.models.embed_content.call_count == 3


def test_fresh_preparation_resumes_after_embedding_budget_block(fresh_demo):
    ctx = fresh_demo
    ctx.settings.embedding_daily_call_limit = 0
    assert prepare_demo.prepare_demo(1, 10) is False
    assert demo_status.get_demo_readiness()["ready"] is False
    assert ctx.client.interactions.create.call_count == 1
    ctx.client.models.embed_content.assert_not_called()

    with ctx.factory() as session:
        job_ids = list(session.scalars(select(EmbeddingJob.id).where(EmbeddingJob.tenant_id == "demo")))
        items = session.scalars(select(EmbeddingJobItem).where(EmbeddingJobItem.tenant_id == "demo")).all()
        assert len(job_ids) == 1
        assert len(items) == 3
        assert all(item.status == "pending" and item.attempts == 0 for item in items)

    ctx.settings.embedding_daily_call_limit = 10
    assert prepare_demo.prepare_demo(1, 10) is True
    assert ctx.client.interactions.create.call_count == 1
    assert ctx.client.models.embed_content.call_count == 3
    with ctx.factory() as session:
        assert list(session.scalars(select(EmbeddingJob.id).where(EmbeddingJob.tenant_id == "demo"))) == job_ids


def test_fresh_preparation_resumes_persisted_vision_retry(fresh_demo):
    ctx = fresh_demo
    ctx.client.interactions.create.side_effect = [TimeoutError("simulated"), ctx.vision_response]
    assert prepare_demo.prepare_demo(1, 10) is False
    ctx.client.models.embed_content.assert_not_called()

    with ctx.factory.begin() as session:
        item = session.execute(select(JobItem).where(JobItem.tenant_id == "demo")).scalar_one()
        assert item.status == "pending"
        assert item.attempts == 1
        # Move past the backoff without sleeping or changing attempt history.
        from sqlalchemy import func
        item.available_at = func.clock_timestamp()
        original_job_id = item.job_id

    assert prepare_demo.prepare_demo(1, 10) is True
    assert ctx.client.interactions.create.call_count == 2
    with ctx.factory() as session:
        item = session.execute(select(JobItem).where(JobItem.tenant_id == "demo")).scalar_one()
        assert item.job_id == original_job_id
        assert item.status == "completed"
        assert item.attempts == 2
        calls = session.scalars(select(AICall).where(
            AICall.tenant_id == "demo", AICall.operation == "vision"
        ).order_by(AICall.attempt)).all()
        assert [call.status for call in calls] == ["failed", "completed"]
