"""Convert candidate text into the target's type, e.g. ``"¥3,980"`` -> ``3980``.

Used to turn page text into values and to drop text that cannot be converted.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

from .exceptions import CoercionError


def normalize_text(text: str) -> str:
    """NFKC-normalize (full-width -> half-width) and collapse whitespace."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


CURRENCY_PREFIXES = "¥$€£"
CURRENCY_SUFFIXES = ("円", "ドル", "ユーロ", "USD", "JPY", "EUR", "yen")

NUMBER_RE = re.compile(
    r"(?<![\w.,/:\-])"
    r"(?P<prefix>[¥$€£]\s?)?"
    r"(?P<number>-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"(?P<suffix>\s?(?:円|ドル|ユーロ|USD|JPY|EUR|yen))?"
    r"(?!\d|,\d|[.:/\-]\d|[年月日時分秒])"
)


_PLAIN_NUMBER_RE = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")


def parse_number(text: str) -> Decimal:
    number_text = normalize_text(text).replace("\u2212", "-")
    number_text = number_text.strip(CURRENCY_PREFIXES + " ")
    for suffix in CURRENCY_SUFFIXES:
        number_text = number_text.removesuffix(suffix).strip()
    if not _PLAIN_NUMBER_RE.fullmatch(number_text):
        raise CoercionError(f"not a number: {text!r}")
    try:
        return Decimal(number_text.replace(",", ""))
    except InvalidOperation:
        raise CoercionError(f"not a number: {text!r}") from None


def _convert_to_int(text: str) -> int:
    value = parse_number(text)
    if value != value.to_integral_value():
        raise CoercionError(f"not an integer: {text!r}")
    return int(value)


def _convert_to_str(text: str) -> str:
    cleaned_text = " ".join(text.split())
    if not cleaned_text:
        raise CoercionError("empty string")
    return cleaned_text


_CONVERTERS: dict[str, Callable[[str], Any]] = {
    "str": _convert_to_str,
    "int": _convert_to_int,
    "float": lambda text: float(parse_number(text)),
    "decimal": parse_number,
}


def convert_text(text: str, kind: str) -> Any:
    """Convert ``text`` to the Python value for ``kind``. Raises :class:`CoercionError`."""
    try:
        converter = _CONVERTERS[kind]
    except KeyError:
        raise CoercionError(f"unsupported type: {kind}") from None
    return converter(text)
