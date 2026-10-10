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


def describe_candidate(candidate: ExtractionCandidate) -> str:
    """e.g. ``"¥3,980" | <span class=price> | nearby label: 販売価格``"""
    text = candidate.text
    if len(text) > MAX_DESCRIPTION_TEXT:
        text = text[:MAX_DESCRIPTION_TEXT] + "…"
    parts = [json.dumps(text, ensure_ascii=False)]
    ctx = candidate.context
    if ctx.get("source"):
        parts.append(ctx["source"])
    elif ctx.get("tag"):
        parts.append(ctx["tag"])
    if ctx.get("heading"):
        parts.append(f"heading {ctx['heading']}")
    if ctx.get("label"):
        parts.append(f"nearby label: {ctx['label']}")
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
    candidates: dict[str, list[ExtractionCandidate]],
) -> JevRequest:
    request = JevRequest(state=build_jev_state(url, page))
    for target in targets:
        chosen = candidates.get(target.name, [])[: MAX_CHOICES - 1]
        if not chosen:
            request.skipped.append(target.name)
            continue
        names = [f"c{i}" for i in range(len(chosen))]
        criteria = {name: describe_candidate(c) for name, c in zip(names, chosen, strict=True)}
        criteria[NONE_CHOICE] = NONE_DESCRIPTION
        request.questions[target.name] = Choice(
            instructions=CHOICE_INSTRUCTIONS.format(
                description=target.description, name=target.name
            ),
            criteria=criteria,
        )
        request.options[target.name] = dict(zip(names, chosen, strict=True))
    return request


def build_jev_payload(request: JevRequest, model: str) -> dict[str, Any]:
    """The request body as it would be sent (for ``--dry-run``)."""
    return {
        "model": model,
        "state": request.state,
        "questions": {
            name: q.model_dump(mode="json", exclude_none=True)
            for name, q in request.questions.items()
        },
    }


def _record_missing_value(
    target: ExtractionTarget, values: dict[str, Any], errors: list[str], reason: str
) -> None:
    if not target.is_optional:
        errors.append(f"{target.name}: {reason}")
    elif target.required:  # nullable without default
        values[target.name] = None


def parse_jev_response(
    request: JevRequest,
    response: JevResponse,
    targets: list[ExtractionTarget],
    min_confidence: float,
) -> ExtractionOutcome:
    fields: dict[str, ExtractedValue] = {}
    values: dict[str, Any] = {}
    errors: list[str] = []

    for target in targets:
        name = target.name
        if name in request.skipped:
            fields[name] = ExtractedValue(value=None, confidence=None, probability=0.0, source=None)
            _record_missing_value(target, values, errors, "no candidates found on the page")
            continue

        answer = response.choices.get(name)
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
        candidate = request.options[name].get(answer.choice)
        if candidate is None:
            errors.append(f"{name}: Jev returned an unknown choice: {answer.choice!r}")
            continue
        if answer.confidence < min_confidence:
            # Not confident enough: discard the value but keep what was rejected and why.
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
