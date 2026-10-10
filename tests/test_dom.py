from jevrake._internal.dom import MAX_MAIN_TEXT_CHARS, parse_page

from .conftest import load_fixture


def test_removes_non_content_and_hidden() -> None:
    html = load_fixture("ja_product.html")

    page = parse_page(html)

    joined = page.main_text + " ".join(e.text for e in page.elements)
    for removed in ("var price", "color: red", "ホーム", "隠し価格", "非表示の説明", "送料無料"):
        assert removed not in joined
    assert "¥３，９８０" in joined


def test_title_and_og_title() -> None:
    html = load_fixture("ja_product.html")

    page = parse_page(html)

    assert page.title == "ワイヤレスイヤホン X100 | サンプルショップ"
    assert page.og_title == "ワイヤレスイヤホン X100"


def test_labels_from_table_and_sibling() -> None:
    html = load_fixture("ja_product.html")

    page = parse_page(html)

    by_text = {e.text: e for e in page.elements}
    assert by_text["2026年9月30日"].label == "発売日"
    assert by_text["¥３，９８０"].label == "販売価格"


def test_definition_list_label() -> None:
    html = load_fixture("en_product.html")

    page = parse_page(html)

    by_text = {e.text: e for e in page.elements}
    assert by_text["March 5, 2026"].label == "Release date"


def test_heading_level() -> None:
    html = "<body><h1><span>Title</span></h1><h2>Sub</h2><p>x</p></body>"

    page = parse_page(html)

    levels = {e.text: e.heading_level for e in page.elements}
    assert levels == {"Title": 1, "Sub": 2, "x": None}


def test_nested_hidden_elements() -> None:
    html = '<body><div hidden><p style="display:none">a</p><p>b</p></div><p>c</p></body>'

    page = parse_page(html)

    assert [e.text for e in page.elements] == ["c"]


def test_main_text_truncated() -> None:
    html = "<body>" + "".join(f"<p>段落{i}</p>" for i in range(3000)) + "</body>"

    page = parse_page(html)

    assert len(page.main_text) == MAX_MAIN_TEXT_CHARS
    assert page.main_text.startswith("段落0\n段落1\n")


def test_empty_document() -> None:
    page = parse_page("")

    assert page.elements == []
    assert page.main_text == ""
