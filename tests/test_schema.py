import re
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

import pytest
from pydantic import BaseModel, Field

from jevrake._internal.exceptions import SchemaError
from jevrake._internal.schema import build_model_from_fields_json, build_targets_from_model


class Product(BaseModel):
    title: str = Field(description="商品名")
    price: int = Field(description="税込の販売価格（円）")
    rating: float
    exact: Decimal
    note: str | None = None
    quantity: Optional[int]  # noqa: UP045


def test_targets_from_model() -> None:
    targets = {s.name: s for s in build_targets_from_model(Product)}

    assert {n: s.kind for n, s in targets.items()} == {
        "title": "str",
        "price": "int",
        "rating": "float",
        "exact": "decimal",
        "note": "str",
        "quantity": "int",
    }
    assert targets["title"].description == "商品名"
    assert targets["rating"].description == "rating"
    assert targets["note"].is_optional
    assert not targets["note"].required
    assert targets["quantity"].nullable
    assert targets["quantity"].required
    assert not targets["price"].is_optional


@pytest.mark.parametrize("annotation", [bool, date, Literal["a", "b"], list[str]])
def test_unsupported_types(annotation: object) -> None:
    class Bad(BaseModel):
        value: annotation  # type: ignore[valid-type]

    with pytest.raises(SchemaError, match="value"):
        build_targets_from_model(Bad)


def test_build_model_from_fields_json() -> None:
    text = '{"title": "商品名", "price": {"description": "税込価格", "type": "int"}, "note": {}}'

    model = build_model_from_fields_json(text)

    targets = {s.name: s for s in build_targets_from_model(model)}
    assert {n: (s.kind, s.description) for n, s in targets.items()} == {
        "title": ("str", "商品名"),
        "price": ("int", "税込価格"),
        "note": ("str", "note"),
    }
    assert all(not s.is_optional for s in targets.values())


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"title": "商品名"', "--fields is not valid JSON"),
        ('["title"]', "--fields must be a non-empty JSON object"),
        ("{}", "--fields must be a non-empty JSON object"),
        ('{"1bad": "x"}', "invalid field name '1bad'"),
        ('{"_x": "x"}', "invalid field name '_x'"),
        ('{"title": "a", "title": "b"}', "duplicate field name 'title'"),
        ('{"price": {"type": "money"}}', "--fields.price.type:"),
        ('{"price": {"desc": "x"}}', "--fields.price.desc:"),
        ('{"price": 1}', "--fields.price:"),
    ],
)
def test_build_model_from_fields_json_errors(text: str, message: str) -> None:
    with pytest.raises(SchemaError, match=re.escape(message)):
        build_model_from_fields_json(text)
