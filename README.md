# jevrake

<h3 align="center"><em>jevrake extracts typed values from web pages without CSS selectors, using TypeSafe AI's Jev.</em></h3>

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
that fits the description. Values always come from the page; nothing is made up.

- Works on list pages too: each repeated item (e.g. each shop in a list) becomes one record
- Types: `str`, `int`, `float`, `decimal`
- A value that is not found, or found with confidence below 0.9, becomes `null`
- robots.txt is not checked. Respecting each site's rules is up to you.

## License

MIT
