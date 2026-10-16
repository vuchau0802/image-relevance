from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from app.repositories.usage import VisionBudgetExceededError
from app.services import vision


@pytest.fixture
def vision_call(monkeypatch, tmp_path):
    image = tmp_path / "img_001.jpg"
    image.write_bytes(b"test image content")
    settings = SimpleNamespace(
        gemini_api_key=SecretStr("unused-test-key"), vision_model="test-model",
        vision_daily_call_limit=2, min_classification_confidence=0.7,
    )
    client = Mock()
    client.interactions.create.return_value = SimpleNamespace(
        output_text='{"subject":"fox","category":"animal","attributes":["orange fur"],"caption":"A fox outdoors","confidence":0.9}',
        usage=SimpleNamespace(total_input_tokens=10, total_output_tokens=5),
    )
    constructor, reserve, finish = Mock(return_value=client), Mock(), Mock()
    monkeypatch.setattr(vision, "get_settings", lambda: settings)
    monkeypatch.setattr(vision.genai, "Client", constructor)
    monkeypatch.setattr(vision, "reserve_vision_call", reserve)
    monkeypatch.setattr(vision, "finish_ai_call", finish)
    return image, client, constructor, reserve, finish


def test_budget_block_does_not_construct_client_or_finalize_a_call(vision_call):
    image, client, constructor, reserve, finish = vision_call
    reserve.side_effect = VisionBudgetExceededError("limit reached")
    with pytest.raises(VisionBudgetExceededError):
        vision.process_image(image)
    constructor.assert_not_called()
    finish.assert_not_called()


def test_successful_call_is_attributed_and_finalized_with_usage(vision_call):
    image, client, constructor, reserve, finish = vision_call
    def reserved(**kwargs):
        constructor.assert_not_called()
    reserve.side_effect = reserved
    result = vision.process_image(image, tenant_id="tenant-a", job_id="job", attempt=2)
    assert result.status == "completed"
    record = reserve.call_args.kwargs["call_record"]
    assert record["tenant_id"] == "tenant-a"
    assert record["job_id"] == "job"
    assert record["attempt"] == 2
    assert record["status"] == "started"
    finish.assert_called_once_with(
        "tenant-a", record["call_id"], status="completed", input_tokens=10, output_tokens=5,
    )
    client.close.assert_called_once()


@pytest.mark.parametrize("failure,status", [(RuntimeError("not logged"), "failed"), (KeyboardInterrupt(), "interrupted")])
def test_failed_or_interrupted_call_records_only_error_type(vision_call, failure, status):
    image, client, constructor, reserve, finish = vision_call
    client.interactions.create.side_effect = failure
    with pytest.raises(type(failure)):
        vision.process_image(image)
    assert finish.call_args.kwargs["status"] == status
    assert finish.call_args.kwargs["error_type"] == type(failure).__name__
    assert "not logged" not in str(finish.call_args)
    client.close.assert_called_once()


def test_client_construction_failure_retains_failed_audit(vision_call):
    image, client, constructor, reserve, finish = vision_call
    constructor.side_effect = ValueError("client setup failed")
    with pytest.raises(ValueError):
        vision.process_image(image)
    assert reserve.call_count == 1
    assert finish.call_args.kwargs["status"] == "failed"
