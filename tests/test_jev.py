from decimal import Decimal

import pytest
from typesafe_sdk import Choice

from jevrake._internal.collect import generate_candidates
from jevrake._internal.dom import parse_page
from jevrake._internal.jev import (
    MAX_CHOICES,
    NONE_CHOICE,
    build_jev_payload,
    build_jev_request,
    describe_candidate,
    parse_jev_response,
)
from jevrake._internal.models import (
    ExtractionCandidate,
    ExtractionTarget,
    ItemBlock,
    JevChoiceAnswer,
    JevResponse,
    ParsedPage,
)

from .conftest import load_fixture

URL = "https://shop.example/item/1"
TARGETS = [
    ExtractionTarget(name="title", description="商品名", kind="str"),
    ExtractionTarget(name="price", description="税込の販売価格（円）", kind="int"),
    ExtractionTarget(
        name="list_price", description="通常価格", kind="decimal", nullable=True, required=False
    ),
]


def _page_and_candidates(
    fixture: str = "ja_product.html",
) -> tuple[ParsedPage, dict[str, list[ExtractionCandidate]]]:
    page = parse_page(load_fixture(fixture))
    whole = ItemBlock(elements=page.elements, is_whole_page=True)
    return page, {s.name: generate_candidates(page, whole, s) for s in TARGETS}


def _response(**choices: tuple[str, float]) -> JevResponse:
    return JevResponse(
        choices={
            name: JevChoiceAnswer(
                choice=choice, confidence=conf, probabilities={choice: conf * 0.9}
            )
            for name, (choice, conf) in choices.items()
        },
        request_id="req-1",
    )


def test_state() -> None:
    page, found = _page_and_candidates()

    request = build_jev_request(URL, page, TARGETS, {None: found})

    assert request.state == {
        "url": URL,
        "page_title": "ワイヤレスイヤホン X100 | サンプルショップ",
        "main_text": page.main_text,
    }


def test_choice_question_structure() -> None:
    page, found = _page_and_candidates()

    request = build_jev_request(URL, page, TARGETS, {None: found})

    price = request.questions["price"]
    assert isinstance(price, Choice)
    assert price.instructions == (
        'Which option is "税込の販売価格（円）"? '
        "Choose the option that represents the price of this page."
    )
    names = list(price.criteria)
    assert names[-1] == NONE_CHOICE
    assert names[:-1] == [f"c{i}" for i in range(len(names) - 1)]
    assert price.criteria["c0"] == '"¥3,980" | <span class=price> | nearby label: 販売価格'
    assert request.options["price"]["c0"].normalized_value == 3980


def test_page_text_is_not_in_instructions() -> None:
    page, found = _page_and_candidates()

    request = build_jev_request(URL, page, TARGETS, {None: found})

    for question in request.questions.values():
        instructions = question.instructions
        assert isinstance(instructions, str)
        assert "3,980" not in instructions
        assert "ワイヤレスイヤホン" not in instructions
        assert page.main_text not in instructions


def test_fields_without_candidates_are_skipped() -> None:
    page, found = _page_and_candidates("empty_page.html")

    request = build_jev_request(URL, page, TARGETS, {None: found})

    assert request.skipped == ["price", "list_price"]
    assert set(request.questions) == {"title"}


def test_choices_capped_at_255() -> None:
    page = parse_page("<body><p>x</p></body>")
    candidates = [ExtractionCandidate(text=str(i), normalized_value=i) for i in range(400)]

    request = build_jev_request(URL, page, [TARGETS[1]], {None: {"price": candidates}})

    assert len(request.questions["price"].criteria) == MAX_CHOICES


def test_describe_candidate_truncates_long_text() -> None:
    candidate = ExtractionCandidate(text="あ" * 500, normalized_value="x")

    description = describe_candidate(candidate)

    assert len(description) < 250


def test_parse_jev_response_success() -> None:
    page, found = _page_and_candidates()
    request = build_jev_request(URL, page, TARGETS, {None: found})
    response = _response(title=("c1", 0.95), price=("c0", 0.88), list_price=("c1", 0.7))

    result = parse_jev_response(request, response, TARGETS, min_confidence=0.6)

    assert result.errors == []
    assert result.values == {
        "title": "ワイヤレスイヤホン X100",
        "price": 3980,
        "list_price": Decimal("4980"),
    }
    price = result.fields["price"]
    assert (price.value, price.confidence, price.source) == (3980, 0.88, "¥3,980")
    assert price.probability == pytest.approx(0.88 * 0.9)


def test_parse_jev_response_discards_required_value_below_min_confidence() -> None:
    page, found = _page_and_candidates()
    request = build_jev_request(URL, page, TARGETS, {None: found})
    response = _response(title=("c1", 0.95), price=("c0", 0.5), list_price=("c1", 0.95))

    result = parse_jev_response(request, response, TARGETS, min_confidence=0.6)

    assert result.errors == ["price: confidence 0.50 is below 0.60 (rejected '¥3,980')"]
    assert "price" not in result.values
    price = result.fields["price"]
    assert (price.value, price.confidence, price.source) == (None, 0.5, "¥3,980")


def test_parse_jev_response_discards_optional_value_below_min_confidence_without_error() -> None:
    page, found = _page_and_candidates()
    request = build_jev_request(URL, page, TARGETS, {None: found})
    response = _response(title=("c1", 0.95), price=("c0", 0.95), list_price=("c1", 0.5))

    result = parse_jev_response(request, response, TARGETS, min_confidence=0.6)

    assert result.errors == []
    assert "list_price" not in result.values  # optional with default: left to the default
    assert result.fields["list_price"].value is None


def test_parse_jev_response_none_for_required_is_error() -> None:
    page, found = _page_and_candidates()
    request = build_jev_request(URL, page, TARGETS, {None: found})
    response = _response(title=("c0", 0.9), price=(NONE_CHOICE, 0.9), list_price=(NONE_CHOICE, 0.9))

    result = parse_jev_response(request, response, TARGETS, min_confidence=0.6)

    assert result.errors == ["price: no matching value (Jev chose __none__)"]
    assert result.fields["price"].value is None
    assert "list_price" not in result.values  # optional with default: left to the default


def test_parse_jev_response_nullable_required_field_gets_none() -> None:
    target = ExtractionTarget(
        name="n", description="数量", kind="int", nullable=True, required=True
    )
    page = parse_page(load_fixture("empty_page.html"))
    request = build_jev_request(URL, page, [target], {None: {"n": []}})

    result = parse_jev_response(request, JevResponse(), [target], 0.6)

    assert result.values == {"n": None}
    assert result.errors == []


def test_build_jev_payload() -> None:
    page, found = _page_and_candidates()
    request = build_jev_request(URL, page, TARGETS, {None: found})

    payload = build_jev_payload(request, "jev-latest")

    assert payload["model"] == "jev-latest"
    assert payload["questions"]["price"]["type"] == "choice"


def test_list_page_questions_are_numbered_per_item() -> None:
    page = parse_page("<body><p>x</p></body>")
    shop_a = [ExtractionCandidate(text="A店", normalized_value="A店")]
    shop_b = [ExtractionCandidate(text="B店", normalized_value="B店")]
    target = ExtractionTarget(name="name", description="店名", kind="str")

    candidates: dict[int | None, dict[str, list[ExtractionCandidate]]] = {
        0: {"name": shop_a},
        1: {"name": shop_b},
    }

    request = build_jev_request(URL, page, [target], candidates)

    assert list(request.questions) == ["item0.name", "item1.name"]
    question = request.questions["item1.name"]
    assert question.instructions == (
        'Which option is "店名"? Choose the option that represents the name of item 1 on this page.'
    )
    assert question.criteria["c0"] == '"B店"'


def test_parse_jev_response_for_one_item() -> None:
    page = parse_page("<body><p>x</p></body>")
    target = ExtractionTarget(name="name", description="店名", kind="str")
    candidates: dict[int | None, dict[str, list[ExtractionCandidate]]] = {
        0: {"name": [ExtractionCandidate(text="A店", normalized_value="A店")]},
        1: {"name": [ExtractionCandidate(text="B店", normalized_value="B店")]},
    }
    request = build_jev_request(URL, page, [target], candidates)
    response = _response(**{"item0.name": ("c0", 0.95), "item1.name": ("__none__", 0.95)})

    first = parse_jev_response(request, response, [target], 0.9, item=0)
    second = parse_jev_response(request, response, [target], 0.9, item=1)

    assert first.values == {"name": "A店"}
    assert second.errors == ["name: no matching value (Jev chose __none__)"]
