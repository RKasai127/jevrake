"""Collect possible values (candidates) for each target from the page.

A list page is split into item blocks (one per record); any other page is one block. Text targets
take titles and text elements; number targets take prices and other numbers. Candidates are
de-duplicated and, if there are too many, only the highest-scoring ones are kept.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from typing import Any

from .convert import NUMBER_RE, convert_text, normalize_text
from .exceptions import CoercionError
from .models import ExtractionCandidate, ExtractionTarget, ItemBlock, ParsedPage, TextElement

MAX_CANDIDATES = 254  # plus "__none__" = 255 choices
MAX_TEXT_CHARS = 200
_PREFIX_LABEL_CHARS = 20
MIN_LIST_ITEMS = 3
MIN_LIST_TEXT_RATIO = 0.5
MAX_SHORT_TEXT_CHARS = 40


def _format_tag(element: TextElement) -> str:
    attr_text = "".join(
        f" {attr_name}={element.attrs[attr_name]}"
        for attr_name in ("class", "id", "itemprop")
        if element.attrs.get(attr_name)
    )
    return f"<{element.tag}{attr_text}>"


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


def _find_text_candidates(page: ParsedPage, block: ItemBlock) -> Iterator[ExtractionCandidate]:
    if block.is_whole_page and page.title:
        yield ExtractionCandidate(
            text=page.title,
            normalized_value=None,
            context={"tag": "<title>", "source": "page title"},
        )
    if block.is_whole_page and page.og_title:
        yield ExtractionCandidate(
            text=page.og_title,
            normalized_value=None,
            context={"tag": "<meta og:title>", "source": "og:title"},
        )
    for element in block.elements:
        if 2 <= len(element.text) <= MAX_TEXT_CHARS:
            yield ExtractionCandidate(
                text=element.text,
                normalized_value=None,
                context=_build_context(element),
            )


def _find_number_candidates(block: ItemBlock) -> Iterator[ExtractionCandidate]:
    for element in block.elements:
        text = normalize_text(element.text)
        for match in NUMBER_RE.finditer(text):
            context = _build_context(element, _find_prefix_label(text, match.start()))
            unit = match.group("prefix") or match.group("suffix")
            if unit:
                context["unit"] = unit.strip()
            yield ExtractionCandidate(
                text=match.group(0).strip(),
                normalized_value=None,
                context=context,
            )


def _split_terms(text: str) -> set[str]:
    """Matching terms: whole words for Latin text, character bigrams for CJK text."""
    normalized_text = normalize_text(text).lower()
    terms = set(re.findall(r"[a-z]{3,}", normalized_text))
    for cjk_text in re.findall(r"[^\x00-\x7f\s\W]+", normalized_text):
        terms |= {cjk_text[i : i + 2] for i in range(len(cjk_text) - 1)}
    return terms


def _calculate_score(
    candidate: ExtractionCandidate, target: ExtractionTarget, same_value_count: int
) -> float:
    context = candidate.context
    score = 0.0
    name_terms = _split_terms(target.name.replace("_", " "))
    wanted_terms = _split_terms(target.description) | name_terms
    label = context.get("label")
    if label:
        score += 1.0
        if _split_terms(label) & wanted_terms:
            score += 2.0
    if _split_terms(context.get("tag", "").replace("-", " ").replace("_", " ")) & name_terms:
        score += 1.5
    heading = context.get("heading")
    if heading and target.kind == "str":
        score += {"h1": 3.0, "h2": 2.0}.get(heading, 1.0)
    if context.get("source"):
        score += 3.0
    score += 0.5 * min(same_value_count - 1, 3)
    if target.kind != "str" and context.get("unit"):
        score += 1.0
    if target.kind == "str" and len(candidate.text) > 80:
        score -= 1.0
    return score


def remove_duplicates(candidates: list[ExtractionCandidate]) -> list[ExtractionCandidate]:
    """Keep one candidate per ``normalized_value``: the one with the most context."""
    index_by_value: dict[Any, int] = {}
    for index, candidate in enumerate(candidates):
        value = candidate.normalized_value
        kept_index = index_by_value.get(value)
        if kept_index is None or len(candidate.context) > len(candidates[kept_index].context):
            index_by_value[value] = index
    return [candidates[index] for index in sorted(index_by_value.values())]


def keep_top_candidates(candidates: list[ExtractionCandidate]) -> list[ExtractionCandidate]:
    """Keep the ``MAX_CANDIDATES`` highest-scoring candidates, preserving document order."""
    if len(candidates) <= MAX_CANDIDATES:
        return candidates
    indexes_by_score = sorted(range(len(candidates)), key=lambda index: -candidates[index].score)
    kept_indexes = sorted(indexes_by_score[:MAX_CANDIDATES])
    return [candidates[index] for index in kept_indexes]


def generate_candidates(
    page: ParsedPage, block: ItemBlock, target: ExtractionTarget
) -> list[ExtractionCandidate]:
    converted_candidates: list[ExtractionCandidate] = []
    raw_candidates = (
        _find_text_candidates(page, block)
        if target.kind == "str"
        else _find_number_candidates(block)
    )
    for raw_candidate in raw_candidates:
        try:
            value = convert_text(raw_candidate.text, target.kind)
        except CoercionError:
            continue
        converted_candidates.append(raw_candidate.model_copy(update={"normalized_value": value}))

    count_by_value = Counter(candidate.normalized_value for candidate in converted_candidates)
    scored_candidates = [
        candidate.model_copy(
            update={
                "score": _calculate_score(
                    candidate, target, count_by_value[candidate.normalized_value]
                )
            }
        )
        for candidate in remove_duplicates(converted_candidates)
    ]
    return keep_top_candidates(scored_candidates)


def _count_text(elements: list[TextElement]) -> int:
    return sum(len(element.text) for element in elements)


def _build_block(
    page: ParsedPage,
    elements: list[TextElement],
    is_whole_page: bool,
    targets: list[ExtractionTarget],
) -> ItemBlock:
    """Make a block and collect the candidates of every target in it."""
    block = ItemBlock(elements=elements, is_whole_page=is_whole_page)
    candidates_by_target = {
        target.name: generate_candidates(page, block, target) for target in targets
    }
    return block.model_copy(update={"candidates_by_target": candidates_by_target})


def find_item_blocks(page: ParsedPage, targets: list[ExtractionTarget]) -> list[ItemBlock]:
    """Return one block per item on a list page, or the whole page as a single block.

    Each block comes with the candidates of every target, so they are collected only once.

    Every block of the chosen group is returned, so an item that misses a value is reported later
    instead of silently disappearing.
    """
    required_targets = [target for target in targets if not target.is_optional]
    page_chars = _count_text(page.elements)
    item_blocks: list[ItemBlock] = []
    max_item_count = 0
    for group in page.repeated_groups:
        blocks = [_build_block(page, elements, False, targets) for elements in group]
        item_count = sum(
            1
            for block in blocks
            if len(block.elements) >= 2
            and any(len(element.text) <= MAX_SHORT_TEXT_CHARS for element in block.elements)
            and all(block.candidates_by_target[target.name] for target in required_targets)
        )
        group_chars = _count_text([element for block in blocks for element in block.elements])
        is_main_content = group_chars >= page_chars * MIN_LIST_TEXT_RATIO
        is_list = item_count >= MIN_LIST_ITEMS and is_main_content
        if is_list and item_count > max_item_count:
            item_blocks, max_item_count = blocks, item_count
    return item_blocks or [_build_block(page, page.elements, True, targets)]
