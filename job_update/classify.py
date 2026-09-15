"""Deterministic, ordered policy classification."""

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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES_PATH = PROJECT_ROOT / "config" / "classification_rules.toml"

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


_LOCATION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Nottingham", ("nottingham city", "nottingham", "city campus", "university park", "jubilee campus", "queen's medical centre", "qmc", "clifton campus", "king's meadow")),
    ("Broxtowe", ("beeston", "stapleford", "kimberley", "eastwood", "chilwell", "nuthall", "giltbrook", "awsworth", "broxtowe")),
    ("Ashfield", ("sutton-in-ashfield", "sutton in ashfield", "kirkby-in-ashfield", "kirkby in ashfield", "hucknall", "ashfield")),
    ("Bassetlaw", ("worksop", "retford", "harworth", "bawtry", "bassetlaw")),
    ("Gedling", ("arnold", "carlton", "netherfield", "gedling")),
    ("Mansfield", ("mansfield", "forest town", "warsop")),
    ("Newark & Sherwood", ("newark", "southwell", "ollerton", "bilsthorpe", "sherwood forest", "brackenhurst", "newark and sherwood", "newark & sherwood")),
    ("Rushcliffe", ("west bridgford", "ruddington", "bingham", "cotgrave", "keyworth", "radcliffe-on-trent", "rushcliffe")),
)


@dataclass(frozen=True)
class ClassificationRules:
    location_patterns: tuple[tuple[str, tuple[str, ...]], ...]
    job_rules: tuple[tuple[str, tuple[str, ...]], ...]
    countywide_terms: tuple[str, ...] = ("nottinghamshire", "countywide", "various locations across the county", "multiple nottinghamshire")


def load_classification_rules(path: Path | str = DEFAULT_RULES_PATH) -> ClassificationRules:
    """Load ordered classification inputs from the tracked TOML policy file."""

    rules_path = Path(path)
    try:
        with rules_path.open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        return ClassificationRules(_LOCATION_PATTERNS, _JOB_RULES)
    location_data = data.get("location", {})
    labels = {
        "nottingham": "Nottingham",
        "broxtowe": "Broxtowe",
        "ashfield": "Ashfield",
        "bassetlaw": "Bassetlaw",
        "gedling": "Gedling",
        "mansfield": "Mansfield",
        "newark_sherwood": "Newark & Sherwood",
        "rushcliffe": "Rushcliffe",
    }
    loaded_locations: list[tuple[str, tuple[str, ...]]] = []
    for key, label in labels.items():
        values = location_data.get(key, [])
        if isinstance(values, list) and values:
            loaded_locations.append((label, tuple(str(value).casefold() for value in values)))
    if not loaded_locations:
        loaded_locations = list(_LOCATION_PATTERNS)
    countywide = location_data.get("countywide", ["nottinghamshire", "countywide"])
    countywide_terms = tuple(str(value).casefold() for value in countywide) if isinstance(countywide, list) else ClassificationRules(_LOCATION_PATTERNS, _JOB_RULES).countywide_terms
    job_data = data.get("job_area", {})
    loaded_jobs: list[tuple[str, tuple[str, ...]]] = []
    if isinstance(job_data, dict):
        for area in JOB_AREAS:
            key = area.casefold().replace(" & ", "_").replace(" ", "_").replace(",", "")
            values = job_data.get(key, [])
            if isinstance(values, list) and values:
                loaded_jobs.append((area, tuple(str(value).casefold() for value in values)))
    return ClassificationRules(tuple(loaded_locations), tuple(loaded_jobs or _JOB_RULES), countywide_terms)


def classify_location(
    location: str,
    description: str = "",
    override: str = "",
    *,
    rules: ClassificationRules | None = None,
) -> tuple[str | None, str, list[str]]:
    """Return ``(area, reason, candidates)`` without guessing ambiguous bases."""

    if override:
        return override, "reviewed override", [override]
    location_text = " ".join((location or "").split()).casefold()
    generic_location = not location_text or any(
        marker in location_text for marker in ("hybrid", "remote", "home-based", "uk other", "nottinghamshire", "notts")
    )
    # A long advert often mentions Nottinghamshire in service-delivery prose
    # while the actual base is elsewhere. Prefer the source location field and
    # consult description text only when the field is missing or explicitly
    # generic/ambiguous.
    text = " ".join(value for value in ((location if not generic_location else ""), description) if value).casefold()
    if location_text and not generic_location:
        text = location_text
    active_rules = rules or load_classification_rules()
    if re.fullmatch(r"nottinghamshire(?:\s*,?\s*united kingdom)?", location_text) or location_text in {"notts", "nottinghamshire county"}:
        return "Nottinghamshire-wide", "explicit Nottinghamshire base", ["Nottinghamshire-wide"]
    if not text.strip():
        return None, "actual work base is missing", []
    if re.search(r"\b(multiple|various|all)\b.{0,30}\b(nottinghamshire|county)\b", text) or any(term in text for term in active_rules.countywide_terms):
        return "Nottinghamshire-wide", "explicit countywide/multiple-county wording", ["Nottinghamshire-wide"]
    if any(term in text for term in ("derbyshire", "leicestershire", "lincolnshire", "south yorkshire", "london", "manchester", "uk other", "nationwide")):
        # A local word elsewhere in a description must not rescue a clearly
        # out-of-county required base.
        return None, "actual base is outside Nottinghamshire or not local", []
    matches: list[str] = []
    for area, patterns in active_rules.location_patterns:
        if any(
            re.search(rf"\b{re.escape(pattern)}\b", text) if pattern in {"nottingham", "nottingham city"} else pattern in text
            for pattern in patterns
        ):
            matches.append(area)
    matches = list(dict.fromkeys(matches))
    if len(matches) == 1:
        return matches[0], "matched explicit place/campus", matches
    if len(matches) > 1:
        return "Multiple Nottinghamshire locations", "multiple Nottinghamshire bases found", matches
    if "hybrid" in text or "remote" in text or "home-based" in text:
        return None, "hybrid/remote wording has no verified Nottinghamshire base", []
    return None, "location does not map deterministically to an allowed area", []


_JOB_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Planning, Environment & Regulatory", ("environmental health", "trading standards", "planning officer", "planning enforcement", "licensing officer", "regulatory", "environment officer")),
    ("Property, Facilities & Operations", ("cleaner", "cleaning", "caretaker", "estates", "facilities", "property", "grounds", "maintenance", "operations", "domestic assistant")),
    ("Finance & Procurement", ("finance", "accountant", "accounting", "accounts", "payroll", "procurement", "purchasing", "audit")),
    ("IT & Digital", ("information technology", "it support", "software", "developer", "digital", "data analyst", "cyber", "systems administrator", "technology")),
    ("HR & People", ("human resources", " hr ", "people partner", "recruitment", "resourcing", "employee relations")),
    ("Housing & Homelessness", ("housing", "homeless", "tenancy", "rent officer", "housing officer")),
    ("Legal & Governance", ("solicitor", "lawyer", "legal", "governance", "democratic services", "committee officer")),
    ("Transport & Driving", ("driver", "driving", "transport", "fleet", "logistics", "hgv", "bus escort")),
    ("Leisure, Sport & Culture", ("leisure", "sport", "sports", "library", "librarian", "museum", "arts", "culture")),
    ("Customer Service", ("customer service", "customer adviser", "contact centre", "receptionist", "front of house", "call handler")),
    ("Children & Young People", ("children", "young people", "youth", "family support", "early years", "nursery", "safeguarding")),
    ("Care & Support", ("care worker", "care assistant", "support worker", "social care", "social worker", "carer", "reablement")),
    ("Health & Clinical", ("nurse", "nursing", "clinical", "doctor", "medical", "midwife", "therapist", "healthcare", "health care", "radiographer", "pharmacy")),
    ("Education & Training", ("teacher", "teaching", "lecturer", "tutor", "trainer", "learning support", "classroom assistant", "teaching assistant", "education")),
    ("Community & Outreach", ("community", "outreach", "engagement", "voluntary sector", "community development")),
    ("Administration & Business Support", ("administrator", "administration", "business support", "office", "clerical", "secretary", "coordinator")),
)

# Title-only signals are deliberately specific.  They prevent long NHS and
# education descriptions (which mention many service functions) from turning a
# plainly titled clinical, finance, property or teaching role into a review
# item.  Broad words such as "officer" and "coordinator" are not included.
_TITLE_PRIORITY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Planning, Environment & Regulatory", ("environmental health", "trading standards", "planning officer", "licensing officer")),
    ("Health & Clinical", ("nurse", "clinical", "doctor", "medical", "midwife", "therapist", "healthcare", "psychiatr", "radiograph", "pharmacy", "orthopt", "matron", "consultant", "ward ", "medicine", "surgery")),
    ("IT & Digital", ("developer", "software", "cyber", "information technology", "it support", "data engineer", "systems administrator")),
    ("Finance & Procurement", ("accountant", "accounting", "finance", "payroll", "procurement", "purchasing", "treasury")),
    ("Property, Facilities & Operations", ("estates", "facilities", "property", "caretaker", "cleaner", "maintenance", "grounds", "operations")),
    ("Customer Service", ("customer service", "customer adviser", "receptionist", "contact centre", "call handler")),
    ("Children & Young People", ("early years", "nursery", "youth worker", "children's", "childrens", "young people")),
    ("Care & Support", ("care worker", "care assistant", "support worker", "social worker", "reablement", "carer")),
    ("Education & Training", ("teacher", "teaching", "lecturer", "tutor", "trainer", "learning support", "classroom assistant")),
    ("Community & Outreach", ("community", "outreach", "engagement", "volunteer coordinator", "voluntary sector")),
    ("Legal & Governance", ("solicitor", "lawyer", "governance", "democratic services", "committee officer")),
    ("Transport & Driving", ("driver", "hgv", "bus escort", "fleet", "logistics", "transport")),
    ("Leisure, Sport & Culture", ("librarian", "library", "museum", "leisure", "sports", "culture")),
    ("HR & People", ("human resources", "people partner", "employee relations", "recruitment adviser")),
)


def classify_job_area(
    title: str,
    description: str = "",
    override: str = "",
    *,
    rules: ClassificationRules | None = None,
) -> tuple[str | None, str, list[str]]:
    """Classify by role function, with specific rules before broad terms."""

    if override:
        return override, "reviewed override", [override]
    title_text = f" {title.casefold()} "
    body_text = f"{title_text} {description.casefold()}"
    # Keep the environmental-health guard explicit: generic health must not win.
    if "environmental health" in body_text:
        return "Planning, Environment & Regulatory", "specific environmental-health rule", ["Planning, Environment & Regulatory"]
    if "teaching assistant" in title_text or "classroom assistant" in title_text:
        if any(word in body_text for word in ("children", "young people", "safeguard", "special educational needs", "send")):
            return "Children & Young People", "teaching support with child-focused evidence", ["Children & Young People"]
        return "Education & Training", "teaching-support role", ["Education & Training"]
    for area, terms in _TITLE_PRIORITY:
        if any(term in title_text for term in terms):
            return area, "specific title role-function rule", [area]
    matches: list[str] = []
    active_rules = rules or load_classification_rules()
    for area, terms in active_rules.job_rules:
        if any(term in body_text for term in terms):
            matches.append(area)
    matches = list(dict.fromkeys(matches))
    # Generic service management is only management when no functional rule
    # (care, housing, finance, etc.) already identifies the service.
    if len(matches) == 1:
        return matches[0], "ordered role-function rule", matches
    if len(matches) > 1:
        # A title-specific rule outranks descriptive text. Ties in the title
        # are intentionally sent to review rather than silently guessed.
        title_matches = [area for area, terms in active_rules.job_rules if any(term in title_text for term in terms)]
        title_matches = list(dict.fromkeys(title_matches))
        if len(title_matches) == 1:
            return title_matches[0], "title-specific role-function rule", title_matches
        return None, "multiple job-area functions remain plausible", matches
    if "manager" in title_text or "head of" in title_text or "lead" in title_text:
        return "Management & Leadership", "explicit management wording without a more specific function", ["Management & Leadership"]
    return "Other", "no stronger controlled role-area rule matched", ["Other"]
