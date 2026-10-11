from decimal import Decimal
from typing import Any

import pytest

from jevrake._internal.convert import convert_text, parse_number
from jevrake._internal.exceptions import CoercionError


@pytest.mark.parametrize(
    ("text", "kind", "expected"),
    [
        ("¥3,980", "int", 3980),
        ("￥３，９８０", "int", 3980),
        ("３９８０円", "int", 3980),
        ("4,980 円", "int", 4980),
        ("$1,299", "int", 1299),
        ("-12", "int", -12),
        ("$12.99", "decimal", Decimal("12.99")),
        ("€1,234.50", "float", 1234.5),
        ("  商品\n名 ", "str", "商品 名"),
    ],
)
def test_convert_text(text: str, kind: str, expected: Any) -> None:
    value = convert_text(text, kind)

    assert value == expected


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("$12.99", "int"),
        ("   ", "str"),
    ],
)
def test_convert_text_errors(text: str, kind: str) -> None:
    with pytest.raises(CoercionError):
        convert_text(text, kind)


@pytest.mark.parametrize("text", ["abc", "", "12-34", "3,98"])
def test_parse_number_errors(text: str) -> None:
    with pytest.raises(CoercionError):
        parse_number(text)
