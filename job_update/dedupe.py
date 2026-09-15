"""Deterministic cross-source duplicate selection.

Advert URLs identify representations, not vacancies. The public reference is
the strongest identity; otherwise the documented employer/title/location/date
fallback is used. A reference-less mirror may join a single reference-bearing
group only when its factual fallback signature agrees.
"""

from __future__ import annotations

from collections import defaultdict

from .models import NormalizedVacancy


VERIFICATION_RANK = {
    "direct-primary-advert": 4,
    "primary-platform-listing": 3,
    "official-indexed-fallback": 2,
    "credible-local-source": 1,
}


def _normalise(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _advertised_employer(record: NormalizedVacancy) -> str:
    return _normalise(record.advertised_employer or record.organization)


def _host_scope(record: NormalizedVacancy) -> str:
    if record.host_association_verified and record.host_organization and _normalise(record.host_organization) != _advertised_employer(record):
        return _normalise(record.host_organization)
    return ""


def _fallback_signature(record: NormalizedVacancy) -> tuple[str, ...]:
    return (
        _advertised_employer(record),
        _normalise(record.job_title),
        _normalise(record.location),
        record.closing_date,
        _host_scope(record),
    )


def _key(record: NormalizedVacancy) -> tuple[str, ...]:
    reference = _normalise(record.job_reference)
    if reference:
        return ("reference", _advertised_employer(record), reference)
    return ("fallback", *_fallback_signature(record))


def _winner(group: list[NormalizedVacancy]) -> NormalizedVacancy:
    return sorted(
        group,
        key=lambda item: (
            VERIFICATION_RANK.get(item.verification_method, 0),
            bool(item.job_reference),
            bool(item.apply_url),
            _normalise(item.source_id),
            _normalise(item.apply_url),
        ),
        reverse=True,
    )[0]


def deduplicate(records: list[NormalizedVacancy]) -> tuple[list[NormalizedVacancy], list[dict[str, str]]]:
    groups: dict[tuple[str, ...], list[NormalizedVacancy]] = defaultdict(list)
    reference_groups_by_fallback: dict[tuple[str, ...], set[tuple[str, ...]]] = defaultdict(set)
    no_reference: list[NormalizedVacancy] = []

    for record in records:
        if _normalise(record.job_reference):
            key = _key(record)
            groups[key].append(record)
            reference_groups_by_fallback[_fallback_signature(record)].add(key)
        else:
            no_reference.append(record)

    # A reference-less mirror can be attached to one and only one reference
    # group with the same factual signature. If two real references exist, do
    # not erase the evidence that they may be separate adverts.
    for record in no_reference:
        signature = _fallback_signature(record)
        candidates = reference_groups_by_fallback.get(signature, set())
        if len(candidates) == 1:
            groups[next(iter(candidates))].append(record)
        else:
            groups[_key(record)].append(record)

    selected: list[NormalizedVacancy] = []
    duplicates: list[dict[str, str]] = []
    for key, group in groups.items():
        winner = _winner(group)
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
