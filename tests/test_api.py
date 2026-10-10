import time
from decimal import Decimal

import httpx
import pytest
from pydantic import BaseModel, Field

from jevrake import ExtractedValue, rake
from jevrake._internal.exceptions import JevAuthError, JevError
from jevrake._internal.fetch import HttpxFetcher

from .fakes import AUTH_ERROR, FakeJev, site

BASE = "https://shop.example"


class Product(BaseModel):
    title: str = Field(description="商品名")
    price: int = Field(description="税込の販売価格（円）")
    list_price: Decimal | None = Field(default=None, description="通常価格")


PICKS = {
    "title": '"ワイヤレスイヤホン X100" | og:title',
    "price": "販売価格",
    "list_price": "通常価格",
}


def fetcher(**kwargs) -> HttpxFetcher:
    kwargs.setdefault("transport", site())
    kwargs.setdefault("delay", 0)
    return HttpxFetcher(**kwargs)


def test_rake_japanese_product() -> None:
    jev = FakeJev(PICKS)

    result = rake([f"{BASE}/ja"], Product, fetcher=fetcher(), client=jev)[0]

    assert result.errors == []
    assert result.data == Product(
        title="ワイヤレスイヤホン X100", price=3980, list_price=Decimal("4980")
    )
    assert result.request_id == "req-1"
    assert result.fields["price"] == ExtractedValue(
        value=3980, confidence=0.9, probability=0.9, source="¥3,980"
    )
    assert len(jev.calls) == 1
    call = jev.calls[0]
    assert call["state"]["url"] == f"{BASE}/ja"
    assert "var price" not in call["state"]["main_text"]


def test_values_below_min_confidence_are_discarded() -> None:
    jev = FakeJev(PICKS, confidence=0.3)

    result = rake([f"{BASE}/ja"], Product, fetcher=fetcher(), client=jev)[0]

    assert result.data is None
    assert "price: confidence 0.30 is below 0.90 (rejected '¥3,980')" in result.errors
    assert all(f.value is None for f in result.fields.values())


def test_missing_required_value_gives_no_data() -> None:
    jev = FakeJev({})

    result = rake([f"{BASE}/empty"], Product, fetcher=fetcher(), client=jev)[0]

    assert result.data is None
    assert "price: no candidates found on the page" in result.errors
    assert "title: no matching value (Jev chose __none__)" in result.errors
    assert "list_price" in result.fields


def test_fetch_errors_are_collected() -> None:
    jev = FakeJev(PICKS)
    urls = [f"{BASE}/missing", f"{BASE}/image.png", "ftp://x/y", f"{BASE}/ja"]

    results = rake(urls, Product, fetcher=fetcher(), client=jev)

    assert [r.url for r in results] == urls
    assert "HTTP 404" in results[0].errors[0]
    assert "not an HTML page" in results[1].errors[0]
    assert "http/https" in results[2].errors[0]
    assert results[3].errors == []
    assert len(jev.calls) == 1


def test_user_agent_sent_and_robots_txt_not_fetched() -> None:
    requests: list[httpx.Request] = []

    rake([f"{BASE}/ja"], Product, fetcher=fetcher(transport=site(requests)), client=FakeJev())

    assert [r.url.path for r in requests] == ["/ja"]
    assert requests[0].headers["user-agent"] == "jevrake/0.1.0"


def test_rate_limit_per_host() -> None:
    times: dict[str, list[float]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        times.setdefault(request.url.host, []).append(time.monotonic())
        return httpx.Response(200, text="<p>x</p>", headers={"content-type": "text/html"})

    f = HttpxFetcher(transport=httpx.MockTransport(handler), delay=0.2)
    urls = ["https://a.example/1", "https://b.example/1", "https://a.example/2"]

    rake(urls, Product, fetcher=f, client=FakeJev())

    a, b = times["a.example"], times["b.example"]
    assert a[1] - a[0] >= 0.19  # same host: waits for the delay
    assert b[0] - a[0] < 0.19  # another host: no wait


def test_auth_error_stops_the_run() -> None:
    jev = FakeJev(error=AUTH_ERROR)
    urls = [f"{BASE}/ja", f"{BASE}/en"]

    with pytest.raises(JevAuthError):
        rake(urls, Product, fetcher=fetcher(), client=jev)


def test_other_jev_errors_are_per_page() -> None:
    jev = FakeJev(error=JevError("boom"))

    result = rake([f"{BASE}/ja"], Product, fetcher=fetcher(), client=jev)[0]

    assert result.errors == ["boom"]
    assert result.data is None


def test_dry_run_does_not_call_jev() -> None:
    seen = []

    results = rake(
        [f"{BASE}/ja"],
        Product,
        fetcher=fetcher(),
        dry_run=True,
        on_request=lambda url, payload: seen.append((url, payload)),
    )

    assert results[0].errors == []
    assert len(seen) == 1
    url, payload = seen[0]
    assert url == f"{BASE}/ja"
    assert set(payload) == {"model", "state", "questions"}
    assert payload["model"] == "jev-latest"
    assert payload["questions"]["price"]["type"] == "choice"
