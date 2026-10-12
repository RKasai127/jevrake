"""Build the question for Jev, and read Jev's answer.

Has no network access; sending the question is done by client.py.
"""

from __future__ import annotations

import json
from typing import Any

from typesafe_sdk import Choice

from .models import (
    ExtractedValue,
    ExtractionCandidate,
    ExtractionOutcome,
    ExtractionTarget,
    JevRequest,
    JevResponse,
    ParsedPage,
)

NONE_CHOICE = "__none__"
NONE_DESCRIPTION = "None of these is the requested value."
MAX_CHOICES = 255
MAX_DESCRIPTION_TEXT = 200

CHOICE_INSTRUCTIONS = (
    'Which option is "{description}"? Choose the option that represents the {name} of this page.'
)

ITEM_CHOICE_INSTRUCTIONS = (
    'Which option is "{description}"? All options come from one item of a list on this page; '
    "choose the option that represents the {name} of that item."
)


def build_question_key(name: str, item_no: int | None) -> str:
    """``price`` for a single-record page, ``item3.price`` for item 3 of a list page."""
    return name if item_no is None else f"item{item_no}.{name}"


def describe_candidate(candidate: ExtractionCandidate) -> str:
    """e.g. ``"¥3,980" | <span class=price> | nearby label: 販売価格``"""
    text = candidate.text
    if len(text) > MAX_DESCRIPTION_TEXT:
        text = text[:MAX_DESCRIPTION_TEXT] + "…"
    parts = [json.dumps(text, ensure_ascii=False)]
    context = candidate.context
    if context.get("source"):
        parts.append(context["source"])
    elif context.get("tag"):
        parts.append(context["tag"])
    if context.get("heading"):
        parts.append(f"heading {context['heading']}")
    if context.get("label"):
        parts.append(f"nearby label: {context['label']}")
    return " | ".join(parts)


def build_jev_state(url: str, page: ParsedPage) -> dict[str, str]:
    return {
        "url": url,
        "page_title": page.title or page.og_title or "",
        "main_text": page.main_text,
    }


def build_jev_request(
    url: str,
    page: ParsedPage,
    targets: list[ExtractionTarget],
    candidates_by_item: dict[int | None, dict[str, list[ExtractionCandidate]]],
) -> JevRequest:
    """Build one request with a question per item and target.

    ``candidates_by_item`` maps an item number (``None`` for a single-record page) to the
    candidates of each target in that item.
    """
    request = JevRequest(state=build_jev_state(url, page))
    for item_no, candidates_by_target in candidates_by_item.items():
        for target in targets:
            key = build_question_key(target.name, item_no)
            option_candidates = candidates_by_target.get(target.name, [])[: MAX_CHOICES - 1]
            if not option_candidates:
                request.skipped_keys.append(key)
                continue
            option_names = [f"c{i}" for i in range(len(option_candidates))]
            candidate_by_option = dict(zip(option_names, option_candidates, strict=True))
            criteria = {
                option_name: describe_candidate(candidate)
                for option_name, candidate in candidate_by_option.items()
            }
            criteria[NONE_CHOICE] = NONE_DESCRIPTION
            instructions = CHOICE_INSTRUCTIONS if item_no is None else ITEM_CHOICE_INSTRUCTIONS
            request.questions[key] = Choice(
                instructions=instructions.format(description=target.description, name=target.name),
                criteria=criteria,
            )
            request.options_by_question[key] = candidate_by_option
    return request


def build_jev_payload(request: JevRequest, model: str) -> dict[str, Any]:
    """The request body as it would be sent (for ``--dry-run``)."""
    return {
        "model": model,
        "state": request.state,
        "questions": {
            key: question.model_dump(mode="json", exclude_none=True)
            for key, question in request.questions.items()
        },
    }


def _record_missing_value(
    target: ExtractionTarget, values: dict[str, Any], errors: list[str], reason: str
) -> None:
    if not target.is_optional:
        errors.append(f"{target.name}: {reason}")
    elif target.is_required:
        values[target.name] = None


def parse_jev_response(
    request: JevRequest,
    response: JevResponse,
    targets: list[ExtractionTarget],
    min_confidence: float,
    item_no: int | None = None,
) -> ExtractionOutcome:
    """Turn Jev's answers for one item (``None`` for a single-record page) into values."""
    fields: dict[str, ExtractedValue] = {}
    values: dict[str, Any] = {}
    errors: list[str] = []

    for target in targets:
        name = target.name
        key = build_question_key(name, item_no)
        if key in request.skipped_keys:
            fields[name] = ExtractedValue(value=None, confidence=None, probability=0.0, source=None)
            _record_missing_value(target, values, errors, "no candidates found on the page")
            continue

        answer = response.choices.get(key)
        if answer is None:
            errors.append(f"{name}: missing from the Jev response")
            continue
        probability = answer.probabilities.get(answer.choice, answer.confidence)
        if answer.choice == NONE_CHOICE:
            fields[name] = ExtractedValue(
                value=None, confidence=answer.confidence, probability=probability, source=None
            )
            _record_missing_value(target, values, errors, "no matching value (Jev chose __none__)")
            continue
        candidate = request.options_by_question[key].get(answer.choice)
        if candidate is None:
            errors.append(f"{name}: Jev returned an unknown choice: {answer.choice!r}")
            continue
        if answer.confidence < min_confidence:
            fields[name] = ExtractedValue(
                value=None,
                confidence=answer.confidence,
                probability=probability,
                source=candidate.text,
            )
            _record_missing_value(
                target,
                values,
                errors,
                f"confidence {answer.confidence:.2f} is below {min_confidence:.2f} "
                f"(rejected {candidate.text!r})",
            )
            continue
        fields[name] = ExtractedValue(
            value=candidate.normalized_value,
            confidence=answer.confidence,
            probability=probability,
            source=candidate.text,
        )
        values[name] = candidate.normalized_value

    return ExtractionOutcome(fields=fields, values=values, errors=errors)
