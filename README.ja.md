<p align="right"><a href="https://github.com/RKasai127/jevrake/blob/main/README.md">English</a> | 日本語</p>

# jevrake — Jevを利用したスクレイピングツール

スクレイピング練習用サイト [books.toscrape.com](https://books.toscrape.com/) での実行例：

```sh
jevrake https://books.toscrape.com/ --fields '{"title": "本のタイトル", "price": {"description": "価格", "type": "decimal"}, "availability": "在庫状況"}'
```

出力（ページ上の本20冊のうち1冊分）：

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

## インストール

```sh
pipx install jevrake
export TYPESAFE_API_KEY=あなたのAPIキー
```

## 使い方

```sh
jevrake https://example.com/item/1 --fields '{"title": "商品名", "price": {"description": "価格", "type": "int"}}'
```

Python からも使えます：

```python
from pydantic import BaseModel, Field
from jevrake import rake


class Product(BaseModel):
    title: str = Field(description="商品名")
    price: int = Field(description="価格")


results = rake(["https://example.com/item/1"], Product)
```

そのまま動かせる例は [examples/example.py](https://github.com/RKasai127/jevrake/blob/main/examples/example.py) にあります。

jevrake は、ページ上から各項目の型に合う値をすべて集め、その中から説明に合うものを Jev に選ばせます。値は必ずページ上に実在するものから選ばれます。

- 一覧ページにも対応しています。一覧の1件ずつ（各店舗など）が、それぞれ別々に出力されます
- 型：`str`、`int`、`float`、`decimal`
- 見つからなかった値や、確信度が0.9未満の値は `null` になります
- robots.txt は確認しません。各サイトのルールを守るのは利用者の責任でお願いいたします。

## ライセンス

MIT
