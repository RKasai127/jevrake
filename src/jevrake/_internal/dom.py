"""Turn raw HTML into a ``ParsedPage``.

Removes scripts, navigation, footers and hidden elements, then collects the page title, the main
text, and each element that holds text together with its nearby label. It also finds blocks that
repeat (such as the items of a list page).
"""

from __future__ import annotations

import re
from typing import TypeGuard

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from .models import ParsedPage, TextElement

MAX_MAIN_TEXT_CHARS = 8000

REMOVED_TAGS = ("script", "style", "nav", "footer", "noscript", "template", "svg", "iframe")
_HIDDEN_STYLE_RE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.IGNORECASE)
_BLOCK_TAGS = {
    "p", "div", "li", "tr", "td", "th", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "main", "header", "aside", "table", "ul", "ol", "dl", "br",
    "blockquote", "pre", "figure", "figcaption", "form", "label",
}  # fmt: skip
MAX_LABEL_CHARS = 30
MIN_REPEATED_BLOCKS = 3


def _get_tag(node: Node) -> str:
    return node.tag or ""


def _is_element(node: Node | None) -> TypeGuard[Node]:
    return node is not None and not _get_tag(node).startswith(("-", "_"))


def _is_hidden(node: Node) -> bool:
    attrs = node.attributes
    if "hidden" in attrs or attrs.get("aria-hidden") == "true":
        return True
    return bool(_HIDDEN_STYLE_RE.search(attrs.get("style") or ""))


def clean_html(html: str) -> HTMLParser:
    """Parse ``html`` and remove non-content elements and hidden elements."""
    tree = HTMLParser(html)
    for tag in REMOVED_TAGS:
        for node in tree.css(tag):
            node.decompose()
    if tree.body is not None:
        hidden = [n for n in tree.body.traverse() if _is_element(n) and _is_hidden(n)]
        # Nodes inside a hidden ancestor are removed together with it.
        for node in hidden:
            if not any(_is_hidden(a) for a in _get_ancestors(node)):
                node.decompose()
    return tree


def _get_ancestors(node: Node) -> list[Node]:
    result: list[Node] = []
    current = node.parent
    while _is_element(current):
        result.append(current)
        current = current.parent
    return result


def _get_own_text(node: Node) -> str:
    parts = [child.text() for child in node.iter(include_text=True) if child.tag == "-text"]
    return " ".join(" ".join(parts).split())


def _get_full_text(node: Node) -> str:
    return " ".join(node.text(deep=True, separator=" ").split())


def _find_previous_element(node: Node) -> Node | None:
    sibling = node.prev
    while sibling is not None and not _is_element(sibling):
        sibling = sibling.prev
    return sibling


def _keep_if_short(text: str) -> str | None:
    text = text.strip().rstrip(":：").strip()
    return text if 0 < len(text) <= MAX_LABEL_CHARS else None


def _find_label(node: Node) -> str | None:
    """Find a nearby label: table header, definition term, or a short preceding element.

    Looks at the node itself and its parent only; going further up tends to pick unrelated text.
    """
    current: Node | None = node
    for _ in range(2):
        if not _is_element(current):
            return None
        if current.tag in ("td", "th", "dd"):
            prev = _find_previous_element(current)
            if prev is not None and prev.tag in ("th", "td", "dt"):
                return _keep_if_short(_get_full_text(prev))
        prev = _find_previous_element(current)
        if prev is not None:
            label = _keep_if_short(_get_full_text(prev))
            if label:
                return label
        for attr in ("aria-label", "itemprop"):
            if current.attributes.get(attr):
                return _keep_if_short(current.attributes[attr] or "")
        current = current.parent
    return None


def _find_heading_level(node: Node) -> int | None:
    current: Node | None = node
    for _ in range(3):
        if not _is_element(current):
            return None
        tag = _get_tag(current)
        if re.fullmatch(r"h[1-6]", tag):
            return int(tag[1])
        current = current.parent
    return None


def _build_main_text(body: Node) -> str:
    lines: list[str] = []
    buffer: list[str] = []

    def add_line() -> None:
        line = " ".join(" ".join(buffer).split())
        if line:
            lines.append(line)
        buffer.clear()

    for node in body.traverse(include_text=True):
        if node.tag == "-text":
            buffer.append(node.text())
        elif node.tag in _BLOCK_TAGS:
            add_line()
    add_line()
    return "\n".join(lines)[:MAX_MAIN_TEXT_CHARS]


def _find_repeated_blocks(body: Node) -> list[list[Node]]:
    """Find children of the same parent that share a tag and class, at least 3 of them."""
    groups: list[list[Node]] = []
    for parent in body.traverse():
        if not _is_element(parent):
            continue
        by_shape: dict[tuple[str, str], list[Node]] = {}
        for child in parent.iter():
            if _is_element(child) and _get_full_text(child):
                shape = (_get_tag(child), child.attributes.get("class") or "")
                by_shape.setdefault(shape, []).append(child)
        groups.extend(b for b in by_shape.values() if len(b) >= MIN_REPEATED_BLOCKS)
    return groups


def parse_page(html: str) -> ParsedPage:
    raw = HTMLParser(html)
    title_node = raw.css_first("title")
    title = " ".join(title_node.text().split()) if title_node else None
    og_node = raw.css_first('meta[property="og:title"]')
    og_title = (og_node.attributes.get("content") or "").strip() or None if og_node else None

    tree = clean_html(html)
    body = tree.body
    if body is None:
        return ParsedPage(title=title or None, og_title=og_title, main_text="", elements=[])

    block_nodes = _find_repeated_blocks(body)
    block_index = {
        node.mem_id: (g, b) for g, group in enumerate(block_nodes) for b, node in enumerate(group)
    }
    repeated_groups: list[list[list[TextElement]]] = [[[] for _ in g] for g in block_nodes]

    elements: list[TextElement] = []
    for node in body.traverse():
        if not _is_element(node) or node.tag == "body":
            continue
        text = _get_own_text(node)
        if not text:
            continue
        element = TextElement(
            text=text,
            tag=_get_tag(node),
            attrs={k: v or "" for k, v in node.attributes.items()},
            label=_find_label(node),
            heading_level=_find_heading_level(node),
        )
        elements.append(element)
        for container in (node, *_get_ancestors(node)):
            if container.mem_id in block_index:
                g, b = block_index[container.mem_id]
                repeated_groups[g][b].append(element)

    return ParsedPage(
        title=title or None,
        og_title=og_title,
        main_text=_build_main_text(body),
        elements=elements,
        repeated_groups=repeated_groups,
    )
