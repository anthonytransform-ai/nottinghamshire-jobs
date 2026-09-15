"""Minimal HTML text extraction retained for the stable Oracle advert."""

from __future__ import annotations

import re
from html.parser import HTMLParser


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() in {"script", "style", "noscript", "template"}:
            self._ignored_depth += 1

    def handle_startendtag(self, tag: str, attrs) -> None:
        # A self-closing ignored tag has no content to suppress.
        return

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "template"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def clean_text(value: str) -> str:
    parser = _TextParser()
    parser.feed(value or "")
    return " ".join(" ".join(parser.parts).split())


def labelled_html_value(html: str, labels: tuple[str, ...] | list[str]) -> str:
    """Read a value adjacent to a simple HTML label."""

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
