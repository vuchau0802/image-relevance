from dataclasses import dataclass
from typing import Literal

from app.schemas.context import (
    ContextRequirements,
    SceneEvidence,
)


@dataclass(frozen=True)
class ContextDecision:
    status: Literal["supported", "contradicted", "unknown"]
    reasons: tuple[str, ...]

    @property
    def matches(self) -> bool:
        return self.status == "supported"


def assess_context(
    requirements: ContextRequirements,
    evidence: list[SceneEvidence],
) -> ContextDecision:
    facts = {}

    for fact in evidence:
        if fact.feature in facts:
            raise ValueError(
                f"Duplicate scene evidence: {fact.feature}"
            )
        facts[fact.feature] = fact

    contradictions = []
    unknowns = []

    for requirement in requirements.requirements:
        fact = facts.get(requirement.feature)

        if fact is None or fact.state == "unknown":
            unknowns.append(
                f"Evidence unavailable for {requirement.feature}; "
                f"required {requirement.expected}."
            )
        elif fact.state != requirement.expected:
            contradictions.append(
                f"{requirement.feature} is {fact.state}; "
                f"required {requirement.expected}."
            )

    if contradictions:
        return ContextDecision(
            status="contradicted",
            reasons=tuple(contradictions + unknowns),
        )

    if unknowns:
        return ContextDecision(
            status="unknown",
            reasons=tuple(unknowns),
        )

    return ContextDecision(
        status="supported",
        reasons=(
            "All explicit context requirements are supported."
            if requirements.requirements
            else "No explicit context requirements were specified.",
        ),
    )