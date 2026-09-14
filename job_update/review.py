"""Structured review queue persistence."""

from __future__ import annotations

import json
from pathlib import Path

from .models import ReviewItem


def write_review_queue(items: list[ReviewItem], path: Path) -> None:
    path.write_text(
        json.dumps([item.to_dict() for item in items], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
