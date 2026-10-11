"""Extract records from each page with ``rake()``.

For each URL: download the page, split it into items (one for a single-record page), collect
candidate values, ask Jev to choose one per field, and validate each item with the user's model.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from . import collect, dom, jev
from .client import MODEL, JevClient, TypeSafeJevClient
from .exceptions import FetchError, JevAuthError, JevError
from .fetch import Fetcher, HttpxFetcher
from .models import ExtractionTarget, ItemBlock, JevResponse, RakeItem, RakeResult
from .schema import build_targets_from_model

DEFAULT_MIN_CONFIDENCE = 0.9
MAX_ITEMS_PER_REQUEST = 20

RequestHook = Callable[[str, dict[str, Any]], None]


def _build_failed_result[T: BaseModel](model: type[T], url: str, error: str) -> RakeResult[T]:
    return RakeResult[model](url=url, items=[], request_ids=[], errors=[error])  # type: ignore[valid-type]


def _format_validation_errors(error: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in error.errors()]


def _rake_page[T: BaseModel](
    url: str,
    model: type[T],
    targets: list[ExtractionTarget],
    fetcher: Fetcher,
    client: JevClient | None,
    min_confidence: float,
    on_request: RequestHook | None,
) -> RakeResult[T]:
    try:
        html = fetcher.fetch(url)
    except FetchError as e:
        return _build_failed_result(model, url, str(e))

    page = dom.parse_page(html)
    blocks = collect.find_item_blocks(page, targets)
    numbered: list[tuple[int | None, ItemBlock]] = (
        [(None, blocks[0])] if blocks[0].is_whole_page else list(enumerate(blocks))
    )

    items: list[RakeItem[T]] = []
    request_ids: list[str] = []
    errors: list[str] = []
    for start in range(0, len(numbered), MAX_ITEMS_PER_REQUEST):
        chunk = numbered[start : start + MAX_ITEMS_PER_REQUEST]
        candidates_by_item = {item: block.candidates for item, block in chunk}
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
                first, last = chunk[0][0], chunk[-1][0]
                errors.append(str(e) if first is None else f"items {first}-{last}: {e}")
                continue
            if response.request_id:
                request_ids.append(response.request_id)

        for item, _ in chunk:
            prefix = "" if item is None else f"item {item}: "
            outcome = jev.parse_jev_response(request, response, targets, min_confidence, item)
            if outcome.errors:
                errors.extend(prefix + e for e in outcome.errors)
                continue
            try:
                data = model.model_validate(outcome.values)
            except ValidationError as e:
                errors.extend(prefix + m for m in _format_validation_errors(e))
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
    fetcher: Fetcher | None = None,
    client: JevClient | None = None,
    dry_run: bool = False,
    on_request: RequestHook | None = None,
) -> list[RakeResult[T]]:
    """Extract records of ``model`` from each URL, one page at a time, in the order of ``urls``.

    Raises :class:`JevAuthError` if the API key is missing or rejected.
    """
    targets = build_targets_from_model(model)

    created: list[HttpxFetcher | TypeSafeJevClient] = []
    if fetcher is None:
        fetcher = HttpxFetcher()
        created.append(fetcher)
    if dry_run:
        client = None
    elif client is None:
        client = TypeSafeJevClient()
        created.append(client)

    try:
        return [
            _rake_page_safely(url, model, targets, fetcher, client, min_confidence, on_request)
            for url in urls
        ]
    finally:
        for resource in created:
            resource.close()
