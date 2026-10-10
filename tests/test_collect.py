from decimal import Decimal

from jevrake._internal.collect import (
    MAX_CANDIDATES,
    generate_candidates,
    keep_top_candidates,
    remove_duplicates,
)
from jevrake._internal.dom import parse_page
from jevrake._internal.models import ExtractionCandidate, ExtractionKind, ExtractionTarget

from .conftest import load_fixture


def _target(kind: ExtractionKind, name: str = "value", description: str = "値") -> ExtractionTarget:
    return ExtractionTarget(name=name, description=description, kind=kind)


def _candidate(value: object, context: dict[str, str], score: float = 0) -> ExtractionCandidate:
    return ExtractionCandidate(
        text=str(value), normalized_value=value, context=context, score=score
    )


def test_japanese_prices() -> None:
    page = parse_page(
        "<body><p>価格: ¥３，９８０（税込）</p><p>通常 4,980円</p><p>送料 ￥500</p></body>"
    )
    target = _target("int", "price", "販売価格")

    candidates = generate_candidates(page, target)

    assert [c.normalized_value for c in candidates] == [3980, 4980, 500]


def test_price_label_and_unit_context() -> None:
    page = parse_page(load_fixture("ja_product.html"))
    target = _target("int", "price", "税込の販売価格（円）")

    candidates = generate_candidates(page, target)

    first = candidates[0]
    assert first.text == "¥3,980"
    assert first.normalized_value == 3980
    assert first.context["label"] == "販売価格"
    assert first.context["unit"] == "¥"


def test_numbers_in_japanese_and_iso_dates_are_not_candidates() -> None:
    page = parse_page("<body><p>2026年9月30日 発売</p><p>2026/10/02</p><p>2026-10-03</p></body>")

    candidates = generate_candidates(page, _target("int"))

    assert candidates == []


def test_decimal_prices_in_english() -> None:
    page = parse_page(load_fixture("en_product.html"))
    target = _target("decimal", "price", "Price in USD")

    candidates = generate_candidates(page, target)

    values = {c.normalized_value for c in candidates}
    assert {Decimal("129.99"), Decimal("159.99")} <= values


def test_int_excludes_fractions() -> None:
    page = parse_page("<body><p>$12.99</p><p>$15</p></body>")

    candidates = generate_candidates(page, _target("int"))

    assert [c.normalized_value for c in candidates] == [15]


def test_text_candidates_include_title_og_and_headings() -> None:
    page = parse_page(load_fixture("ja_product.html"))
    target = _target("str", "title", "商品名")

    candidates = generate_candidates(page, target)

    texts = [c.text for c in candidates]
    assert texts[0] == "ワイヤレスイヤホン X100 | サンプルショップ"
    assert "ワイヤレスイヤホン X100" in texts
    # og:title and h1 share the same value: kept once, with the richer context.
    assert texts.count("ワイヤレスイヤホン X100") == 1


def test_empty_page_has_no_numbers() -> None:
    page = parse_page(load_fixture("empty_page.html"))

    candidates = generate_candidates(page, _target("int"))

    assert candidates == []


def test_remove_duplicates_keeps_candidate_with_more_context() -> None:
    items = [
        _candidate(100, {"tag": "<p>"}),
        _candidate(200, {"tag": "<p>"}),
        _candidate(100, {"tag": "<span>", "label": "価格"}),
    ]

    unique = remove_duplicates(items)

    assert unique == [items[1], items[2]]


def test_keep_top_candidates_keeps_document_order() -> None:
    items = [_candidate(i, {}, score=i % 7) for i in range(300)]

    kept = keep_top_candidates(items)

    assert len(kept) == MAX_CANDIDATES
    assert [c.normalized_value for c in kept] == sorted(c.normalized_value for c in kept)
    assert min(c.score for c in kept) >= max(c.score for c in items if c not in kept)


def test_generate_candidates_returns_at_most_254() -> None:
    page = parse_page("<body>" + "".join(f"<p>¥{i:,}</p>" for i in range(1000, 1400)) + "</body>")

    candidates = generate_candidates(page, _target("int"))

    assert len(candidates) == MAX_CANDIDATES
