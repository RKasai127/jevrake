"""Test doubles: an httpx MockTransport site and a scripted Jev client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from jevrake._internal.exceptions import JevAuthError
from jevrake._internal.models import JevChoiceAnswer, JevResponse

from .conftest import load_fixture

PAGES = {
    "/ja": "ja_product.html",
    "/en": "en_product.html",
    "/empty": "empty_page.html",
    "/shops": "shop_list.html",
}


def site(requests: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        path = request.url.path
        if path in PAGES:
            return httpx.Response(
                200,
                text=load_fixture(PAGES[path]),
                headers={"content-type": "text/html; charset=utf-8"},
            )
        if path == "/image.png":
            return httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


class FakeJev:
    """Answers each question with the first choice whose description contains the pick."""

    def __init__(
        self,
        picks: Mapping[str, str] | None = None,
        *,
        confidence: float = 0.9,
        error: Exception | None = None,
    ) -> None:
        self.picks = dict(picks or {})
        self.confidence = confidence
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def ask(self, state: Mapping[str, Any], questions: Mapping[str, Any]) -> JevResponse:
        self.calls.append({"state": state, "questions": questions})
        if self.error is not None:
            raise self.error
        choices = {}
        for name, question in questions.items():
            wanted = self.picks.get(name.split(".")[-1])
            choice = next(
                (key for key, desc in question.criteria.items() if wanted and wanted in desc),
                "__none__",
            )
            choices[name] = JevChoiceAnswer(
                choice=choice,
                confidence=self.confidence,
                probabilities={choice: self.confidence},
            )
        return JevResponse(choices=choices, request_id=f"req-{len(self.calls)}")

    def close(self) -> None:
        pass


AUTH_ERROR = JevAuthError("Jev API rejected the API key (HTTP 401)")
