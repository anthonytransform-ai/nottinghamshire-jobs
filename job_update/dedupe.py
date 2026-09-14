"""Deterministic cross-source duplicate selection."""

from __future__ import annotations

from collections import defaultdict

from .models import NormalizedVacancy


VERIFICATION_RANK = {
    "direct-primary-advert": 4,
    "primary-platform-listing": 3,
    "official-indexed-fallback": 2,
    "credible-local-source": 1,
}


def _key(record: NormalizedVacancy) -> tuple[str, ...]:
    organization = " ".join(record.organization.casefold().split())
    reference = " ".join(record.job_reference.casefold().split())
    if reference:
        return ("reference", organization, reference)
    apply_url = record.apply_url.casefold().rstrip("/")
    if apply_url:
        return ("url", apply_url)
    return (
        "fallback",
        organization,
        " ".join(record.job_title.casefold().split()),
        " ".join(record.location.casefold().split()),
        record.closing_date,
    )


def deduplicate(records: list[NormalizedVacancy]) -> tuple[list[NormalizedVacancy], list[dict[str, str]]]:
    groups: dict[tuple[str, ...], list[NormalizedVacancy]] = defaultdict(list)
    for record in records:
        groups[_key(record)].append(record)
    selected: list[NormalizedVacancy] = []
    duplicates: list[dict[str, str]] = []
    for key, group in groups.items():
        winner = sorted(
            group,
            key=lambda item: (
                VERIFICATION_RANK.get(item.verification_method, 0),
                bool(item.job_reference),
                bool(item.apply_url),
                item.source_id,
            ),
            reverse=True,
        )[0]
        selected.append(winner)
        for duplicate in group:
            if duplicate is winner:
                continue
            duplicates.append(
                {
                    "source_id": duplicate.source_id,
                    "title": duplicate.job_title,
                    "organization": duplicate.organization,
                    "reason": "duplicate of stronger current source",
                    "winner_source_id": winner.source_id,
                    "duplicate_key": "|".join(key),
                }
            )
    return selected, duplicates
