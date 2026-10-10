"""Collect possible values (candidates) for each target from the page.

Text targets take titles and text elements; number targets take prices and other numbers.
Candidates are de-duplicated and, if there are too many, only the highest-scoring ones are kept.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from typing import Any

from .convert import NUMBER_RE, convert_text, normalize_text
from .exceptions import CoercionError
from .models import ExtractionCandidate, ExtractionTarget, ParsedPage, TextElement

MAX_CANDIDATES = 254  # plus "__none__" = 255 choices
MAX_TEXT_CHARS = 200
_PREFIX_LABEL_CHARS = 20


def _format_tag(element: TextElement) -> str:
    attrs = "".join(
        f" {key}={element.attrs[key]}"
        for key in ("class", "id", "itemprop")
        if element.attrs.get(key)
    )
    return f"<{element.tag}{attrs}>"


def _build_context(element: TextElement, label: str | None = None) -> dict[str, str]:
    context = {"tag": _format_tag(element)}
    label = label or element.label
    if label and label != element.text:
        context["label"] = label
    if element.heading_level:
        context["heading"] = f"h{element.heading_level}"
    return context


def _find_prefix_label(text: str, start: int) -> str | None:
    prefix = text[:start].strip().rstrip(":：").strip()
    if 0 < len(prefix) <= _PREFIX_LABEL_CHARS and not re.search(r"\d", prefix[-3:]):
        return prefix
    return None


def _find_text_candidates(page: ParsedPage) -> Iterator[ExtractionCandidate]:
    if page.title:
        yield ExtractionCandidate(
            text=page.title,
            normalized_value=None,
            context={"tag": "<title>", "source": "page title"},
        )
    if page.og_title:
        yield ExtractionCandidate(
            text=page.og_title,
            normalized_value=None,
            context={"tag": "<meta og:title>", "source": "og:title"},
        )
    for element in page.elements:
        if 2 <= len(element.text) <= MAX_TEXT_CHARS:
            yield ExtractionCandidate(
                text=element.text,
                normalized_value=None,
                context=_build_context(element),
            )


def _find_number_candidates(page: ParsedPage) -> Iterator[ExtractionCandidate]:
    for element in page.elements:
        text = normalize_text(element.text)
        for m in NUMBER_RE.finditer(text):
            context = _build_context(element, _find_prefix_label(text, m.start()))
            if m.group("prefix") or m.group("suffix"):
                context["unit"] = (m.group("prefix") or m.group("suffix")).strip()
            yield ExtractionCandidate(
                text=m.group(0).strip(),
                normalized_value=None,
                context=context,
            )


def _split_terms(text: str) -> set[str]:
    """Matching terms: whole words for Latin text, character bigrams for CJK text."""
    s = normalize_text(text).lower()
    terms = {w for w in re.findall(r"[a-z]{3,}", s)}
    for run in re.findall(r"[^\x00-\x7f\s\W]+", s):
        terms |= {run[i : i + 2] for i in range(len(run) - 1)}
    return terms


def _calculate_score(
    candidate: ExtractionCandidate, target: ExtractionTarget, frequency: int
) -> float:
    ctx = candidate.context
    score = 0.0
    name_terms = _split_terms(target.name.replace("_", " "))
    wanted = _split_terms(target.description) | name_terms
    label = ctx.get("label")
    if label:
        score += 1.0
        if _split_terms(label) & wanted:
            score += 2.0
    if _split_terms(ctx.get("tag", "").replace("-", " ").replace("_", " ")) & name_terms:
        score += 1.5
    heading = ctx.get("heading")
    if heading and target.kind == "str":
        score += {"h1": 3.0, "h2": 2.0}.get(heading, 1.0)
    if ctx.get("source"):
        score += 3.0
    score += 0.5 * min(frequency - 1, 3)
    if target.kind != "str" and ctx.get("unit"):
        score += 1.0
    if target.kind == "str" and len(candidate.text) > 80:
        score -= 1.0
    return score


def remove_duplicates(candidates: list[ExtractionCandidate]) -> list[ExtractionCandidate]:
    """Keep one candidate per ``normalized_value``: the one with the most context."""
    best: dict[Any, int] = {}
    for i, candidate in enumerate(candidates):
        key = candidate.normalized_value
        if key not in best or len(candidate.context) > len(candidates[best[key]].context):
            best[key] = i
    return [candidates[i] for i in sorted(best.values())]


def keep_top_candidates(candidates: list[ExtractionCandidate]) -> list[ExtractionCandidate]:
    """Keep the ``MAX_CANDIDATES`` highest-scoring candidates, preserving document order."""
    if len(candidates) <= MAX_CANDIDATES:
        return candidates
    ranked = sorted(range(len(candidates)), key=lambda i: -candidates[i].score)
    keep = sorted(ranked[:MAX_CANDIDATES])
    return [candidates[i] for i in keep]


def generate_candidates(page: ParsedPage, target: ExtractionTarget) -> list[ExtractionCandidate]:
    converted: list[ExtractionCandidate] = []
    raw_candidates = (
        _find_text_candidates(page) if target.kind == "str" else _find_number_candidates(page)
    )
    for raw in raw_candidates:
        try:
            value = convert_text(raw.text, target.kind)
        except CoercionError:
            continue
        converted.append(raw.model_copy(update={"normalized_value": value}))

    frequency = Counter(c.normalized_value for c in converted)
    unique = remove_duplicates(converted)
    scored = [
        c.model_copy(update={"score": _calculate_score(c, target, frequency[c.normalized_value])})
        for c in unique
    ]
    return keep_top_candidates(scored)
