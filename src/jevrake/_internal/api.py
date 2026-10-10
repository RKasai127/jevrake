"""Extract values from each page with ``rake()``.

For each URL: download the page, collect candidate values, ask Jev to choose one, and validate the
result with the user's model.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from . import collect, dom, jev
from .client import MODEL, JevClient, TypeSafeJevClient
from .exceptions import FetchError, JevAuthError, JevError
from .fetch import Fetcher, HttpxFetcher
from .models import ExtractionTarget, JevResponse, RakeResult
from .schema import build_targets_from_model

DEFAULT_MIN_CONFIDENCE = 0.9

RequestHook = Callable[[str, dict[str, Any]], None]


def _build_failed_result[T: BaseModel](model: type[T], url: str, error: str) -> RakeResult[T]:
    return RakeResult[model](url=url, data=None, fields={}, request_id=None, errors=[error])  # type: ignore[valid-type]


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
    found = {target.name: collect.generate_candidates(page, target) for target in targets}
    request = jev.build_jev_request(url, page, targets, found)

    if on_request is not None:
        on_request(url, jev.build_jev_payload(request, MODEL))
    if client is None:  # dry run
        return RakeResult[model](url=url, data=None, fields={}, request_id=None, errors=[])  # type: ignore[valid-type]

    response = JevResponse()
    if request.questions:
        try:
            response = client.ask(request.state, request.questions)
        except JevAuthError:
            raise
        except JevError as e:
            return _build_failed_result(model, url, str(e))

    result = jev.parse_jev_response(request, response, targets, min_confidence)
    errors = list(result.errors)
    data = None
    if not errors:
        try:
            data = model.model_validate(result.values)
        except ValidationError as e:
            errors.extend(_format_validation_errors(e))
    return RakeResult[model](  # type: ignore[valid-type]
        url=url,
        data=data,
        fields=result.fields,
        request_id=response.request_id,
        errors=errors,
    )


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
    """Extract ``model`` from each URL, one page at a time, in the order of ``urls``.

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
