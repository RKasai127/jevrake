# jevrake

English | [日本語](README.ja.md)

<h3 align="center"><em>jevrake — a scraping tool powered by Jev</em></h3>

Example on [books.toscrape.com](https://books.toscrape.com/), a site made for scraping practice:

```sh
jevrake https://books.toscrape.com/ --fields '{"title": "Book title", "price": {"description": "Price", "type": "decimal"}, "availability": "Availability"}'
```

Output (1 of the 20 books on the page):

```json
{
  "url": "https://books.toscrape.com/",
  "data": {
    "title": "A Light in the ...",
    "price": "51.77",
    "availability": "In stock"
  },
  "fields": {
    "title": {"value": "A Light in the ...", "confidence": 1.0, "probability": 1.0, "source": "A Light in the ..."},
    "price": {"value": "51.77", "confidence": 0.98, "probability": 0.99, "source": "£51.77"},
    "availability": {"value": "In stock", "confidence": 1.0, "probability": 1.0, "source": "In stock"}
  }
}
```

## Install

```sh
pipx install git+https://github.com/RKasai127/jevrake
export TYPESAFE_API_KEY=your-api-key
```

## Usage

```sh
jevrake https://example.com/item/1 --fields '{"title": "Product name", "price": {"description": "Price", "type": "int"}}'
```

Or from Python:

```python
from pydantic import BaseModel, Field
from jevrake import rake


class Product(BaseModel):
    title: str = Field(description="Product name")
    price: int = Field(description="Price")


results = rake(["https://example.com/item/1"], Product)
```

jevrake collects every value on the page that matches each field's type, and Jev picks the one
that fits the description. Values always come from the page.

- Works on list pages too: each repeated item (e.g. each shop in a list) becomes one record
- Types: `str`, `int`, `float`, `decimal`
- A value that is not found, or found with confidence below 0.9, becomes `null`
- robots.txt is not checked. Please make sure you follow each site's rules.

## License

MIT
