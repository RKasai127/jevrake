"""Extract every book on the first page of books.toscrape.com, a site made for scraping practice.

Run from the repository root (needs TYPESAFE_API_KEY):

    uv run python examples/example.py

Options of ``rake()`` you can change:

- ``min_confidence``: values Jev is less sure of than this are discarded (0 to 1, default 0.9)
- ``delay``: seconds to wait between requests to the same site (default 1.0)
- ``dry_run``: True only builds the Jev requests without sending them (no API cost)
"""

from decimal import Decimal

from pydantic import BaseModel, Field

from jevrake import rake


class Book(BaseModel):
    title: str = Field(description="Book title")
    price: Decimal = Field(description="Price")
    availability: str = Field(description="Availability")


results = rake(
    ["https://books.toscrape.com/"],
    Book,
    min_confidence=0.9,
    delay=1.0,
)

for result in results:
    for item in result.items:
        book = item.data
        print(f"{book.title}: £{book.price} ({book.availability})")
    for error in result.errors:
        print(f"[error] {result.url}: {error}")
