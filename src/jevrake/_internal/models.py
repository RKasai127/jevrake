"""Data models shared across the internal modules."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from typesafe_sdk import Choice

ExtractionKind = Literal["str", "int", "float", "decimal"]


class ExtractionTarget(BaseModel):
    """Internal description of one field to extract."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    kind: ExtractionKind
    nullable: bool = False
    required: bool = True

    @property
    def optional(self) -> bool:
        return self.nullable or not self.required


class TextElement(BaseModel):
    """An element that directly contains text, with information about its surroundings."""

    model_config = ConfigDict(frozen=True)

    text: str
    tag: str
    attrs: dict[str, str]
    label: str | None = None
    heading_level: int | None = None


class ParsedPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str | None
    og_title: str | None
    main_text: str
    elements: list[TextElement]


class ExtractionCandidate(BaseModel):
    """A value found on the page that may be the answer for a field."""

    model_config = ConfigDict(frozen=True)

    text: str
    normalized_value: Any
    context: dict[str, str] = {}
    score: float = 0.0


class JevRequest(BaseModel):
    state: dict[str, str]
    questions: dict[str, Choice] = {}
    options: dict[str, dict[str, ExtractionCandidate]] = {}
    skipped: list[str] = []


class JevChoiceAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    choice: str
    confidence: float
    probabilities: dict[str, float]


class JevResponse(BaseModel):
    """The parts of a Jev response jevrake uses, independent of the SDK types."""

    model_config = ConfigDict(frozen=True)

    choices: dict[str, JevChoiceAnswer] = {}
    request_id: str | None = None


class ExtractedValue(BaseModel):
    value: Any | None
    confidence: float | None
    probability: float
    source: str | None


class ExtractionOutcome(BaseModel):
    fields: dict[str, ExtractedValue]
    values: dict[str, Any]
    errors: list[str]


class RakeResult[T: BaseModel](BaseModel):
    url: str
    data: T | None
    fields: dict[str, ExtractedValue]
    request_id: str | None
    errors: list[str]
