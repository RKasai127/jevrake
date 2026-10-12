"""Send the question to Jev (TypeSafe AI API) and return its answer.

Wraps the official SDK so the rest of jevrake does not depend on SDK types or exceptions.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import typesafe_sdk as ts

from .exceptions import JevAuthError, JevError, MissingAPIKeyError
from .models import JevChoiceAnswer, JevResponse

if TYPE_CHECKING:
    import httpx2

API_KEY_ENV = "TYPESAFE_API_KEY"
MODEL = "jev-latest"
TIMEOUT = 30.0
MAX_RETRIES = 3

MISSING_API_KEY_MESSAGE = f"""\
{API_KEY_ENV} is not set.
Create an API key at https://console.typesafe.ai and set it with one of:
  export {API_KEY_ENV}=<your API key>
  cp .envrc.example .envrc  # fill in the key, then run `direnv allow`"""


class TypeSafeJevClient:
    """Jev client backed by ``typesafe_sdk.TypeSafeClient``.

    429 / 5xx responses are retried with exponential backoff (up to ``MAX_RETRIES`` times) by
    the SDK's retry policy.
    """

    def __init__(self, *, transport: httpx2.BaseTransport | None = None) -> None:
        api_key = os.environ.get(API_KEY_ENV)

        if not api_key:
            raise MissingAPIKeyError(MISSING_API_KEY_MESSAGE)

        self._client = ts.TypeSafeClient(
            api_key=api_key,
            retry=ts.RetryPolicy(max_retries=MAX_RETRIES, timeout=None),
            timeout=TIMEOUT,
            transport=transport,
        )

    def ask(self, state: Mapping[str, Any], questions: Mapping[str, Any]) -> JevResponse:
        try:
            response = self._client.system_one(state=dict(state), questions=questions, model=MODEL)
        except (ts.TypeSafeAuthenticationError, ts.TypeSafePermissionDeniedError) as e:
            raise JevAuthError(
                f"Jev API rejected the API key (HTTP {e.status}). Check {API_KEY_ENV}."
            ) from None
        except ts.TypeSafeAPITimeoutError:
            raise JevError("Jev API request timed out") from None
        except ts.TypeSafeAPIError as e:
            raise JevError(f"Jev API error (HTTP {e.status}): {e.body}") from None
        except ts.TypeSafeError as e:
            raise JevError(f"Jev API error: {e}") from None

        return JevResponse(
            choices={
                key: JevChoiceAnswer(
                    choice=answer.choice,
                    confidence=answer.confidence,
                    probabilities=dict(answer.probabilities),
                )
                for key, answer in response.choices.items()
            },
            request_id=response.request_id,
        )

    def close(self) -> None:
        self._client.close()
