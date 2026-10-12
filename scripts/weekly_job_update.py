"""Shared contracts and local state helpers for the Workflow-First job update.

This module deliberately contains no source-specific collector or final editorial
classification logic.  It gives the repo-local Skill and future collectors one
small standard-library surface for the fixed registry, source lifecycle, raw
candidate evidence, and resumable local working state.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = (
    REPOSITORY_ROOT
    / ".agents"
    / "skills"
    / "weekly-job-update"
    / "references"
    / "source-registry.json"
)
DEFAULT_WORKING_ROOT = REPOSITORY_ROOT / ".weekly-job-update"
REGISTRY_SCHEMA_VERSION = 1


class SourceRunStatus(str, Enum):
    """The only source-run lifecycle states exposed to collectors."""

    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    OK = "OK"
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    ERROR = "ERROR"


class RawCandidateStatus(str, Enum):
    """Progress state for a captured raw candidate."""

    CAPTURED = "CAPTURED"
    DETAIL_COMPLETE = "DETAIL_COMPLETE"
    EXCLUDED = "EXCLUDED"


TERMINAL_SOURCE_STATUSES = frozenset(
    {
        SourceRunStatus.OK,
        SourceRunStatus.EMPTY,
        SourceRunStatus.PARTIAL,
        SourceRunStatus.ERROR,
    }
)


def _text(value: Any, *, field_name: str, required: bool = False) -> str:
    if value is None:
        result = ""
    elif isinstance(value, str):
        result = value
    else:
        result = str(value)
    if required and not result.strip():
        raise ValueError(f"{field_name} must not be blank")
    return result


def _http_url(value: str, *, field_name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an absolute HTTP(S) URL")
    return value


@dataclass(frozen=True)
class SourceDefinition:
    """One canonical fixed source entry."""

    source_id: str
    name: str
    family: str
    method: str
    fixed_route: str
    individual_route_pattern: str | None
    fallback: str
    platform: str | None = None
    wvid: str | None = None
    notes: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceDefinition":
        source_id = _text(value.get("id"), field_name="source id", required=True)
        name = _text(value.get("name"), field_name=f"{source_id}.name", required=True)
        family = _text(value.get("family"), field_name=f"{source_id}.family", required=True)
        method = _text(value.get("method"), field_name=f"{source_id}.method", required=True)
        fixed_route = _http_url(
            _text(value.get("fixed_route"), field_name=f"{source_id}.fixed_route", required=True),
            field_name=f"{source_id}.fixed_route",
        )
        fallback = _text(value.get("fallback"), field_name=f"{source_id}.fallback", required=True)
        pattern_value = value.get("individual_route_pattern")
        individual_route_pattern = None if pattern_value is None else _text(
            pattern_value,
            field_name=f"{source_id}.individual_route_pattern",
        )
        platform_value = value.get("platform")
        platform = None if platform_value is None else _text(
            platform_value,
            field_name=f"{source_id}.platform",
        )
        wvid_value = value.get("wvid")
        wvid = None if wvid_value is None else _text(wvid_value, field_name=f"{source_id}.wvid")
        notes_value = value.get("notes", [])
        if not isinstance(notes_value, list) or not all(isinstance(note, str) for note in notes_value):
            raise ValueError(f"{source_id}.notes must be a list of strings")

        return cls(
            source_id=source_id,
            name=name,
            family=family,
            method=method,
            fixed_route=fixed_route,
            individual_route_pattern=individual_route_pattern,
            fallback=fallback,
            platform=platform,
            wvid=wvid,
            notes=tuple(notes_value),
        )

    def to_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": self.source_id,
            "name": self.name,
            "family": self.family,
            "method": self.method,
            "fixed_route": self.fixed_route,
            "individual_route_pattern": self.individual_route_pattern,
            "fallback": self.fallback,
        }
        if self.platform is not None:
            value["platform"] = self.platform
        if self.wvid is not None:
            value["wvid"] = self.wvid
        if self.notes:
            value["notes"] = list(self.notes)
        return value


@dataclass(frozen=True)
class SourceRegistry:
    """Validated view of the one machine-readable source registry."""

    registry_id: str
    schema_version: int
    sources: tuple[SourceDefinition, ...]

    @property
    def source_count(self) -> int:
        return len(self.sources)

    def get(self, source_id: str) -> SourceDefinition:
        for source in self.sources:
            if source.source_id == source_id:
                return source
        raise KeyError(f"Unknown source id: {source_id}")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "registry_id": self.registry_id,
            "schema_version": self.schema_version,
            "source_count": self.source_count,
            "sources": [source.to_mapping() for source in self.sources],
        }


def load_registry(path: Path | str = REGISTRY_PATH) -> SourceRegistry:
    """Load and validate the canonical registry using only the standard library."""

    registry_path = Path(path)
    with registry_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError("Source registry must contain a JSON object")
    schema_version = payload.get("schema_version")
    if schema_version != REGISTRY_SCHEMA_VERSION:
        raise ValueError(f"Unsupported source registry schema: {schema_version!r}")
    registry_id = _text(payload.get("registry_id"), field_name="registry_id", required=True)
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list):
        raise ValueError("Source registry sources must be a JSON array")
    expected_count = payload.get("source_count")
    if expected_count != len(raw_sources):
        raise ValueError("Source registry source_count does not match the sources array")

    sources = tuple(SourceDefinition.from_mapping(item) for item in raw_sources)
    source_ids = [source.source_id for source in sources]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Source registry source IDs must be unique")
    return SourceRegistry(
        registry_id=registry_id,
        schema_version=schema_version,
        sources=sources,
    )


@dataclass
class SourceRun:
    """A resumable source-run record with explicit terminal semantics."""

    source_id: str
    status: SourceRunStatus = SourceRunStatus.NOT_STARTED
    started_at: str | None = None
    finished_at: str | None = None
    candidate_count: int = 0
    normal_collection_completed: bool = False
    limitation: str = ""
    error: str = ""

    def begin(self, started_at: str) -> None:
        if self.status is not SourceRunStatus.NOT_STARTED:
            raise ValueError(f"Source {self.source_id} cannot begin from {self.status.value}")
        self.started_at = _text(started_at, field_name="started_at", required=True)
        self.status = SourceRunStatus.RUNNING

    def complete(
        self,
        outcome: SourceRunStatus,
        *,
        candidate_count: int,
        finished_at: str,
        normal_collection_completed: bool,
        limitation: str = "",
        error: str = "",
    ) -> None:
        if self.status is not SourceRunStatus.RUNNING:
            raise ValueError(f"Source {self.source_id} cannot complete from {self.status.value}")
        if outcome not in TERMINAL_SOURCE_STATUSES:
            raise ValueError(f"Source outcome must be terminal, got {outcome!r}")
        if candidate_count < 0:
            raise ValueError("candidate_count must not be negative")
        if outcome is SourceRunStatus.EMPTY:
            if not normal_collection_completed or candidate_count != 0:
                raise ValueError("EMPTY requires a completed normal collection with zero candidates")
            if limitation.strip() or error.strip():
                raise ValueError("EMPTY cannot carry a limitation or error")
        elif outcome is SourceRunStatus.OK:
            if not normal_collection_completed or candidate_count == 0:
                raise ValueError("OK requires a completed normal collection with at least one candidate")
            if error.strip():
                raise ValueError("OK cannot carry an error")
        elif outcome is SourceRunStatus.PARTIAL:
            if not limitation.strip():
                raise ValueError("PARTIAL requires a nonblank limitation")
        elif outcome is SourceRunStatus.ERROR:
            if not error.strip():
                raise ValueError("ERROR requires a nonblank error")

        self.status = outcome
        self.finished_at = _text(finished_at, field_name="finished_at", required=True)
        self.candidate_count = candidate_count
        self.normal_collection_completed = normal_collection_completed
        self.limitation = limitation
        self.error = error

    def to_mapping(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceRun":
        status_value = value.get("status", SourceRunStatus.NOT_STARTED.value)
        try:
            status = SourceRunStatus(status_value)
        except ValueError as exc:
            raise ValueError(f"Unknown source run status: {status_value!r}") from exc
        candidate_count = int(value.get("candidate_count", 0))
        if candidate_count < 0:
            raise ValueError("candidate_count must not be negative")
        return cls(
            source_id=_text(value.get("source_id"), field_name="source_id", required=True),
            status=status,
            started_at=value.get("started_at"),
            finished_at=value.get("finished_at"),
            candidate_count=candidate_count,
            normal_collection_completed=bool(value.get("normal_collection_completed", False)),
            limitation=_text(value.get("limitation"), field_name="limitation"),
            error=_text(value.get("error"), field_name="error"),
        )


@dataclass(frozen=True)
class RawCandidate:
    """Source-neutral evidence captured before final classification."""

    source_id: str
    source_family: str
    raw_organization: str = ""
    raw_title: str = ""
    raw_location: str = ""
    raw_deadline: str = ""
    raw_salary: str = ""
    raw_contract: str = ""
    raw_work_pattern: str = ""
    source_reference: str = ""
    source_platform_id: str = ""
    list_url: str = ""
    source_url: str = ""
    detail_url: str = ""
    apply_url: str = ""
    detail_body: str = ""
    collected_at: str = ""
    collection_method: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)
    status: RawCandidateStatus = RawCandidateStatus.CAPTURED

    def __post_init__(self) -> None:
        for field_name in ("source_id", "source_family", "collected_at", "collection_method"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")
        if not (self.list_url.strip() or self.source_url.strip()):
            raise ValueError("RawCandidate requires list_url or source_url")
        if not isinstance(self.provenance, Mapping):
            raise ValueError("provenance must be a mapping")
        if isinstance(self.status, str):
            try:
                object.__setattr__(self, "status", RawCandidateStatus(self.status))
            except ValueError as exc:
                raise ValueError(f"Unknown raw candidate status: {self.status!r}") from exc

    def to_mapping(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        value["provenance"] = dict(self.provenance)
        return value

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RawCandidate":
        status_value = value.get("status", RawCandidateStatus.CAPTURED.value)
        try:
            status = RawCandidateStatus(status_value)
        except ValueError as exc:
            raise ValueError(f"Unknown raw candidate status: {status_value!r}") from exc
        provenance = value.get("provenance", {})
        if not isinstance(provenance, Mapping):
            raise ValueError("provenance must be a mapping")

        fields = {
            "source_id": _text(value.get("source_id"), field_name="source_id", required=True),
            "source_family": _text(value.get("source_family"), field_name="source_family", required=True),
            "raw_organization": _text(value.get("raw_organization"), field_name="raw_organization"),
            "raw_title": _text(value.get("raw_title"), field_name="raw_title"),
            "raw_location": _text(value.get("raw_location"), field_name="raw_location"),
            "raw_deadline": _text(value.get("raw_deadline"), field_name="raw_deadline"),
            "raw_salary": _text(value.get("raw_salary"), field_name="raw_salary"),
            "raw_contract": _text(value.get("raw_contract"), field_name="raw_contract"),
            "raw_work_pattern": _text(value.get("raw_work_pattern"), field_name="raw_work_pattern"),
            "source_reference": _text(value.get("source_reference"), field_name="source_reference"),
            "source_platform_id": _text(value.get("source_platform_id"), field_name="source_platform_id"),
            "list_url": _text(value.get("list_url"), field_name="list_url"),
            "source_url": _text(value.get("source_url"), field_name="source_url"),
            "detail_url": _text(value.get("detail_url"), field_name="detail_url"),
            "apply_url": _text(value.get("apply_url"), field_name="apply_url"),
            "detail_body": _text(value.get("detail_body"), field_name="detail_body"),
            "collected_at": _text(value.get("collected_at"), field_name="collected_at", required=True),
            "collection_method": _text(
                value.get("collection_method"),
                field_name="collection_method",
                required=True,
            ),
            "provenance": dict(provenance),
            "status": status,
        }
        return cls(**fields)


@dataclass(frozen=True)
class WorkingStatePaths:
    """The ignored local files used to resume a source-by-source run."""

    root: Path = DEFAULT_WORKING_ROOT

    @property
    def source_runs(self) -> Path:
        return self.root / "source-runs.json"

    @property
    def raw_candidates(self) -> Path:
        return self.root / "raw-candidates.jsonl"

    @property
    def draft_candidates(self) -> Path:
        return self.root / "draft-candidates.json"

    @property
    def final_candidates(self) -> Path:
        return self.root / "final-candidates.json"


class WorkingStateStore:
    """Persist resumable local state without introducing a database or service."""

    def __init__(self, root: Path | str = DEFAULT_WORKING_ROOT) -> None:
        self.paths = WorkingStatePaths(Path(root))

    def ensure(self) -> None:
        self.paths.root.mkdir(parents=True, exist_ok=True)

    def save_source_runs(self, runs: Iterable[SourceRun]) -> None:
        payload = {"schema_version": 1, "sources": [run.to_mapping() for run in runs]}
        self._write_json(self.paths.source_runs, payload)

    def load_source_runs(self) -> list[SourceRun]:
        payload = self._read_json(self.paths.source_runs, default={"sources": []})
        raw_sources = payload.get("sources", [])
        if not isinstance(raw_sources, list):
            raise ValueError("source-runs.json sources must be a JSON array")
        return [SourceRun.from_mapping(value) for value in raw_sources]

    def append_raw_candidate(self, candidate: RawCandidate) -> None:
        self.ensure()
        with self.paths.raw_candidates.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(candidate.to_mapping(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def load_raw_candidates(self) -> list[RawCandidate]:
        if not self.paths.raw_candidates.exists():
            return []
        candidates: list[RawCandidate] = []
        with self.paths.raw_candidates.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                    candidates.append(RawCandidate.from_mapping(value))
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid raw candidate at line {line_number}") from exc
        return candidates

    def save_draft_candidates(self, candidates: Sequence[Mapping[str, Any]]) -> None:
        self._write_json(self.paths.draft_candidates, list(candidates))

    def save_final_candidates(self, candidates: Sequence[Mapping[str, Any]]) -> None:
        self._write_json(self.paths.final_candidates, list(candidates))

    def load_candidate_state(self, state: str) -> list[dict[str, Any]]:
        if state not in {"draft", "final"}:
            raise ValueError("state must be 'draft' or 'final'")
        path = self.paths.draft_candidates if state == "draft" else self.paths.final_candidates
        payload = self._read_json(path, default=[])
        if not isinstance(payload, list) or not all(isinstance(value, dict) for value in payload):
            raise ValueError(f"{path.name} must contain a JSON array of objects")
        return payload

    @staticmethod
    def _read_json(path: Path, *, default: Any) -> Any:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write_json(self, path: Path, payload: Any) -> None:
        self.ensure()
        temporary = path.with_name(f".{path.name}.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(path)


__all__ = [
    "DEFAULT_WORKING_ROOT",
    "RawCandidate",
    "RawCandidateStatus",
    "REGISTRY_PATH",
    "SourceDefinition",
    "SourceRegistry",
    "SourceRun",
    "SourceRunStatus",
    "WorkingStatePaths",
    "WorkingStateStore",
    "load_registry",
]
