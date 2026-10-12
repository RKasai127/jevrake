import time
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field

from jevrake import ExtractedValue, __version__, rake
from jevrake._internal import api
from jevrake._internal.exceptions import JevAuthError, JevError
from jevrake._internal.fetch import HttpxFetcher
from jevrake._internal.models import JevResponse

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


Install = Callable[..., None]


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch) -> Install:
    """Make ``rake()`` use ``jev`` and ``page_fetcher`` (the fake site by default)."""

    def install_fakes(jev: FakeJev, page_fetcher: Any = None) -> None:
        used = page_fetcher if page_fetcher is not None else fetcher()
        monkeypatch.setattr(api, "HttpxFetcher", lambda delay: used)
        monkeypatch.setattr(api, "TypeSafeJevClient", lambda: jev)

    return install_fakes


def test_rake_japanese_product(install: Install) -> None:
    jev = FakeJev(PICKS)
    install(jev)

    result = rake([f"{BASE}/ja"], Product)[0]

    assert result.errors == []
    assert len(result.items) == 1
    item = result.items[0]
    assert item.data == Product(
        title="ワイヤレスイヤホン X100", price=3980, list_price=Decimal("4980")
    )
    assert result.request_ids == ["req-1"]
    assert item.fields["price"] == ExtractedValue(
        value=3980, confidence=0.9, probability=0.9, source="¥3,980"
    )
    assert len(jev.calls) == 1
    call = jev.calls[0]
    assert call["state"]["url"] == f"{BASE}/ja"
    assert "var price" not in call["state"]["main_text"]


def test_values_below_min_confidence_are_discarded(install: Install) -> None:
    jev = FakeJev(PICKS, confidence=0.3)
    install(jev)

    result = rake([f"{BASE}/ja"], Product)[0]

    assert result.items == []
    assert "price: confidence 0.30 is below 0.90 (rejected '¥3,980')" in result.errors


def test_missing_required_value_gives_no_data(install: Install) -> None:
    jev = FakeJev({})
    install(jev)

    result = rake([f"{BASE}/empty"], Product)[0]

    assert result.items == []
    assert "price: no candidates found on the page" in result.errors
    assert "title: no matching value (Jev chose __none__)" in result.errors


def test_fetch_errors_are_collected(install: Install) -> None:
    jev = FakeJev(PICKS)
    urls = [f"{BASE}/missing", f"{BASE}/image.png", "ftp://x/y", f"{BASE}/ja"]
    install(jev)

    results = rake(urls, Product)

    assert [r.url for r in results] == urls
    assert "HTTP 404" in results[0].errors[0]
    assert "not an HTML page" in results[1].errors[0]
    assert "http/https" in results[2].errors[0]
    assert results[3].errors == []
    assert len(jev.calls) == 1


def test_user_agent_sent_and_robots_txt_not_fetched(install: Install) -> None:
    requests: list[httpx.Request] = []
    install(FakeJev(), fetcher(transport=site(requests)))

    rake([f"{BASE}/ja"], Product)

    assert [r.url.path for r in requests] == ["/ja"]
    assert requests[0].headers["user-agent"] == f"jevrake/{__version__}"


def test_rate_limit_per_host(install: Install) -> None:
    times: dict[str, list[float]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        times.setdefault(request.url.host, []).append(time.monotonic())
        return httpx.Response(200, text="<p>x</p>", headers={"content-type": "text/html"})

    f = HttpxFetcher(transport=httpx.MockTransport(handler), delay=0.2)
    urls = ["https://a.example/1", "https://b.example/1", "https://a.example/2"]
    install(FakeJev(), f)

    rake(urls, Product)

    a, b = times["a.example"], times["b.example"]
    assert a[1] - a[0] >= 0.19
    assert b[0] - a[0] < 0.19


def test_auth_error_stops_the_run(install: Install) -> None:
    jev = FakeJev(error=AUTH_ERROR)
    urls = [f"{BASE}/ja", f"{BASE}/en"]
    install(jev)

    with pytest.raises(JevAuthError):
        rake(urls, Product)


def test_other_jev_errors_are_per_page(install: Install) -> None:
    jev = FakeJev(error=JevError("boom"))
    install(jev)

    result = rake([f"{BASE}/ja"], Product)[0]

    assert result.errors == ["boom"]
    assert result.items == []


def test_dry_run_does_not_call_jev(install: Install) -> None:
    seen = []
    install(FakeJev())

    results = rake(
        [f"{BASE}/ja"],
        Product,
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


class Shop(BaseModel):
    name: str = Field(description="店名")
    address: str = Field(description="住所")
    facilities: str | None = Field(default=None, description="設備")


SHOP_PICKS = {
    "name": "shop-name",
    "address": "nearby label: 住所",
    "facilities": "nearby label: 設備",
}


def test_list_page_returns_one_item_per_shop(install: Install) -> None:
    jev = FakeJev(SHOP_PICKS)
    install(jev)

    result = rake([f"{BASE}/shops"], Shop)[0]

    assert [item.data.name for item in result.items] == [
        "アルファ新宿店",
        "ベータ渋谷店",
        "デルタ上野店",
    ]
    assert result.items[0].data.address == "東京都新宿区西新宿1-1-1"
    assert result.items[0].data.facilities == "駐車場あり・喫煙所あり"
    assert result.errors == ["item 2: address: no matching value (Jev chose __none__)"]
    assert len(jev.calls) == 1


def _list_page(count: int) -> str:
    shops = "".join(
        f'<li class="shop"><h3 class="shop-name">店舗{i}</h3><p>住所 東京都{i}</p></li>'
        for i in range(count)
    )
    return f"<html><body><ul>{shops}</ul></body></html>"


def _fetcher_for(html: str) -> HttpxFetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    return HttpxFetcher(transport=httpx.MockTransport(handler), delay=0)


def test_large_list_page_is_sent_in_several_requests(install: Install) -> None:
    jev = FakeJev({"name": "shop-name", "address": "住所"})
    install(jev, _fetcher_for(_list_page(25)))

    result = rake([f"{BASE}/many"], Shop)[0]

    assert [len(call["questions"]) for call in jev.calls] == [20 * 3, 5 * 3]
    assert len(result.items) == 25
    assert result.request_ids == ["req-1", "req-2"]


class FailingSecondCall(FakeJev):
    def ask(self, state: Mapping[str, Any], questions: Mapping[str, Any]) -> JevResponse:
        if self.calls:
            self.calls.append({"state": state, "questions": questions})
            raise JevError("boom")
        return super().ask(state, questions)


def test_failed_request_loses_only_its_own_items(install: Install) -> None:
    jev = FailingSecondCall({"name": "shop-name", "address": "住所"})
    install(jev, _fetcher_for(_list_page(25)))

    result = rake([f"{BASE}/many"], Shop)[0]

    assert len(result.items) == 20
    assert result.errors == ["items 20-24: boom"]


def test_model_validation_failure_drops_the_item(install: Install) -> None:
    class ExpensiveProduct(BaseModel):
        price: int = Field(gt=10000, description="税込の販売価格（円）")

    jev = FakeJev(PICKS)
    install(jev)

    result = rake([f"{BASE}/ja"], ExpensiveProduct)[0]

    assert result.items == []
    assert result.errors == ["price: Input should be greater than 10000"]


class BrokenFetcher:
    """Fails with an unexpected error (a bug) for one URL and works for the others."""

    def __init__(self) -> None:
        self.fetcher = fetcher()

    def fetch(self, url: str) -> str:
        if url.endswith("/broken"):
            raise RuntimeError("unexpected bug")
        return self.fetcher.fetch(url)

    def close(self) -> None:
        self.fetcher.close()


def test_unexpected_error_on_one_page_does_not_stop_the_others(install: Install) -> None:
    jev = FakeJev(PICKS)
    install(jev, BrokenFetcher())

    results = rake([f"{BASE}/broken", f"{BASE}/ja"], Product)

    assert results[0].errors == ["RuntimeError: unexpected bug"]
    assert len(results[1].items) == 1


class ClosingFakeJev(FakeJev):
    closed = False

    def close(self) -> None:
        self.closed = True


class ClosingFetcher(HttpxFetcher):
    closed = False

    def close(self) -> None:
        self.closed = True
        super().close()


def test_fetcher_and_client_are_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    created_fetcher = ClosingFetcher(transport=site(), delay=0)
    created_client = ClosingFakeJev(PICKS)
    delays: list[float] = []

    def make_fetcher(delay: float) -> HttpxFetcher:
        delays.append(delay)
        return created_fetcher

    monkeypatch.setattr(api, "HttpxFetcher", make_fetcher)
    monkeypatch.setattr(api, "TypeSafeJevClient", lambda: created_client)

    results = rake([f"{BASE}/ja"], Product, delay=2.5)

    assert len(results[0].items) == 1
    assert delays == [2.5]
    assert created_fetcher.closed
    assert created_client.closed


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (httpx.ConnectTimeout("slow"), "request timed out"),
        (httpx.ConnectError("refused"), "request failed"),
    ],
)
def test_fetch_errors_become_page_errors(install: Install, error: Exception, message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    install(FakeJev(PICKS), HttpxFetcher(transport=httpx.MockTransport(handler), delay=0))

    result = rake([f"{BASE}/ja"], Product)[0]

    assert result.items == []
    assert message in result.errors[0]
