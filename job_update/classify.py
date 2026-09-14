"""Deterministic, ordered policy classification."""

from __future__ import annotations

import re


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


def classify_location(location: str, description: str = "", override: str = "") -> tuple[str | None, str, list[str]]:
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
    if re.fullmatch(r"nottinghamshire(?:\s*,?\s*united kingdom)?", location_text) or location_text in {"notts", "nottinghamshire county"}:
        return "Nottinghamshire-wide", "explicit Nottinghamshire base", ["Nottinghamshire-wide"]
    if not text.strip():
        return None, "actual work base is missing", []
    if re.search(r"\b(multiple|various|all)\b.{0,30}\b(nottinghamshire|county)\b", text) or "nottinghamshire-wide" in text or "countywide" in text:
        return "Nottinghamshire-wide", "explicit countywide/multiple-county wording", ["Nottinghamshire-wide"]
    if any(term in text for term in ("derbyshire", "leicestershire", "lincolnshire", "south yorkshire", "london", "manchester", "uk other", "nationwide")):
        # A local word elsewhere in a description must not rescue a clearly
        # out-of-county required base.
        return None, "actual base is outside Nottinghamshire or not local", []
    matches: list[str] = []
    for area, patterns in _LOCATION_PATTERNS:
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


def classify_job_area(title: str, description: str = "", override: str = "") -> tuple[str | None, str, list[str]]:
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
    matches: list[str] = []
    for area, terms in _JOB_RULES:
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
        title_matches = [area for area, terms in _JOB_RULES if any(term in title_text for term in terms)]
        title_matches = list(dict.fromkeys(title_matches))
        if len(title_matches) == 1:
            return title_matches[0], "title-specific role-function rule", title_matches
        return None, "multiple job-area functions remain plausible", matches
    if "manager" in title_text or "head of" in title_text or "lead" in title_text:
        return "Management & Leadership", "explicit management wording without a more specific function", ["Management & Leadership"]
    if re.search(r"\b(officer|coordinator|assistant|advisor|adviser|worker|analyst)\b", title_text):
        return None, "generic role title needs a human area decision", []
    return "Other", "no stronger controlled role-area rule matched", ["Other"]
