"""The ``jevrake`` command.

Reads URLs and ``--fields``, calls ``rake()``, and prints the pages that were fully extracted as
JSON. Errors are printed to stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ._internal import api
from ._internal.exceptions import JevAuthError, SchemaError
from ._internal.fetch import DEFAULT_DELAY
from ._internal.schema import build_model_from_fields_json
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
        "--fields",
        required=True,
        metavar="JSON",
        help='fields to extract as a JSON object, e.g. \'{"title": "Product name", '
        '"price": {"description": "Price", "type": "int"}}\' (type defaults to str)',
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


def _run_command(args: argparse.Namespace) -> int:
    if not 0 <= args.min_confidence <= 1:
        raise SchemaError("--min-confidence must be between 0 and 1")

    model = build_model_from_fields_json(args.fields)

    results = api.rake(
        args.urls,
        model,
        min_confidence=args.min_confidence,
        delay=args.delay,
        dry_run=args.dry_run,
        on_request=_print_dry_run if args.dry_run else None,
    )

    if not args.dry_run:
        records = [
            {"url": result.url, **item.model_dump(mode="json")}
            for result in results
            for item in result.items
        ]
        records_json = json.dumps(records, ensure_ascii=False, indent=2)
        if args.output is None:
            print(records_json)
        else:
            args.output.write_text(records_json + "\n", encoding="utf-8")

    failed_results = [result for result in results if result.errors]
    for result in failed_results:
        for error in result.errors:
            print(f"[error] {result.url}: {error}", file=sys.stderr)

    return EXIT_PARTIAL if failed_results else EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return _run_command(args)
    except SchemaError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INPUT
    except JevAuthError as e:
        print(f"authentication error: {e}", file=sys.stderr)
        return EXIT_AUTH


if __name__ == "__main__":
    sys.exit(main())
