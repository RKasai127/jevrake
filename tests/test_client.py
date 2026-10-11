import pytest

from jevrake._internal.client import TypeSafeJevClient
from jevrake._internal.exceptions import MissingAPIKeyError


def test_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError, match="TYPESAFE_API_KEY"):
        TypeSafeJevClient()
