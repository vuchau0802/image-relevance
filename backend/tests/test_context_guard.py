import pytest
from pydantic import ValidationError

from app.schemas.context import (
    ContextRequirement,
    ContextRequirements,
    SceneEvidence,
)
from app.services.context_guard import assess_context


def requirement(feature="snow", expected="present"):
    return ContextRequirement(
        feature=feature,
        expected=expected,
    )


def fact(feature="snow", state="present"):
    return SceneEvidence(
        feature=feature,
        state=state,
        source="manual_review",
        explanation="Synthetic test evidence.",
    )


@pytest.mark.parametrize(
    "expected,observed,status",
    [
        ("present", "present", "supported"),
        ("present", "absent", "contradicted"),
        ("present", "unknown", "unknown"),
        ("absent", "absent", "supported"),
        ("absent", "present", "contradicted"),
        ("absent", "unknown", "unknown"),
    ],
)
def test_context_truth_table(expected, observed, status):
    requirements = ContextRequirements(
        requirements=[requirement(expected=expected)]
    )

    result = assess_context(
        requirements,
        [fact(state=observed)],
    )

    assert result.status == status
    assert result.matches is (status == "supported")


@pytest.mark.parametrize("expected", ["present", "absent"])
def test_missing_evidence_is_unknown(expected):
    result = assess_context(
        ContextRequirements(requirements=[
            requirement(expected=expected)
        ]),
        [],
    )

    assert result.status == "unknown"
    assert result.matches is False


def test_no_requirements_passes_context_gate():
    result = assess_context(ContextRequirements(), [])

    assert result.status == "supported"
    assert result.matches is True


def test_all_requirements_must_be_supported():
    result = assess_context(
        ContextRequirements(requirements=[
            requirement("rider"),
            requirement("helmet"),
        ]),
        [
            fact("rider"),
            fact("helmet"),
        ],
    )

    assert result.matches is True


def test_one_missing_requirement_prevents_acceptance():
    result = assess_context(
        ContextRequirements(requirements=[
            requirement("rider"),
            requirement("helmet"),
        ]),
        [fact("rider")],
    )

    assert result.status == "unknown"
    assert result.matches is False
    assert any("helmet" in reason for reason in result.reasons)


def test_contradiction_takes_priority_over_unknown():
    result = assess_context(
        ContextRequirements(requirements=[
            requirement("rider"),
            requirement("helmet"),
        ]),
        [fact("rider", "absent")],
    )

    assert result.status == "contradicted"
    assert result.matches is False
    assert len(result.reasons) == 2


def test_duplicate_evidence_is_rejected():
    with pytest.raises(ValueError, match="Duplicate scene"):
        assess_context(
            ContextRequirements(requirements=[requirement()]),
            [
                fact(state="present"),
                fact(state="absent"),
            ],
        )


def test_conflicting_requirements_are_rejected():
    with pytest.raises(ValidationError, match="only once"):
        ContextRequirements(requirements=[
            requirement(expected="present"),
            requirement(expected="absent"),
        ])