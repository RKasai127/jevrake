from collections.abc import Callable

import httpx2
import pytest
from typesafe_sdk import Choice

from jevrake._internal import client as client_module
from jevrake._internal.client import TypeSafeJevClient
from jevrake._internal.exceptions import JevAuthError, JevError, MissingAPIKeyError
from jevrake._internal.models import JevChoiceAnswer

QUESTIONS = {"price": Choice(instructions="Which is the price?", criteria={"c0": "¥3,980"})}


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch) -> Callable[..., TypeSafeJevClient]:
    """A real TypeSafeJevClient whose HTTP calls are answered by ``handler``."""
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setattr(client_module, "MAX_RETRIES", 0)  # no slow retries in tests

    def make(handler: Callable[[httpx2.Request], httpx2.Response]) -> TypeSafeJevClient:
        return TypeSafeJevClient(transport=httpx2.MockTransport(handler))

    return make


def test_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError, match="TYPESAFE_API_KEY"):
        TypeSafeJevClient()


def test_ask_converts_the_sdk_response(make_client: Callable[..., TypeSafeJevClient]) -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        body = {
            "model": "jev-latest",
            "usage": {"input_tokens": 10, "output_tokens": 1},
            "answers": {
                "price": {
                    "type": "choice",
                    "choice": "c0",
                    "confidence": 0.97,
                    "probabilities": {"c0": 0.97, "__none__": 0.03},
                }
            },
        }
        return httpx2.Response(200, json=body, headers={"x-typesafe-request-id": "req-1"})

    client = make_client(handler)

    response = client.ask({"url": "https://shop.example"}, QUESTIONS)

    assert response.choices == {
        "price": JevChoiceAnswer(
            choice="c0", confidence=0.97, probabilities={"c0": 0.97, "__none__": 0.03}
        )
    }
    assert response.request_id == "req-1"
    assert sent[0].headers["authorization"] == "Bearer test-key"


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_api_key_raises_auth_error(
    make_client: Callable[..., TypeSafeJevClient], status: int
) -> None:
    client = make_client(lambda request: httpx2.Response(status, json={"error": "denied"}))

    with pytest.raises(JevAuthError, match=f"HTTP {status}"):
        client.ask({}, QUESTIONS)


def test_server_error_raises_jev_error(make_client: Callable[..., TypeSafeJevClient]) -> None:
    client = make_client(lambda request: httpx2.Response(500, json={"error": "boom"}))

    with pytest.raises(JevError, match="HTTP 500") as excinfo:
        client.ask({}, QUESTIONS)

    assert not isinstance(excinfo.value, JevAuthError)


def test_timeout_raises_jev_error(make_client: Callable[..., TypeSafeJevClient]) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("too slow", request=request)

    client = make_client(handler)

    with pytest.raises(JevError, match="timed out"):
        client.ask({}, QUESTIONS)


def test_connection_error_raises_jev_error(make_client: Callable[..., TypeSafeJevClient]) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no network", request=request)

    client = make_client(handler)

    with pytest.raises(JevError, match="Jev API error"):
        client.ask({}, QUESTIONS)
