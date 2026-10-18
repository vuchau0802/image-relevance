import json
import sys
from unittest.mock import Mock

import pytest

from app.schemas.context import ContextRequirements, SceneEvidence
from scripts import rank_context_pilot as pilot


def candidate(image_id="img_test"):
    return {
        "image_id": image_id,
        "subject": "red fox",
        "caption": "Synthetic test image.",
        "similarity": 0.90,
    }


def evidence(state):
    return [
        SceneEvidence(
            feature="snow",
            state=state,
            source="manual_review",
            explanation="Synthetic evidence for this test.",
        )
    ]


@pytest.fixture
def setup_pilot(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["rank_context_pilot", "--post-id", "eval_test"],
    )

    requirements = ContextRequirements(
        requirements=[{"feature": "snow", "expected": "present"}]
    )

    post_context = Mock(return_value=requirements)
    image_context = Mock(return_value=evidence("present"))
    ranker = Mock(return_value={
        "post_id": "eval_test",
        "status": "matched",
        "reason": "Original ranking reason.",
        "results": [candidate()],
    })

    monkeypatch.setattr(
        pilot, "get_current_post_context", post_context
    )
    monkeypatch.setattr(
        pilot, "get_current_image_context", image_context
    )
    monkeypatch.setattr(pilot, "rank_post_images", ranker)

    return post_context, image_context, ranker


@pytest.mark.parametrize(
    "state,expected_status",
    [
        ("present", "matched"),
        ("absent", "no_confident_match"),
        ("unknown", "incomplete"),
        (None, "incomplete"),
    ],
)
def test_context_controls_acceptance(
    setup_pilot, capsys, state, expected_status
):
    _, image_context, ranker = setup_pilot
    image_context.return_value = (
        evidence(state) if state is not None else None
    )

    pilot.main()
    result = json.loads(capsys.readouterr().out)

    assert result["status"] == expected_status
    assert len(result["results"]) == (
        1 if expected_status == "matched" else 0
    )
    assert result["context_checks"][0]["context_status"] == (
        "supported" if state == "present"
        else "contradicted" if state == "absent"
        else "unknown"
    )
    ranker.assert_called_once_with(
        tenant_id="demo", post_id="eval_test", top=50
    )
    image_context.assert_called_once_with(
        "demo", "img_test", "manual-v2-pilot"
    )


def test_missing_post_context_stops_before_ranking(
    setup_pilot, capsys
):
    post_context, image_context, ranker = setup_pilot
    post_context.return_value = None

    with pytest.raises(SystemExit) as error:
        pilot.main()

    assert error.value.code == 1
    assert "post context is missing" in capsys.readouterr().err
    ranker.assert_not_called()
    image_context.assert_not_called()


def test_below_threshold_candidates_are_not_rescued(
    setup_pilot, capsys
):
    _, image_context, ranker = setup_pilot
    ranker.return_value.update({
        "status": "no_confident_match",
        "reason": "Below similarity threshold.",
        "results": [],
    })

    pilot.main()
    result = json.loads(capsys.readouterr().out)

    assert result["status"] == "no_confident_match"
    assert result["reason"] == "Below similarity threshold."
    assert result["results"] == []
    assert result["context_checks"] == []
    image_context.assert_not_called()


@pytest.mark.parametrize(
    "status", ["incomplete", "unsupported_subject"]
)
def test_original_nonmatch_status_is_preserved(
    setup_pilot, capsys, status
):
    _, _, ranker = setup_pilot
    ranker.return_value.update({
        "status": status,
        "reason": "Original ranking reason.",
        "results": [],
    })

    pilot.main()
    result = json.loads(capsys.readouterr().out)

    assert result["status"] == status
    assert result["reason"] == "Original ranking reason."
    assert result["results"] == []


def test_unknown_candidate_blocks_partial_acceptance(
    setup_pilot, capsys
):
    _, image_context, ranker = setup_pilot
    ranker.return_value["results"] = [
        candidate("img_supported"),
        candidate("img_unknown"),
    ]
    image_context.side_effect = [
        evidence("present"),
        None,
    ]

    pilot.main()
    result = json.loads(capsys.readouterr().out)

    assert result["status"] == "incomplete"
    assert result["results"] == []
    assert [
        check["context_status"]
        for check in result["context_checks"]
    ] == ["supported", "unknown"]