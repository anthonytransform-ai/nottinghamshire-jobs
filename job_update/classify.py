"""Controlled semantic validation with deliberately small fallback mappings.

Weekly natural-language judgements belong to Codex. These helpers validate
agent-supplied enum values and provide conservative mappings only when a role
or place is obvious enough to be useful without pretending to understand an
entire advert.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path


JOB_AREAS = (
    "Administration & Business Support",
    "Care & Support",
    "Children & Young People",
    "Community & Outreach",
    "Customer Service",
    "Education & Training",
    "Finance & Procurement",
    "Health & Clinical",
    "HR & People",
    "Housing & Homelessness",
    "IT & Digital",
    "Legal & Governance",
    "Management & Leadership",
    "Planning, Environment & Regulatory",
    "Property, Facilities & Operations",
    "Transport & Driving",
    "Leisure, Sport & Culture",
    "Other",
)

LOCATION_AREAS = (
    "Nottingham",
    "Broxtowe",
    "Ashfield",
    "Bassetlaw",
    "Gedling",
    "Mansfield",
    "Newark & Sherwood",
    "Rushcliffe",
    "Nottinghamshire-wide",
    "Multiple Nottinghamshire locations",
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES_PATH = PROJECT_ROOT / "config" / "classification_rules.toml"

_DEFAULT_LOCATION_PATTERNS = (
    ("Nottingham", ("nottingham", "city campus", "university park", "jubilee campus", "queen's medical centre", "qmc", "clifton campus")),
    ("Broxtowe", ("beeston", "stapleford", "kimberley", "eastwood", "chilwell", "broxtowe")),
    ("Ashfield", ("sutton-in-ashfield", "sutton in ashfield", "kirkby-in-ashfield", "kirkby in ashfield", "hucknall", "ashfield")),
    ("Bassetlaw", ("worksop", "retford", "harworth", "bawtry", "bassetlaw")),
    ("Gedling", ("arnold", "carlton", "netherfield", "gedling")),
    ("Mansfield", ("mansfield", "forest town", "warsop")),
    ("Newark & Sherwood", ("newark", "southwell", "ollerton", "bilsthorpe", "sherwood forest", "brackenhurst", "newark and sherwood")),
    ("Rushcliffe", ("west bridgford", "ruddington", "bingham", "cotgrave", "keyworth", "radcliffe-on-trent", "rushcliffe")),
)

_DEFAULT_JOB_RULES = (
    ("Planning, Environment & Regulatory", ("environmental health", "trading standards", "planning officer", "licensing officer")),
    ("Property, Facilities & Operations", ("cleaner", "cleaning", "caretaker", "estates", "facilities", "property", "grounds", "maintenance")),
    ("Finance & Procurement", ("finance", "accountant", "accounting", "payroll", "procurement", "purchasing", "audit")),
    ("IT & Digital", ("information technology", "it support", "software", "developer", "digital", "data analyst", "cyber", "systems administrator")),
    ("Health & Clinical", ("nurse", "nursing", "clinical", "doctor", "medical", "midwife", "therapist", "healthcare", "radiographer", "pharmacy")),
    ("Education & Training", ("teacher", "teaching", "lecturer", "tutor", "trainer", "learning support", "classroom assistant", "teaching assistant")),
    ("Care & Support", ("care worker", "care assistant", "support worker", "social care", "social worker", "reablement")),
    ("Children & Young People", ("children", "young people", "youth", "family support", "early years", "nursery", "safeguarding")),
    ("Administration & Business Support", ("administrator", "administration", "business support", "office", "clerical", "secretary", "coordinator")),
    ("Customer Service", ("customer service", "customer adviser", "contact centre", "receptionist", "call handler")),
    ("Community & Outreach", ("community", "outreach", "engagement", "voluntary sector")),
    ("Legal & Governance", ("solicitor", "lawyer", "legal", "governance", "democratic services")),
    ("Transport & Driving", ("driver", "driving", "transport", "fleet", "logistics", "hgv")),
    ("Leisure, Sport & Culture", ("leisure", "sport", "library", "librarian", "museum", "arts", "culture")),
    ("HR & People", ("human resources", "people partner", "recruitment", "employee relations")),
)


@dataclass(frozen=True)
class ClassificationRules:
    location_patterns: tuple[tuple[str, tuple[str, ...]], ...]
    job_rules: tuple[tuple[str, tuple[str, ...]], ...]
    countywide_terms: tuple[str, ...] = ("nottinghamshire", "countywide", "multiple nottinghamshire")


def load_classification_rules(path: Path | str = DEFAULT_RULES_PATH) -> ClassificationRules:
    try:
        with Path(path).open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        return ClassificationRules(_DEFAULT_LOCATION_PATTERNS, _DEFAULT_JOB_RULES)
    location_data = data.get("location", {})
    location_keys = {
        "nottingham": "Nottingham",
        "broxtowe": "Broxtowe",
        "ashfield": "Ashfield",
        "bassetlaw": "Bassetlaw",
        "gedling": "Gedling",
        "mansfield": "Mansfield",
        "newark_sherwood": "Newark & Sherwood",
        "rushcliffe": "Rushcliffe",
    }
    locations = []
    for key, label in location_keys.items():
        values = location_data.get(key, [])
        if isinstance(values, list) and values:
            locations.append((label, tuple(str(value).casefold() for value in values)))
    jobs = []
    job_data = data.get("job_area", {})
    if isinstance(job_data, dict):
        for area in JOB_AREAS:
            key = area.casefold().replace(" & ", "_").replace(" ", "_").replace(",", "")
            values = job_data.get(key, [])
            if isinstance(values, list) and values:
                jobs.append((area, tuple(str(value).casefold() for value in values)))
    countywide = location_data.get("countywide", ["nottinghamshire", "countywide", "multiple nottinghamshire"])
    return ClassificationRules(
        tuple(locations) or _DEFAULT_LOCATION_PATTERNS,
        tuple(jobs) or _DEFAULT_JOB_RULES,
        tuple(str(value).casefold() for value in countywide) if isinstance(countywide, list) else ClassificationRules(_DEFAULT_LOCATION_PATTERNS, _DEFAULT_JOB_RULES).countywide_terms,
    )


def validate_location_area(value: str) -> bool:
    return value in LOCATION_AREAS


def validate_job_area(value: str) -> bool:
    return value in JOB_AREAS


def _contains_term(text: str, term: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text))


def classify_location(
    location: str,
    description: str = "",
    override: str = "",
    *,
    rules: ClassificationRules | None = None,
) -> tuple[str | None, str, list[str]]:
    if override:
        return (override, "reviewed controlled override", [override]) if validate_location_area(override) else (None, "invalid location-area override", [])
    location_text = " ".join((location or "").split()).casefold()
    if not location_text:
        return None, "actual work base is missing", []
    if location_text in {"nottinghamshire", "notts", "nottinghamshire county"}:
        return "Nottinghamshire-wide", "explicit Nottinghamshire base", ["Nottinghamshire-wide"]
    text = location_text if location_text not in {"hybrid", "remote", "home-based"} else ""
    if not text:
        return None, "hybrid/remote wording has no verified Nottinghamshire base", []
    if any(term in text for term in ("derbyshire", "leicestershire", "lincolnshire", "south yorkshire", "london", "manchester", "uk other", "nationwide")):
        return None, "actual base is outside Nottinghamshire or not local", []
    active = rules or load_classification_rules()
    if any(term in text for term in active.countywide_terms):
        return "Nottinghamshire-wide", "explicit countywide wording", ["Nottinghamshire-wide"]
    matches = [area for area, terms in active.location_patterns if any(_contains_term(text, term) for term in terms)]
    matches = list(dict.fromkeys(matches))
    if len(matches) == 1:
        return matches[0], "obvious place mapping", matches
    if len(matches) > 1:
        return "Multiple Nottinghamshire locations", "multiple obvious local bases", matches
    return None, "location requires agent judgement", []


def classify_job_area(
    title: str,
    description: str = "",
    override: str = "",
    *,
    rules: ClassificationRules | None = None,
) -> tuple[str | None, str, list[str]]:
    if override:
        return (override, "reviewed controlled override", [override]) if validate_job_area(override) else (None, "invalid job-area override", [])
    text = f"{title} {description}".casefold()
    active = rules or load_classification_rules()
    if "environmental health" in text:
        return "Planning, Environment & Regulatory", "obvious environmental-health mapping", ["Planning, Environment & Regulatory"]
    matches = [area for area, terms in active.job_rules if any(_contains_term(text, term) for term in terms)]
    matches = list(dict.fromkeys(matches))
    if len(matches) == 1:
        return matches[0], "obvious role-function mapping", matches
    if len(matches) > 1:
        title_matches = [area for area, terms in active.job_rules if any(_contains_term(title.casefold(), term) for term in terms)]
        title_matches = list(dict.fromkeys(title_matches))
        if len(title_matches) == 1:
            return title_matches[0], "obvious title-function mapping", title_matches
        return None, "job area requires agent judgement", matches
    return "Other", "no obvious fallback mapping", ["Other"]
