from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


class ContextRequirement(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    feature: str = Field(
        pattern=r"^[a-z][a-z0-9_]{0,49}$",
    )
    expected: Literal["present", "absent"]


class ContextRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: list[ContextRequirement] = Field(
        default_factory=list,
        max_length=20,
    )

    @model_validator(mode="after")
    def reject_duplicate_features(self):
        features = [
            item.feature for item in self.requirements
        ]

        if len(features) != len(set(features)):
            raise ValueError(
                "Each context feature must appear only once"
            )

        return self


class SceneEvidence(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    feature: str = Field(
        pattern=r"^[a-z][a-z0-9_]{0,49}$",
    )
    state: Literal["present", "absent", "unknown"]
    source: Literal["manual_review", "vision_model"]
    explanation: str = Field(
        min_length=1,
        max_length=500,
    )