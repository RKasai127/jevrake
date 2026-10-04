import functools
import json
from pathlib import Path

import pytest

from jevrake import cli
from jevrake._internal.fetch import HttpxFetcher

from .fakes import AUTH_ERROR, FakeJev, site

BASE = "https://shop.example"
PICKS = {"title": "og:title", "price": "販売価格"}
ARGS = [f"{BASE}/ja", "-f", "title:商品名", "-f", "price:税込価格:int", "--delay", "0"]


@pytest.fixture
def jev(monkeypatch: pytest.MonkeyPatch) -> FakeJev:
    fake = FakeJev(PICKS)
    monkeypatch.setattr(cli, "HttpxFetcher", functools.partial(HttpxFetcher, transport=site()))
    monkeypatch.setattr(cli, "TypeSafeJevClient", lambda: fake)
    return fake


def _run_cli(argv: list[str]) -> int | str | None:
    """Run the CLI and return its exit code, including argparse's SystemExit."""
    try:
        return cli.main(argv)
    except SystemExit as e:
        return e.code


def test_prints_extracted_result_to_stdout(
    jev: FakeJev, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli.main(ARGS)

    assert exit_code == cli.EXIT_OK
    results = json.loads(capsys.readouterr().out)
    assert len(results) == 1
    row = results[0]
    assert row["data"] == {"title": "ワイヤレスイヤホン X100", "price": 3980}
    assert row["fields"]["price"]["source"] == "¥3,980"
    assert "errors" not in row


def test_writes_only_successful_pages_to_file(
    jev: FakeJev, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "result.json"
    argv = [f"{BASE}/missing", *ARGS, "-o", str(out)]

    exit_code = cli.main(argv)

    assert exit_code == cli.EXIT_PARTIAL
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert [r["url"] for r in rows] == [f"{BASE}/ja"]
    assert f"[error] {BASE}/missing: HTTP 404" in capsys.readouterr().err


def test_pages_below_min_confidence_are_left_out(
    jev: FakeJev, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = [*ARGS, "--min-confidence", "0.95"]

    exit_code = cli.main(argv)

    assert exit_code == cli.EXIT_PARTIAL
    captured = capsys.readouterr()
    assert json.loads(captured.out) == []
    assert "confidence 0.90 is below 0.95" in captured.err


def test_dry_run_prints_request_without_api_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(cli, "HttpxFetcher", functools.partial(HttpxFetcher, transport=site()))

    exit_code = cli.main([*ARGS, "--dry-run"])

    assert exit_code == cli.EXIT_OK
    printed = json.loads(capsys.readouterr().out)
    assert printed["url"] == f"{BASE}/ja"
    assert printed["request"]["model"] == "jev-latest"
    assert set(printed["request"]["questions"]) == {"title", "price"}


def test_missing_api_key_is_reported_as_auth_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    exit_code = cli.main(ARGS)

    assert exit_code == cli.EXIT_AUTH
    assert "TYPESAFE_API_KEY" in capsys.readouterr().err


def test_rejected_api_key_is_reported_as_auth_error(jev: FakeJev) -> None:
    jev.error = AUTH_ERROR

    exit_code = cli.main(ARGS)

    assert exit_code == cli.EXIT_AUTH


@pytest.mark.parametrize(
    "argv",
    [
        [f"{BASE}/ja"],
        [*ARGS, "-f", "title:重複"],
        [*ARGS, "-f", "1bad:x"],
        [*ARGS, "--min-confidence", "1.5"],
    ],
)
def test_invalid_input_is_reported_as_input_error(jev: FakeJev, argv: list[str]) -> None:
    exit_code = _run_cli(argv)

    assert exit_code == cli.EXIT_INPUT
