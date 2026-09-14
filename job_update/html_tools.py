"""Small HTML helpers with an optional BeautifulSoup enhancement."""

from __future__ import annotations

import html as html_module
import re
from html.parser import HTMLParser
from urllib.parse import urljoin


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def clean_text(value: str) -> str:
    parser = _TextParser()
    parser.feed(value or "")
    return " ".join(" ".join(parser.parts).split())


def text_content(value: str) -> str:
    return clean_text(value)


def absolute_url(base_url: str, href: str) -> str:
    return urljoin(base_url, html_module.unescape(href.strip()))


def attribute_matches(tag_attrs: str, name: str, value: str | None = None) -> bool:
    pattern = rf"\b{re.escape(name)}\s*=\s*([\"'])(.*?)\1"
    match = re.search(pattern, tag_attrs, re.I | re.S)
    if not match:
        return False
    return value is None or match.group(2) == value


def extract_tag_blocks(html: str, tag: str = "div") -> list[tuple[str, str]]:
    """Return opening attributes and inner HTML for shallow fixture-friendly tags."""

    pattern = re.compile(
        rf"<(?P<tag>{re.escape(tag)})\b(?P<attrs>[^>]*)>(?P<body>.*?)</{re.escape(tag)}>",
        re.I | re.S,
    )
    return [(match.group("attrs"), match.group("body")) for match in pattern.finditer(html)]


def first_attr(attrs: str, names: tuple[str, ...]) -> str:
    for name in names:
        match = re.search(rf"\b{re.escape(name)}\s*=\s*([\"'])(.*?)\1", attrs, re.I | re.S)
        if match:
            return html_module.unescape(match.group(2)).strip()
    return ""


def extract_links(body: str, base_url: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for match in re.finditer(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>", body, re.I | re.S):
        href = first_attr(match.group("attrs"), ("href",))
        if href:
            links.append((clean_text(match.group("body")), absolute_url(base_url, href)))
    return links


def element_text_by_id(html: str, element_id: str) -> str:
    """Return the text inside the first element carrying ``element_id``."""

    match = re.search(
        rf"<(?P<tag>[A-Za-z][\w:-]*)\b(?P<attrs>[^>]*\bid\s*=\s*['\"]{re.escape(element_id)}['\"][^>]*)>"
        rf"(?P<body>.*?)</(?P=tag)>",
        html or "",
        re.I | re.S,
    )
    return clean_text(match.group("body")) if match else ""


def labelled_html_value(html: str, labels: tuple[str, ...] | list[str]) -> str:
    """Extract values from label/``br`` or label/element pairs in source HTML.

    ``clean_text`` intentionally collapses layout whitespace.  This helper is
    for pages whose fields are represented by adjacent HTML nodes, where a
    plain-text regex would otherwise consume the next field as well.
    """

    label_pattern = "|".join(re.escape(label) for label in labels)
    patterns = (
        rf"<(?:b|strong|dt|th)\b[^>]*>\s*(?:{label_pattern})\s*</(?:b|strong|dt|th)>\s*(?:<br\s*/?>\s*)?(?P<value><[^>]+>.*?</[^>]+>|[^<]+)",
        rf"<(?:p|div|li)\b[^>]*>\s*(?:{label_pattern})\s*[:\-]?\s*(?:<br\s*/?>\s*)?(?P<value>.*?)</(?:p|div|li)>",
    )
    for pattern in patterns:
        match = re.search(pattern, html or "", re.I | re.S)
        if match:
            value = clean_text(match.group("value"))
            if value:
                return value
    return ""


def hidden_form_fields(html: str) -> dict[str, str]:
    """Return hidden form values for public form/postback routes."""

    fields: dict[str, str] = {}
    for match in re.finditer(r"<input\b(?P<attrs>[^>]*)>", html or "", re.I | re.S):
        attrs = match.group("attrs")
        input_type = first_attr(attrs, ("type",)).casefold()
        if input_type and input_type != "hidden":
            continue
        name = first_attr(attrs, ("name", "id"))
        if name:
            fields[name] = first_attr(attrs, ("value",))
    return fields


def first_match(patterns: list[str], value: str, flags: int = re.I | re.S) -> str:
    for pattern in patterns:
        match = re.search(pattern, value, flags)
        if match:
            return clean_text(match.group(1)) if match.lastindex else clean_text(match.group(0))
    return ""
