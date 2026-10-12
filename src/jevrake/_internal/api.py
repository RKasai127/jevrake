"""Extract items from each page with ``rake()``.

For each URL: download the page, split it into items (the whole page is one item if it is not a
list), collect candidate values, ask Jev to choose one per field, and validate each item with the
user's model.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from . import collect, dom, jev
from .client import MODEL, TypeSafeJevClient
from .exceptions import FetchError, JevAuthError, JevError
from .fetch import DEFAULT_DELAY, HttpxFetcher
from .models import ExtractionTarget, ItemBlock, JevResponse, RakeItem, RakeResult
from .schema import build_targets_from_model

DEFAULT_MIN_CONFIDENCE = 0.9
MAX_ITEMS_PER_REQUEST = 20

RequestHook = Callable[[str, dict[str, Any]], None]


def _build_failed_result[T: BaseModel](model: type[T], url: str, error: str) -> RakeResult[T]:
    return RakeResult[model](url=url, items=[], request_ids=[], errors=[error])  # type: ignore[valid-type]


def _format_validation_errors(error: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(part) for part in detail['loc'])}: {detail['msg']}"
        for detail in error.errors()
    ]


def _rake_page[T: BaseModel](
    url: str,
    model: type[T],
    targets: list[ExtractionTarget],
    fetcher: HttpxFetcher,
    client: TypeSafeJevClient | None,
    min_confidence: float,
    on_request: RequestHook | None,
) -> RakeResult[T]:
    try:
        html = fetcher.fetch(url)
    except FetchError as e:
        return _build_failed_result(model, url, str(e))

    page = dom.parse_page(html)
    item_blocks = collect.find_item_blocks(page, targets)
    numbered_blocks: list[tuple[int | None, ItemBlock]] = (
        [(None, item_blocks[0])] if item_blocks[0].is_whole_page else list(enumerate(item_blocks))
    )

    items: list[RakeItem[T]] = []
    request_ids: list[str] = []
    errors: list[str] = []
    for start in range(0, len(numbered_blocks), MAX_ITEMS_PER_REQUEST):
        request_blocks = numbered_blocks[start : start + MAX_ITEMS_PER_REQUEST]
        candidates_by_item = {
            item_no: block.candidates_by_target for item_no, block in request_blocks
        }
        request = jev.build_jev_request(url, page, targets, candidates_by_item)
        if on_request is not None:
            on_request(url, jev.build_jev_payload(request, MODEL))
        if client is None:
            continue

        response = JevResponse()
        if request.questions:
            try:
                response = client.ask(request.state, request.questions)
            except JevAuthError:
                raise
            except JevError as e:
                first_item_no, last_item_no = request_blocks[0][0], request_blocks[-1][0]
                errors.append(
                    str(e)
                    if first_item_no is None
                    else f"items {first_item_no}-{last_item_no}: {e}"
                )
                continue
            if response.request_id:
                request_ids.append(response.request_id)

        for item_no, _ in request_blocks:
            error_prefix = "" if item_no is None else f"item {item_no}: "
            outcome = jev.parse_jev_response(request, response, targets, min_confidence, item_no)
            if outcome.errors:
                errors.extend(error_prefix + error for error in outcome.errors)
                continue
            try:
                data = model.model_validate(outcome.values)
            except ValidationError as e:
                errors.extend(error_prefix + error for error in _format_validation_errors(e))
                continue
            items.append(RakeItem[model](data=data, fields=outcome.fields))  # type: ignore[valid-type]

    return RakeResult[model](url=url, items=items, request_ids=request_ids, errors=errors)  # type: ignore[valid-type]


def _rake_page_safely[T: BaseModel](url: str, model: type[T], *args: Any) -> RakeResult[T]:
    try:
        return _rake_page(url, model, *args)
    except JevAuthError:
        raise
    except Exception as e:  # one bad page must not stop the others
        return _build_failed_result(model, url, f"{type(e).__name__}: {e}")


def rake[T: BaseModel](
    urls: Sequence[str],
    model: type[T],
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    delay: float = DEFAULT_DELAY,
    dry_run: bool = False,
    on_request: RequestHook | None = None,
) -> list[RakeResult[T]]:
    """Extract items of ``model`` from each URL, one page at a time, in the order of ``urls``.

    ``delay`` is the wait between requests to the same host. Raises :class:`JevAuthError` if the
    API key is missing or rejected.
    """
    targets = build_targets_from_model(model)

    # Made once here and passed down instead of per page: the fetcher remembers when each host
    # was last accessed (for ``delay``), and the client keeps its connection open.
    client = None if dry_run else TypeSafeJevClient()
    fetcher = HttpxFetcher(delay=delay)

    try:
        return [
            _rake_page_safely(url, model, targets, fetcher, client, min_confidence, on_request)
            for url in urls
        ]
    finally:
        fetcher.close()
        if client is not None:
            client.close()
