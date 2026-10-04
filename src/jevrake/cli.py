"""Command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from ._internal import api
from ._internal.client import JevAuthError, JevClient, TypeSafeJevClient
from ._internal.fetch import DEFAULT_DELAY, HttpxFetcher
from ._internal.schema import SchemaError, build_model_from_cli_fields
from ._internal.version import VERSION

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_INPUT = 2
EXIT_AUTH = 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jevrake",
        description="Selector-free web scraping powered by TypeSafe AI's Jev.",
    )
    parser.add_argument("urls", nargs="+", metavar="URL")
    parser.add_argument(
        "-f",
        "--field",
        action="append",
        required=True,
        metavar="FIELD",
        help="field to extract as name:description[:type] (type defaults to str)",
    )
    parser.add_argument(
        "-o", "--output", type=Path, metavar="FILE", help="write JSON to FILE instead of stdout"
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=api.DEFAULT_MIN_CONFIDENCE,
        metavar="FLOAT",
        help="discard values below this confidence (default: %(default)s)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        metavar="FLOAT",
        help="seconds between requests to the same host (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the Jev request instead of sending it"
    )
    parser.add_argument("--version", action="version", version=f"jevrake {VERSION}")
    return parser


def _print_dry_run(url: str, payload: dict[str, Any]) -> None:
    print(json.dumps({"url": url, "request": payload}, ensure_ascii=False, indent=2))


async def _run(args: argparse.Namespace) -> int:
    if not 0 <= args.min_confidence <= 1:
        raise SchemaError("--min-confidence must be between 0 and 1")

    model = build_model_from_cli_fields(args.field)

    async with AsyncExitStack() as stack:
        client: JevClient | None = None
        if not args.dry_run:
            jev_client = TypeSafeJevClient()
            stack.push_async_callback(jev_client.aclose)
            client = jev_client

        fetcher = await stack.enter_async_context(HttpxFetcher(delay=args.delay))

        results = await api.arake_many(
            args.urls,
            model,
            min_confidence=args.min_confidence,
            fetcher=fetcher,
            client=client,
            dry_run=args.dry_run,
            on_request=_print_dry_run if args.dry_run else None,
        )

    # A page with any error is left out of the output; its errors go to stderr only.
    succeeded = [r for r in results if not r.errors]
    failed = [r for r in results if r.errors]
    for result in failed:
        for error in result.errors:
            print(f"[error] {result.url}: {error}", file=sys.stderr)
    if not args.dry_run:
        text = json.dumps(
            [r.model_dump(mode="json", exclude={"errors"}) for r in succeeded],
            ensure_ascii=False,
            indent=2,
        )
        if args.output is None:
            print(text)
        else:
            args.output.write_text(text + "\n", encoding="utf-8")
    return EXIT_PARTIAL if failed else EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except SchemaError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INPUT
    except JevAuthError as e:
        print(f"authentication error: {e}", file=sys.stderr)
        return EXIT_AUTH


if __name__ == "__main__":
    sys.exit(main())
