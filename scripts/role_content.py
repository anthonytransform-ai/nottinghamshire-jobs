"""Select source-grounded role evidence for editorial judgement, not summaries.

Full captured HTML stays in the evidence cache. These selectors remove known
source furniture and expose duties/structured facts to the Playbook judgement
step; they do not classify, include, summarise or publish a vacancy.
"""
from __future__ import annotations

import re


STOP_HEADINGS = re.compile(
    r"^(?:about (?:you|us)|join us|safe\s*&\s*inclusive|working for our organisation|"
    r"what (?:the school offers|we offer)|benefits|our commitment to inclusion|"
    r"who we.re looking for|why nottingham|commitment to safeguarding|applying for|"
    r"further details|about the school|why work|what.s in it for you|"
    r"what we.re looking for|what next)", re.I,
)


def blocks(node):
    """Keep paragraph/list/heading boundaries instead of flattening whole pages."""
    result = []

    def visit(current):
        if current.tag in {"script", "style", "noscript"}:
            return
        if "advertheader" in current.attrs.get("class", "").split():
            return
        if current.tag in {"p", "li", "h1", "h2", "h3", "h4", "h5"}:
            text = current.text()
            if text:
                result.append((current.tag, text))
            return
        for child in current.children:
            if hasattr(child, "tag"):
                visit(child)

    visit(node)
    return result


def section(items, start, stop=STOP_HEADINGS):
    selected = []
    active = False
    for tag, text in items:
        if re.match(start, text, re.I):
            active = True
            # Some portals put a heading and its prose in a single paragraph.
            remainder = re.sub(start, "", text, count=1, flags=re.I).strip(" :")
            if remainder:
                selected.append(remainder)
            continue
        if active and stop.match(text):
            break
        if active and not tag.startswith("h"):
            selected.append(text)
    return selected


def role_paragraphs(source, root):
    """Return retained role paragraphs using the provider's normal structure."""
    if source.method == "jobtrain":
        container = next((n for n in root.nodes() if n.attrs.get("id") == "Media_Rich_Advert"), root)
        items = blocks(container)
        selected = section(items, r"^About the Role\b") or section(items, r"^(?:Role overview|Key responsibilities|The Role)\b")
        if selected:
            return selected
        selected = []
        for tag, text in items:
            if STOP_HEADINGS.match(text):
                break
            if tag in {"p", "li"}:
                if not re.match(r"^(?:Salary|\(?£|Permanent|Full[- ]time|Fixed[- ]term)\b", text, re.I):
                    selected.append(text)
        return selected
    if source.method == "oracle-cloud":
        containers = root.nodes(cls="job-details__description-content")
        if not containers:
            return []
        items = blocks(containers[0])
        selected = section(items, r"^About (?:the|this|your) Role\b")
        if selected:
            return selected
        # Other adverts expose responsibilities without the usual heading.
        selected = section(items, r"^(?:Main duties|Key responsibilities|The role|Your role)\b")
        return selected or [text for tag, text in items if not tag.startswith("h")]
    if source.method == "university-vacancies":
        container = next((n for n in root.nodes() if n.attrs.get("id") == "main"), root)
        result = []
        for tag, text in blocks(container):
            # One current UoN template labels its duties 'About you'; that
            # heading alone must not discard explicit administrative work.
            if (STOP_HEADINGS.match(text) and text.casefold() != "about you") or re.match(r"(?:Informal enquiries|The University of Nottingham is an equal|Further details|Email details|Apply Online)", text, re.I):
                break
            if tag in {"p", "li"}:
                result.append(text)
        return result
    if source.method == "healthjobsuk-trac":
        container = next((n for n in root.nodes() if n.attrs.get("id") == "hj-job-advert"), root)
        items = blocks(container)
        overview = section(items, r"^Job overview\b", re.compile(r"^(?:Main duties of the job|Working for our organisation)", re.I))
        duties = section(items, r"^Main duties of the job\b", re.compile(r"^Working for our organisation", re.I))
        return overview + duties
    if source.method == "govuk-teaching-vacancies":
        container = next((n for n in root.nodes() if n.attrs.get("id") == "job-details"), root)
        items = blocks(container)
        # Include duties embedded in the skills section, while the judgement
        # step rejects qualifications/person criteria and uses structured facts
        # when no narrative work description is available.
        role = section(items, r"^(?:About the role\b|In this role,?\s*you will\b|You will:\s*$|Key responsibilities\b|The Role\b|Your mission as [^:]+:)")
        content = role or section(items, r"^(?:What skills and experience we.re looking for|.*job summary)\b")
        further = section(items, r"^Further information about the job\b")
        return content + [text for text in further if text not in content]
    return []


def structured_teaching_facts(root):
    """Capture verified role/subject/key-stage facts without inferring duties."""
    facts = {}
    for heading in root.nodes("h3"):
        key = heading.text().casefold()
        if key not in {"job role", "subject", "subjects", "key stage", "working pattern", "contract type"}:
            continue
        label = heading.parent if heading.parent.tag == "dt" else heading
        siblings = label.parent.children
        following = siblings[siblings.index(label) + 1:]
        values = []
        for sibling in following:
            if hasattr(sibling, "tag"):
                if sibling.tag in {"h2", "h3"}:
                    break
                value = sibling.text()
                if value:
                    values.append(value)
        facts[key] = re.split(r"\s+View all\b", " ".join(values))[0].strip()
    return facts
