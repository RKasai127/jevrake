"""Data passed between the steps of ``rake()``, and the results returned to users."""

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
    is_nullable: bool = False
    is_required: bool = True

    @property
    def is_optional(self) -> bool:
        return self.is_nullable or not self.is_required


class TargetDefinition(BaseModel):
    """One entry of the CLI ``--fields`` JSON."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    type: ExtractionKind = "str"


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
    repeated_groups: list[list[list[TextElement]]] = []


class ExtractionCandidate(BaseModel):
    """A value found on the page that may be the answer for a field."""

    model_config = ConfigDict(frozen=True)

    text: str
    normalized_value: Any
    context: dict[str, str] = {}


class ItemBlock(BaseModel):
    """The part of a page that holds one item (one record of output).

    On a list page, each repeated entry (e.g. one shop) is an item, numbered from 0 (``item_no``).
    On any other page, the whole page is the only item (``item_no`` is ``None``).
    """

    model_config = ConfigDict(frozen=True)

    elements: list[TextElement]
    is_whole_page: bool
    candidates_by_target: dict[str, list[ExtractionCandidate]] = {}


class JevRequest(BaseModel):
    state: dict[str, str]
    questions: dict[str, Choice] = {}
    options_by_question: dict[str, dict[str, ExtractionCandidate]] = {}
    skipped_keys: list[str] = []


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


class RakeItem[T: BaseModel](BaseModel):
    """One record found on a page."""

    data: T
    fields: dict[str, ExtractedValue]


class RakeResult[T: BaseModel](BaseModel):
    """All records found on one page."""

    url: str
    items: list[RakeItem[T]]
    request_ids: list[str]
    errors: list[str]
