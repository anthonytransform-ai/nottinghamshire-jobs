#!/usr/bin/env python3
"""Prepare Base64 staging chunks and a manifest for an audited jobs.csv file."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path

if __package__:
    from .validate_job_update import ValidationError, parse_csv_bytes
else:
    from validate_job_update import ValidationError, parse_csv_bytes

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


def prepare(csv_path: Path, output_dir: Path, date_checked: str, base_main_sha: str, chunk_chars: int) -> dict:
    if not _SHA1_RE.fullmatch(base_main_sha):
        raise ValidationError("base_main_sha must be a lowercase 40-character commit SHA")
    if chunk_chars < 1000 or chunk_chars % 4 != 0:
        raise ValidationError("chunk_chars must be at least 1000 and divisible by 4")

    data = csv_path.read_bytes()
    records = parse_csv_bytes(data)
    if any(record["date_checked"] != date_checked for record in records):
        raise ValidationError("every CSV date_checked must equal --date-checked")

    encoded = base64.b64encode(data).decode("ascii")
    stage_dir = output_dir / ".job-update"
    stage_dir.mkdir(parents=True, exist_ok=True)

    chunks = []
    for index, start in enumerate(range(0, len(encoded), chunk_chars), start=1):
        relative = f".job-update/chunk-{index:03d}.b64"
        (output_dir / relative).write_text(encoded[start:start + chunk_chars], encoding="ascii")
        chunks.append(relative)

    manifest = {
        "date_checked": date_checked,
        "row_count": len(records),
        "sha256": hashlib.sha256(data).hexdigest(),
        "base_main_sha": base_main_sha,
        "chunks": chunks,
    }
    (output_dir / "job-update-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--date-checked", required=True)
    parser.add_argument("--base-main-sha", required=True)
    parser.add_argument("--chunk-chars", type=int, default=12000)
    args = parser.parse_args()

    try:
        manifest = prepare(args.csv, args.output_dir, args.date_checked, args.base_main_sha, args.chunk_chars)
    except (OSError, ValidationError) as exc:
        print(f"PREPARATION FAILED: {exc}")
        return 1

    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
