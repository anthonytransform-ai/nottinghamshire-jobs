"""TOML-driven source registry and adapter factory."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Callable

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

    def adapters(self) -> list[object]:
        from .adapters.academy_trust import AcademyTrustAdapter
        from .adapters.direct_council import DirectCouncilAdapter
        from .adapters.gedling import GedlingAdapter
        from .adapters.itrent import ITrentAdapter
        from .adapters.nhs import NHSAdapter
        from .adapters.nottingham_cvs import NottinghamCVSAdapter
        from .adapters.ntu_jobtrain import NTUJobtrainAdapter
        from .adapters.oracle_hcm import OracleHCMAdapter
        from .adapters.tal import TALAdapter
        from .adapters.teaching_vacancies import TeachingVacanciesAdapter
        from .adapters.university_nottingham import UniversityNottinghamAdapter

        factories: dict[str, Callable[[SourceSpec], object]] = {
            "academy_trust": AcademyTrustAdapter,
            "direct_council": DirectCouncilAdapter,
            "gedling": GedlingAdapter,
            "itrent": ITrentAdapter,
            "nhs": NHSAdapter,
            "nottingham_cvs": NottinghamCVSAdapter,
            "ntu_jobtrain": NTUJobtrainAdapter,
            "oracle_hcm": OracleHCMAdapter,
            "tal": TALAdapter,
            "teaching_vacancies": TeachingVacanciesAdapter,
            "university_nottingham": UniversityNottinghamAdapter,
        }
        result: list[object] = []
        for source in self.sources:
            try:
                factory = factories[source.adapter]
            except KeyError as exc:
                raise ValueError(f"no adapter registered for {source.adapter!r}") from exc
            result.append(factory(source))
        return result
