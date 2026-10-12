# jevrake 仕様書（v0.1.0）

## 1. 概要

TypeSafe AI の Jev を使った、CSSセレクタ不要のWebスクレイピングツール。
利用者は取得したい項目（名前・説明・型）を定義するだけでよい。jevrake がページから型に合う値を候補として集め、説明に合うものを Jev に選ばせて、型付きのデータを返す。値は必ずページ上に実在するテキストから選ぶ。

- 詳細ページ（1ページ＝1件）と一覧ページ（1ページ＝複数件）の両方に対応する
- CLI と Python API の2つの使い方があり、中の処理は共通

対象外：JavaScript で描画されるページ、1項目に複数の値（`list[T]`）、ページ送りの自動追跡、ログインが必要なページ、robots.txt の確認。

## 2. 処理の流れ

```
① 取得        fetch.py     ページのHTMLを取得（同じホストへは delay 秒空ける）
② 整理        dom.py       不要な要素を除き、テキストを持つ要素と繰り返しのブロックを抽出
③ 一覧の判定  collect.py   一覧ページなら1件ごとのブロックに分ける（それ以外はページ全体で1件）
④ 候補集め    collect.py   ブロックごとに、各項目の型に合う値を候補として集める
⑤ 質問        jev.py       候補を選択肢にして、Jev への質問を組み立てる
⑥ 問い合わせ  client.py    Jev API に送る（1リクエスト最大20件分）
⑦ 解釈        jev.py       回答を値に戻す。確信度が足りない値は捨てる
⑧ 検証        api.py       1件ずつ利用者のモデルで検証し、結果を返す
```

## 3. Python API

```python
from pydantic import BaseModel, Field
from jevrake import rake


class Product(BaseModel):
    title: str = Field(description="商品名")
    price: int = Field(description="税込の販売価格（円）")
    stock: str | None = Field(default=None, description="在庫状況の表示")


results = rake(["https://example.com/item/1"], Product)
```

### 3.1 `rake(urls, model, *, ...) -> list[RakeResult]`

URL を先頭から1件ずつ順に処理し、URL と同じ順で1ページにつき1つの `RakeResult` を返す。

| 引数 | 既定 | 説明 |
|---|---|---|
| `urls` | （必須） | URL のリスト |
| `model` | （必須） | 取得する項目を定義した Pydantic モデル |
| `min_confidence` | `0.9` | これ未満の確信度の値は捨てる |
| `delay` | `1.0` | 同一ホストへのアクセス間隔（秒） |
| `dry_run` | `False` | Jev に送信しない |
| `on_request` | `None` | 送信内容を受け取るコールバック `(url, payload) -> None` |

取得処理（`HttpxFetcher`）と Jev クライアント（`TypeSafeJevClient`）は `rake()` の中で作り、最後に閉じる。
APIキーが未設定・拒否された場合は `JevAuthError` を送出して全体を止める。

### 3.2 対応する型

| 型 | 候補にするもの |
|---|---|
| `str` | `<title>`、`og:title`（ページ全体で1件のときのみ）、テキストを持つ要素（2〜200文字） |
| `int` / `float` / `Decimal` | ページ中の数値。`¥` `$` `€` `£` `円` `ドル` 等の通貨記号・単位、カンマ、全角数字に対応 |

- `X | None` または既定値のある項目は任意項目。それ以外は必須項目
- `bool`、日付、`Enum` / `Literal`、`list` などは対象外（`SchemaError`）
- `description` が質問文に使われる。なければ項目名を使う

### 3.3 戻り値

```python
class ExtractedValue(BaseModel):  # 1項目の結果
    value: Any | None  # 型変換後の値
    confidence: float | None  # Jev の確信度
    probability: float  # 選ばれた選択肢の確率
    source: str | None  # 選ばれた候補の元テキスト（出典）


class RakeItem[T](BaseModel):  # 1件分
    data: T  # 利用者のモデル
    fields: dict[str, ExtractedValue]


class RakeResult[T](BaseModel):  # 1ページ分
    url: str
    items: list[RakeItem[T]]  # 取得できた件
    request_ids: list[str]  # Jev の問い合わせ番号
    errors: list[str]  # 失敗の理由
```

### 3.4 値が取れなかったときの扱い

Jev が「該当なし」を選んだ、候補が1つもない、確信度が `min_confidence` 未満のいずれかの場合：

- **任意項目**：エラーにせず `None`（既定値）にする
- **必須項目**：その件だけを捨て、`errors` に理由を残す（例：`item 2: address: no matching value (Jev chose __none__)`）。ほかの件は残す

捨てた値の確信度と元のテキストは、`fields` に残る。
ページの取得失敗はページ全体の失敗とする。Jev API のエラーは、そのリクエストに含まれる件だけの失敗とする（例：`items 20-24: ...`）。

## 4. CLI

```
jevrake URL... --fields JSON [-o FILE] [--min-confidence FLOAT] [--delay FLOAT] [--dry-run] [--version]
```

| オプション | 既定 | 説明 |
|---|---|---|
| `-f`, `--fields` | （必須） | 取得する項目の JSON |
| `-o`, `--output` | 標準出力 | 結果の JSON を書き出すファイル |
| `--min-confidence` | `0.9` | これ未満の確信度の値は捨てる（`null` にする） |
| `--delay` | `1.0` | 同一ホストへのアクセス間隔（秒） |
| `--dry-run` | — | Jev へのリクエスト内容を表示して送信しない（APIキー不要） |
| `--version` | — | バージョンを表示 |

### 4.1 `--fields`

各項目は、説明文だけの文字列（型は `str`）か、`{"description": ..., "type": ...}` で書く。`type` は `str` / `int` / `float` / `decimal`（省略時は `str`）。

```json
{"title": "商品名", "price": {"description": "税込価格", "type": "int"}}
```

- CLI の項目はすべて任意項目。取れなかった値・確信度不足の値は `null` になる
- 項目名は英字で始まる識別子（`_` 始まり不可）。キーの重複、未知のキー、未知の型は入力エラー

### 4.2 出力

1件＝1レコードの JSON 配列。一覧ページなら、1ページから複数レコードが出る。

```json
[{"url": "...", "data": {"title": "...", "price": 3980}, "fields": {"title": {...}, "price": {...}}}]
```

失敗の理由は、出力の後に標準エラー出力へ `[error] URL: 理由` の形で表示する。

### 4.3 終了コード

| コード | 意味 |
|---|---|
| `0` | 成功 |
| `1` | 一部失敗（取得失敗のページ、捨てた件がある） |
| `2` | 入力エラー（`--fields` の誤りなど） |
| `3` | 認証エラー（APIキー未設定・拒否） |

ヘルプ・エラーメッセージはすべて英語。

## 5. 一覧ページの判定

- dom.py が、同じ親の下に同じ形（タグ名と class が同じ）の要素が3つ以上並ぶ場所を「繰り返しのグループ」として集める
- collect.py が、次の条件を満たすグループを一覧とみなす
  - 「1件らしい」ブロックが3つ以上ある。1件らしいブロックとは、要素が2つ以上あり、40文字以下の短い要素を含み、必須項目すべてに候補があるもの
  - グループのテキストが、ページ全体のテキストの半分以上を占める
- 条件を満たすグループが複数あれば、1件らしいブロックが最も多いものを採る。どれも満たさなければ、ページ全体を1件とする
- 採ったグループのブロックは、条件を満たさないものも含めてすべて1件として扱う（欠けた値は 3.4 のとおり処理する）

しきい値は collect.py の定数（`MIN_LIST_ITEMS = 3`、`MIN_LIST_TEXT_RATIO = 0.5`、`MAX_SHORT_TEXT_CHARS = 40`）。

## 6. Jev との連携

- 公式 SDK `typesafe-sdk` の同期版クライアント（`TypeSafeClient`）を使う。モデルは常に `jev-latest`
- APIキーは環境変数 `TYPESAFE_API_KEY` からのみ読む
- 質問はすべて選択式（Choice）。1ページで1回送る（一覧ページは20件ごとに分けて送る）

### 6.1 state

```json
{"url": "...", "page_title": "<title>（なければ og:title）", "main_text": "整形済みの本文（8,000文字まで）"}
```

### 6.2 質問

Jev に送る文面はすべて英語。

| 質問名 | ページ全体で1件：`price`、一覧ページの3件目：`item3.price` |
|---|---|
| 質問文（1件） | `Which option is "{description}"? Choose the option that represents the {name} of this page.` |
| 質問文（一覧） | `Which option is "{description}"? All options come from one item of a list on this page; choose the option that represents the {name} of that item.` |
| 選択肢名 | `c0`, `c1`, …（ページ上の順） |
| 選択肢の説明 | `"¥3,980" \| <span class=price> \| nearby label: 販売価格`（テキストは200文字で切る） |
| 該当なし | `__none__`：`None of these is the requested value.` |

- 一覧ページの質問文に件の番号は入れない（Jev がページ上の何件目かを数え違えるため。選択肢はその件のブロック内の候補だけ）
- 選択肢は最大255個。候補が多い場合は点数の高い254個に絞る（点数はラベルと項目名・説明の一致、class 名、見出し、出現頻度、通貨記号の有無など）
- ページのテキストは質問文に入れず、state と選択肢の説明にだけ入れる

### 6.3 エラー処理

| 状況 | 扱い |
|---|---|
| 429・5xx・タイムアウト・接続失敗 | SDK の `RetryPolicy(max_retries=3)` で指数バックオフ。最終的に失敗したら `JevError` |
| 401・403、APIキー未設定 | `JevAuthError`。全体を止める（CLI は終了コード3） |
| タイムアウト | 1回の通信につき30秒 |

## 7. 取得

- `httpx` の同期クライアント。リダイレクトに従う
- User-Agent：`jevrake/<バージョン>`（固定）
- 同じホストへのアクセスは、前回から `delay` 秒（既定1秒）空ける（`time.monotonic` で計測）
- http / https 以外の URL、4xx・5xx、HTML 以外の Content-Type はそのページの失敗
- robots.txt は確認しない。対象サイトの robots.txt や利用規約を守るのは利用者の責任

## 8. HTML の整理

- `script` / `style` / `nav` / `footer` / `noscript` / `template` / `svg` / `iframe` と、非表示の要素（`hidden` 属性、`aria-hidden="true"`、`display:none` / `visibility:hidden`）を除く
- テキストを直接持つ要素ごとに、テキスト・タグ・属性・近くのラベル・見出しレベルを集める
  - 近くのラベル：表の `<th>`、定義リストの `<dt>`、直前の短い要素（30文字以内）、`aria-label` / `itemprop`。対象は要素自身と親まで
- 本文（`main_text`）はブロック要素ごとに改行し、8,000文字で切る

## 9. 設計方針

- 公開 API は `jevrake/__init__.py` で再エクスポートし、`__all__` に明示する（`rake`、`RakeResult`、`RakeItem`、`ExtractedValue`、`__version__`）。内部実装は `_internal/` にまとめ、自由に変更してよい
- 通信を行うのは `fetch.py` と `client.py` だけ。ほかのモジュールは入力を受け取って結果を返すだけの処理にする
- データモデルはすべて Pydantic の `BaseModel` で `models.py` に、例外は `exceptions.py` にまとめる
- 関数名は「動詞＋名詞」、簡単な英語を使う。ファイル内をコメントで区切らない
- 依存は最小限（実行時：`pydantic` / `httpx` / `selectolax` / `typesafe-sdk`、開発時：`pytest` / `ruff`）

## 10. ディレクトリ構成

```
src/jevrake/
├── __init__.py        公開API
├── cli.py             jevrake コマンド
├── py.typed           型ヒント付きパッケージの印
└── _internal/
    ├── api.py         rake()：処理の流れ
    ├── fetch.py       HTML の取得とレート制限
    ├── dom.py         HTML の整理、テキスト要素と繰り返しブロックの抽出
    ├── collect.py     一覧の判定、候補集め、絞り込み
    ├── convert.py     テキストから型への変換（"¥3,980" → 3980）
    ├── jev.py         質問の組み立てと回答の解釈（通信しない）
    ├── client.py      Jev API との通信
    ├── schema.py      モデル・--fields から項目定義（ExtractionTarget）を作る
    ├── models.py      データモデル
    ├── exceptions.py  例外
    └── version.py     バージョンと User-Agent
tests/                 ネットワークなしで動くテスト（fixtures/ に保存済みHTML）
docs/spec.md           この仕様書
```

## 11. テスト

- すべてネットワークなしで実行できる。HTTP は `httpx.MockTransport`（Jev SDK は `httpx2.MockTransport`）で差し替え、Jev は決められた回答を返すフェイクに差し替える（`monkeypatch` で `api.HttpxFetcher` / `api.TypeSafeJevClient` を置き換える）
- 各テストは「準備 → 実行 → 確認」の3段を空行で区切る
- 実際の Jev API を呼ぶテスト（E2E）は対象外

## 12. 技術構成

| 用途 | 技術 |
|---|---|
| 言語 | Python 3.12 以上（型パラメータの文法 `def f[T]` を使うため） |
| 環境・パッケージ管理 / ビルド | uv / uv_build |
| Lint・フォーマット | Ruff |
| テスト | pytest |
| 環境変数 | direnv（`.envrc` は Git 管理外、`.envrc.example` を置く） |
| CI | GitHub Actions（main への push と全 PR で `ruff check` / `ruff format --check` / `pytest`） |
| ライセンス | MIT |
