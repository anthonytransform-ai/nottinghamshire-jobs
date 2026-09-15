"""TOML-driven source registry and explicit stable-collector registry."""

from __future__ import annotations

import tomllib
from pathlib import Path

from .models import SourceSpec


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "config" / "job_sources.toml"


class SourceRegistry:
    def __init__(self, sources: list[SourceSpec]) -> None:
        self.sources = sources
        self.by_id = {source.source_id: source for source in sources}
        if len(self.by_id) != len(sources):
            raise ValueError("source registry contains duplicate source_id values")

    @classmethod
    def load(cls, path: Path | str = DEFAULT_REGISTRY_PATH) -> "SourceRegistry":
        registry_path = Path(path)
        with registry_path.open("rb") as stream:
            data = tomllib.load(stream)
        sources = [SourceSpec(**entry) for entry in data.get("sources", [])]
        if not sources:
            raise ValueError(f"source registry is empty: {registry_path}")
        return cls(sources)

    @property
    def mandatory(self) -> list[SourceSpec]:
        return [source for source in self.sources if source.mandatory]

    def get(self, source_id: str) -> SourceSpec:
        try:
            return self.by_id[source_id]
        except KeyError as exc:
            raise KeyError(f"unknown source_id: {source_id}") from exc

    @property
    def agent_researched(self) -> list[SourceSpec]:
        return [source for source in self.sources if source.source_type == "agent-researched"]

    def collectors(self) -> list[object]:
        """Return only explicitly retained stable collectors.

        The weekly default is agent research plus structured ingestion.  A
        collector is opt-in metadata in the registry, never a requirement for
        a source to be represented or audited.
        """

        from .adapters.oracle_hcm import OracleHCMAdapter

        factories = {"oracle_hcm": OracleHCMAdapter}
        result: list[object] = []
        for source in self.sources:
            if not source.collector:
                continue
            try:
                factory = factories[source.collector]
            except KeyError as exc:
                raise ValueError(f"no stable collector registered for {source.collector!r}") from exc
            result.append(factory(source))
        return result
