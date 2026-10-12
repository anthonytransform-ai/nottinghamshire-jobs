"""Evidence-only adapters. Run one registered source per invocation.

HTTP parsing uses the standard library; rendered sources lazily use Playwright.
No eligibility, classification, summary or public CSV policy lives here.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

from scripts.role_content import role_paragraphs
from scripts.weekly_job_update import (
    DEFAULT_WORKING_ROOT, RawCandidate, RawCandidateStatus, SourceRun,
    SourceRunStatus, WorkingStateStore, load_registry,
)

# Keep the original pilot tuple public for the controlled ANT-259 shadow tool.
PILOTS = ("university-of-nottingham", "nottingham-trent-university", "nottingham-university-hospitals")
ITRENT_SOURCES = (
    "ashfield-district-council",
    "mansfield-district-council",
    "bassetlaw-district-council",
    "newark-and-sherwood-district-council",
    "west-nottinghamshire-college",
    "north-notts-college-rnn-group",
)
EXPANSION_SOURCES = ("govuk-teaching-vacancies", *ITRENT_SOURCES, "nottingham-city-council")
SUPPORTED_SOURCES = (*PILOTS, *EXPANSION_SOURCES)
RENDERED_LIST_METHODS = frozenset({"jobtrain", "healthjobsuk-trac", "itrent", "oracle-cloud"})
RENDERED_DETAIL_METHODS = RENDERED_LIST_METHODS


def now():
    return datetime.now(timezone.utc).isoformat()


def clean(text):
    return " ".join(text.split())


@dataclass
class Element:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    parent: Element | None = field(default=None, repr=False)

    def nodes(self, tag=None, cls=None):
        result = []
        for child in self.children:
            if isinstance(child, Element):
                if (tag is None or child.tag == tag) and (cls is None or cls in child.attrs.get("class", "").split()):
                    result.append(child)
                result.extend(child.nodes(tag, cls))
        return result

    def text(self):
        if self.tag in {"script", "style", "noscript"}:
            return ""
        return clean(" ".join(child.text() if isinstance(child, Element) else child for child in self.children))

    def first_text(self, cls):
        matches = self.nodes(cls=cls)
        return matches[0].text() if matches else ""


class Document(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Element("document")
        self.current = self.root
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Element(tag, dict(attrs), parent=self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current
        while node.parent is not None:
            if node.tag == tag:
                self.current = node.parent
                break
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


class CollectionError(RuntimeError):
    pass


def check_document(html):
    root = Document(html).root
    text = root.text().lower()
    source = html.lower()
    if any(marker in text or marker in source for marker in ("complete the security check", "verify you are human", "access denied", "just a moment", "checking your browser", "quick check needed", "confirm you're a real person", "altcha-widget")):
        raise CollectionError("Access/security check returned instead of vacancy evidence")
    return root


def rendered_access_blocked(text):
    """Recognise a rendered portal security page before waiting for detail markup."""
    return bool(re.search(r"possible security violation|E0227SECURITY", text, re.I))


def labelled(node):
    facts = {}
    for item in ([node] if node.tag == "p" else []) + node.nodes("p"):
        labels = item.nodes("b") or item.nodes("strong")
        for label_node in labels:
            if not label_node.text():
                continue
            label = label_node.text().rstrip(" :").lower()
            value_container = label_node.parent
            facts[label] = value_container.text().partition(label_node.text())[2].lstrip(" :")
    terms = node.nodes("dt")
    for term in terms:
        siblings = term.parent.children
        position = siblings.index(term)
        following = next((s for s in siblings[position + 1:] if isinstance(s, Element)), None)
        if following and following.tag == "dd":
            facts[term.text().lower()] = following.text()
    return facts


def advert_url(href, page_url):
    url = urljoin(page_url, href)
    if urlparse(url).scheme not in {"http", "https"} or urlparse(url).netloc != urlparse(page_url).netloc:
        raise CollectionError(f"Unexpected advert destination: {url}")
    return url


def _ancestor(node, *classes):
    current = node
    while current is not None:
        tokens = set(current.attrs.get("class", "").split())
        if any(value in tokens for value in classes):
            return current
        current = current.parent
    return None


def _first_text(node, *, tag=None, cls=None):
    matches = node.nodes(tag, cls)
    return matches[0].text() if matches else ""


def _json_ld_records(root):
    records = []
    for script in root.nodes("script"):
        if script.attrs.get("type") != "application/ld+json":
            continue
        content = "".join(child for child in script.children if isinstance(child, str)).strip()
        if not content:
            continue
        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            continue
        values = value if isinstance(value, list) else value.get("@graph", [value]) if isinstance(value, dict) else []
        records.extend(item for item in values if isinstance(item, dict))
    return records


def _labelled_class_facts(node, label_class, value_class):
    facts = {}
    for wrapper in node.nodes(cls=label_class):
        label = clean(wrapper.text()).rstrip(" :").lower()
        if not label:
            continue
        parent = wrapper.parent
        if parent is None:
            continue
        values = parent.nodes(cls=value_class)
        if values:
            facts[label] = values[0].text()
    return facts


def _result_count(text, *patterns):
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))
    return None


def _source_is_rendered(source):
    return source.method in RENDERED_LIST_METHODS


def _registered_query_value(source, key):
    return _query_value(source.fixed_route, key)


def _query_value(url, key):
    expected = key.lower()
    for actual, values in parse_qs(urlparse(url).query).items():
        if actual.lower() == expected:
            return values[0] if values else ""
    return ""


def parse_list(source, html, page_url):
    root = check_document(html)
    rows = []
    if source.source_id == PILOTS[0]:
        if not root.nodes(cls="vacancylist"):
            raise CollectionError("UoN all-vacancies list marker missing")
        for section in root.nodes(cls="vacancylist"):
            # Preserve the section context for later agent exclusions; no adapter filtering.
            siblings = section.parent.children
            index = siblings.index(section)
            category = next((n.text() for n in reversed(siblings[:index]) if isinstance(n, Element) and n.tag == "h2"), "")
            for item in section.nodes("p"):
                links = [a for a in item.nodes("a") if urlparse(a.attrs.get("href", "")).path.lower().endswith("vacancy.aspx") and "ref" in parse_qs(urlparse(a.attrs.get("href", "")).query)]
                for link in links:
                    url = advert_url(link.attrs["href"], page_url)
                    facts = labelled(item)
                    rows.append(dict(url=url, title=link.text(), reference=parse_qs(urlparse(url).query)["ref"][0], platform_id="", location="", salary=facts.get("salary", ""), deadline=facts.get("closing date", ""), context=category, list_text=item.text()))
        if not rows and not re.search(r"no (?:current )?(?:jobs|vacancies)|no results", root.text(), re.I):
            raise CollectionError("UoN zero lacks explicit empty-result evidence")
    elif source.source_id == PILOTS[1]:
        totals = [n.attrs.get("value", "") for n in root.nodes("input") if n.attrs.get("id") == "totalMatchRecords"]
        if not totals or not totals[0].isdigit():
            raise CollectionError("NTU rendered result count marker missing")
        for item in root.nodes(cls="job-card"):
            links = [a for a in item.nodes("a") if "JobId" in parse_qs(urlparse(a.attrs.get("href", "")).query)]
            if not links:
                raise CollectionError("NTU card has no source-exposed JobId link")
            link = links[0]
            url = advert_url(link.attrs["href"], page_url)
            facts = labelled(item)
            rows.append(dict(url=url, title=link.text(), platform_id=parse_qs(urlparse(url).query)["JobId"][0], reference=facts.get("job reference", ""), location=facts.get("location", ""), salary=facts.get("salary / grade", ""), contract=facts.get("employment type", ""), list_text=item.text()))
    elif source.method == "govuk-teaching-vacancies":
        items = root.nodes(cls="search-results__item")
        if not items:
            if re.search(r"(?:no|0) (?:current )?(?:jobs|vacancies|results)|no jobs found", root.text(), re.I):
                return []
            raise CollectionError("GOV.UK Teaching Vacancies result list marker missing")
        for item in items:
            links = [
                a for a in item.nodes("a")
                if re.search(r"/jobs/[^/?#]+$", urlparse(a.attrs.get("href", "")).path, re.I)
            ]
            if not links:
                raise CollectionError("GOV.UK result has no source-exposed advert link")
            link = links[0]
            url = advert_url(link.attrs["href"], page_url)
            slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
            facts = labelled(item)
            address = _first_text(item, tag="p", cls="address")
            rows.append(dict(
                url=url,
                title=link.text(),
                platform_id=slug,
                reference="",
                location=address,
                salary=facts.get("full time equivalent salary", ""),
                deadline=facts.get("closing date", ""),
                list_text=item.text(),
            ))
    elif source.method == "oracle-cloud":
        links = [
            a for a in root.nodes("a", "job-list-item__link")
            if re.search(r"/job/[^/?#]+$", urlparse(a.attrs.get("href", "")).path, re.I)
        ]
        advertised_count = _result_count(root.text(), r"Job search results\s+(\d+)", r"(\d+)\s+Open Jobs")
        if advertised_count is None:
            raise CollectionError("Oracle rendered result count marker missing")
        if not links:
            if advertised_count == 0:
                return []
            raise CollectionError("Oracle rendered job links missing")
        for link in links:
            url = advert_url(link.attrs["href"], page_url)
            platform_id = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
            card = _ancestor(link, "job-list-item") or link.parent
            title = _first_text(card, tag="span", cls="job-tile__title") if card else ""
            title = title or link.text()
            if not title:
                raise CollectionError("Oracle rendered job title missing")
            values = card.nodes(cls="job-list-item__job-info-value") if card else []
            rows.append(dict(
                url=url,
                title=title,
                platform_id=platform_id,
                reference="",
                location=values[0].text() if values else "",
                list_text=(card or link).text(),
                advertised_count=advertised_count,
            ))
    elif source.method == "itrent":
        cards = root.nodes(cls="Mhr-jobDetail--listItem")
        advertised_count = _result_count(root.text(), r"(\d+)\s+jobs?\s+match", r"(\d+)\s+open jobs", r"Results\s*-\s*(\d+)\s+match(?:es)?\s+found")
        if advertised_count is None:
            raise CollectionError("iTrent rendered result count marker missing")
        if not cards:
            if advertised_count == 0:
                return []
            raise CollectionError("iTrent rendered vacancy cards missing")
        for card in cards:
            platform_id = card.attrs.get("vac-id", "").strip()
            detail_href = card.attrs.get("bu-send", "").strip()
            if not platform_id or not detail_href:
                raise CollectionError("iTrent card missing VACANCY_ID or observed detail route")
            url = advert_url(detail_href, page_url)
            registered_wvid = source.wvid or _registered_query_value(source, "WVID")
            observed_wvid = _query_value(url, "WVID")
            if not registered_wvid or observed_wvid != registered_wvid:
                raise CollectionError("iTrent detail route leaves the registered WVID")
            observed_id = _query_value(url, "VACANCY_ID")
            if not observed_id or observed_id != platform_id:
                raise CollectionError("iTrent detail route disagrees with observed VACANCY_ID")
            links = card.nodes("a", "Mhr-jobDetailTitleLink")
            title = links[0].text() if links else ""
            if not title:
                raise CollectionError("iTrent card title missing")
            facts = _labelled_class_facts(card, "Mhr-jobDetailEntry--label", "Mhr-jobDetailEntry--text")
            rows.append(dict(
                url=url,
                title=title,
                platform_id=platform_id,
                reference="",
                location=facts.get("location", ""),
                salary=facts.get("salary", ""),
                work_pattern=facts.get("basis", ""),
                list_text=card.text(),
                advertised_count=advertised_count,
            ))
    elif source.source_id == PILOTS[2]:
        lists = root.nodes(cls="hj-job-list")
        if not lists:
            raise CollectionError("HealthJobsUK employer list marker missing")
        for item in lists[0].nodes(cls="hj-job"):
            links = [a for a in item.nodes("a") if re.search(r"-v\d+", a.attrs.get("href", ""))]
            if not links:
                raise CollectionError("HealthJobsUK card has no source-exposed advert link")
            link = links[0]
            url = advert_url(link.attrs["href"], page_url)
            rows.append(dict(url=url, title=item.first_text("hj-jobtitle"), platform_id=re.search(r"-v(\d+)", url).group(1), reference="", organization=item.first_text("hj-employername"), location=item.first_text("hj-locationtown"), salary=re.sub(r"^Salary:\s*", "", item.first_text("hj-salary")), list_text=item.text()))
        if not rows and not re.search(r"no (?:current )?(?:jobs|vacancies)|no results", lists[0].text(), re.I):
            raise CollectionError("HealthJobsUK zero lacks an explicit empty-result message")
    else:
        raise CollectionError(f"No adapter is registered for source {source.source_id}")
    unique = {}
    for row in rows:
        identity = row.get("platform_id") or row["reference"]
        if not identity or not row["title"]:
            raise CollectionError("Vacancy card missing identity/title")
        if identity in unique and unique[identity] != row:
            raise CollectionError(f"Conflicting vacancy identity {identity}")
        unique[identity] = row
    return list(unique.values())


def next_page(source, html, page_url):
    root = check_document(html)
    links = [a for a in root.nodes("a") if "next" in a.attrs.get("rel", "").split() or re.fullmatch(r"next(?: page)?\s*[>»]?", a.text(), re.I)]
    targets = {advert_url(a.attrs["href"], page_url) for a in links if a.attrs.get("href")}
    if len(targets) > 1:
        raise CollectionError("Ambiguous normal Next page control")
    target = next(iter(targets), None)
    if target and source.source_id == PILOTS[2]:
        if parse_qs(urlparse(target).query).get("emp") != parse_qs(urlparse(source.fixed_route).query).get("emp"):
            raise CollectionError("Next page leaves the registered employer")
    return target


def _oracle_salary(content):
    """Read a salary field, never an open-ended match across the advert body.

    Modern Oracle adverts put salary in a paragraph (sometimes alongside
    icon-prefixed location/directorate facts). Preserve pay/allowance wording
    within that field; paragraphs and labelled non-pay facts bound its extent.
    A flat legacy fixture is usable only with an explicit following delimiter.
    """
    label = re.compile(r"\bsalary\s*:\s*", re.I)
    delimiter = re.compile(
        r"\s+(?:(?:Number of posts|Location|Contract(?: type)?|Closing Date|"
        r"Working Hours|Worker Type|Base office)\s*:|Job Identification\b|"
        r"About (?:the Role|You|Us)\b|[🏢📍🌳⏰])", re.I)
    blocks = [n for n in content.nodes()
              if n.tag in {"p", "li", "td", "dd", "h1", "h2", "h3", "h4"}]
    # Avoid using an enclosing list/table block instead of its salary child.
    for block in blocks:
        if any(label.search(n.text()) for n in block.nodes()
               if n.tag in {"p", "li", "td", "dd"}):
            continue
        match = label.search(block.text())
        if match:
            return delimiter.split(block.text()[match.end():], maxsplit=1)[0].strip()
    if not blocks:
        match = label.search(content.text())
        if match:
            value = content.text()[match.end():]
            boundary = delimiter.search(value)
            if boundary:
                return value[:boundary.start()].strip()
    return ""


def parse_detail(source, row, html):
    root = check_document(html)
    facts = labelled(root)
    body = ""
    apply_url = row.get("url", "")
    if source.source_id == PILOTS[0]:
        headers = root.nodes(cls="advertheader")
        titles = root.nodes("h1", "pagetitle")
        if not titles:
            raise CollectionError("UoN advert title missing")
        if headers:
            facts = labelled(headers[0])
        if facts.get("reference") and facts["reference"] != row["reference"]:
            raise CollectionError("UoN detail reference disagrees with observed advert link")
        # The main content contains duties and any withdrawal/expiry notices.
        containers = [n for n in root.nodes() if n.attrs.get("id") == "main"]
        body = containers[0].text() if containers else root.text()
    elif source.source_id == PILOTS[1]:
        postings = []
        for script in root.nodes("script"):
            if script.attrs.get("type") == "application/ld+json":
                try:
                    data = json.loads("".join(c for c in script.children if isinstance(c, str)))
                except json.JSONDecodeError:
                    continue
                records = data if isinstance(data, list) else data.get("@graph", [data])
                postings.extend(v for v in records if v.get("@type") == "JobPosting")
        if len(postings) != 1:
            raise CollectionError("NTU JobPosting detail evidence missing/ambiguous")
        post = postings[0]
        posted_id = parse_qs(urlparse(post.get("url", "")).query).get("JobId")
        if posted_id and posted_id != [row["platform_id"]]:
            raise CollectionError("NTU detail JobId disagrees with observed advert link")
        body = Document(post.get("description", "")).root.text()
        facts.update({"closing date": post.get("validThrough", ""), "employment type": post.get("employmentType", "")})
    elif source.method == "govuk-teaching-vacancies":
        titles = root.nodes("h1")
        if not titles:
            raise CollectionError("GOV.UK advert title missing")
        postings = [record for record in _json_ld_records(root) if record.get("@type") == "JobPosting"]
        post = postings[0] if postings else {}
        posted_url = post.get("url", "")
        if posted_url and urlparse(posted_url).path != urlparse(row["url"]).path:
            raise CollectionError("GOV.UK detail slug disagrees with observed advert link")
        content = [node.text() for node in root.nodes(cls="editor-rendered-content") if node.text()]
        json_body = Document(str(post.get("description", ""))).root.text()
        supplementary = [node.text() for node in root.nodes(cls="govuk_body") if node.text()]
        job_details = [node.text() for node in root.nodes() if node.attrs.get("id") == "job-details" and node.text()]
        body = next((value for value in (*content, json_body, *supplementary, *job_details) if value), "")
        facts.update(labelled(root))
        organization = post.get("hiringOrganization", {}).get("name", "")
        location = _first_text(root, tag="span", cls="govuk-caption-l") or row.get("location", "")
        salary = facts.get("full time equivalent salary", "")
        base_salary = post.get("baseSalary", {})
        if not salary and isinstance(base_salary, dict):
            value = base_salary.get("value", {})
            salary = value.get("value", "") if isinstance(value, dict) else str(value or "")
        employment_type = post.get("employmentType", "")
        if isinstance(employment_type, list):
            employment_type = ", ".join(str(value) for value in employment_type)
        facts.update({
            "employer": organization,
            "location": location,
            "salary": salary,
            "closing date": post.get("validThrough", "") or facts.get("closing date", ""),
            "contract type": facts.get("contract type", employment_type),
            "working pattern": facts.get("working pattern", ""),
        })
        apply_url = ""
        for link in root.nodes("a"):
            if link.attrs.get("data-link-type") == "external_advert_link" and link.attrs.get("href"):
                candidate_url = urljoin(row["url"], link.attrs["href"])
                if urlparse(candidate_url).scheme in {"http", "https"} and urlparse(candidate_url).netloc:
                    apply_url = candidate_url
                    break
    elif source.method == "oracle-cloud":
        titles = root.nodes("h1", "job-details__title")
        if not titles:
            raise CollectionError("Oracle advert title missing")
        expected_id = row.get("platform_id", "")
        identified = re.search(r"Job Identification\s+([^\s]+)", root.text(), re.I)
        if identified and expected_id and identified.group(1) != expected_id:
            raise CollectionError("Oracle detail job ID disagrees with observed advert link")
        content = root.nodes(cls="job-details__description-content")
        body = content[0].text() if content else ""
        if not body:
            raise CollectionError("Oracle advert description missing")
        contract_match = re.search(r"Contract:\s*(.*?)(?=\s+(?:Number of posts|Location|Salary|Closing Date)\s*:|\s+Job Identification\b|$)", body, re.I)
        closing_match = re.search(r"Closing Date:\s*(.*?)(?=\s+(?:Please note|Number of posts|Location|Salary|Contract)\s*:|\s+Job Identification\b|$)", body, re.I)
        facts.update({
            "location": _first_text(root, tag="div", cls="job-details__subtitle") or row.get("location", ""),
            "salary": _oracle_salary(content[0]) or row.get("salary", ""),
            "closing date": closing_match.group(1).strip() if closing_match else "",
            "contract": contract_match.group(1).strip() if contract_match else "",
        })
        apply_url = row["url"]
    elif source.method == "itrent":
        profiles = root.nodes(cls="Mhr-jobProfile")
        if not profiles:
            raise CollectionError("iTrent job profile missing")
        profile = profiles[0]
        profile_id = _query_value(row["url"], "VACANCY_ID")
        if not profile_id or not row.get("platform_id") or profile_id != row["platform_id"]:
            raise CollectionError("iTrent detail VACANCY_ID disagrees with observed card")
        registered_wvid = source.wvid or _registered_query_value(source, "WVID")
        observed_wvid = _query_value(row["url"], "WVID")
        if not registered_wvid or observed_wvid != registered_wvid:
            raise CollectionError("iTrent detail route leaves the registered WVID")
        facts.update(_labelled_class_facts(profile, "Mhr-jobProfile--dataListLabel", "Mhr-jobProfile--dataListData"))
        closing = _first_text(profile, cls="Mhr-jobProfile--closingDate")
        facts["closing date"] = re.sub(r"^Apply by\s*", "", closing, flags=re.I)
        content = profile.nodes(cls="Mhr-jobProfile--description")
        body = content[0].text() if content else ""
        apply_links = [
            link for link in profile.nodes("a")
            if "apply" in link.text().lower() and link.attrs.get("href")
        ]
        apply_url = advert_url(apply_links[0].attrs["href"], row["url"]) if apply_links else row["url"]
    elif source.source_id == PILOTS[2]:
        if not root.nodes(cls="hj-job-details"):
            raise CollectionError("HealthJobsUK job summary facts missing")
        containers = [n for n in root.nodes() if n.attrs.get("id") in {"hj-job-advert", "hj-job-description"}]
        body = " ".join(n.text() for n in containers) if containers else root.text()
        apply_url = row["url"]
    else:
        raise CollectionError(f"No adapter is registered for source {source.source_id}")
    if not body:
        raise CollectionError("Advert has no readable body evidence")
    # Metadata was read above; prefer role sections for judgement while keeping
    # the complete HTML in the evidence cache. Do not write a final summary here.
    if source.method in {"jobtrain", "university-vacancies", "oracle-cloud"}:
        paragraphs = role_paragraphs(source, root)
        if paragraphs:
            body = " ".join(paragraphs)
    location = facts.get("location", row.get("location", ""))
    if source.source_id == PILOTS[2]:
        location = ", ".join(v for v in (facts.get("site", ""), facts.get("town", "")) if v)
    return dict(
        raw_location=location,
        raw_deadline=facts.get("closing date", facts.get("closing", row.get("deadline", ""))),
        raw_salary=facts.get("salary", row.get("salary", "")),
        raw_contract=facts.get("contract", facts.get("contract type", facts.get("employment type", row.get("contract", "")))),
        raw_work_pattern=facts.get("hours", facts.get("working pattern", facts.get("basis", row.get("work_pattern", "")))),
        source_reference=facts.get("reference", facts.get("job ref", facts.get("job reference", row.get("reference", "")))),
        raw_organization=facts.get("employer") or row.get("organization") or source.name,
        detail_body=body,
        raw_apply_url=apply_url,
    )


class Transport:
    """Bounded ordinary access. Failed/challenge responses are never cached as success."""

    def __init__(self, root, source, channel=None, headed=False, timeout=25000):
        self.root = root / "evidence" / source.source_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.source = source
        self.channel, self.headed, self.timeout = channel, headed, timeout
        self.pw = self.browser = self.page = None
        self.requests = self.cache_hits = 0

    def close(self):
        if self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()

    def browser_page(self):
        if self.page is None:
            from playwright.sync_api import sync_playwright
            self.pw = sync_playwright().start()
            self.browser = self.pw.chromium.launch(channel=self.channel, headless=not self.headed, timeout=self.timeout, args=["--start-minimized"] if self.headed else [])
            self.page = self.browser.new_page()
            self.page.set_default_timeout(self.timeout)
        return self.page

    def save(self, html, url, key):
        check_document(html)
        filename = sha256(key.encode()).hexdigest() + ".html"
        path = self.root / filename
        path.write_bytes(html.encode("utf-8"))
        metadata = dict(url=url, fetched_at=now(), sha256=sha256(html.encode()).hexdigest(), file=filename)
        path.with_suffix(".json").write_text(json.dumps(metadata), encoding="utf-8")
        return metadata

    def fetch(self, url, rendered=False):
        key = ("rendered:" if rendered else "http:") + url
        path = self.root / (sha256(key.encode()).hexdigest() + ".html")
        if path.exists() and path.with_suffix(".json").exists():
            html = path.read_bytes().decode("utf-8")
            meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            if meta["sha256"] != sha256(html.encode()).hexdigest():
                raise CollectionError("Evidence cache checksum mismatch")
            check_document(html)
            self.cache_hits += 1
            return html, meta
        for attempt in range(2):
            try:
                self.requests += 1
                if rendered:
                    page = self.browser_page()
                    response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
                    if response is None or response.status >= 400:
                        raise CollectionError(f"HTTP {response.status if response else 'no response'}: {url}")
                    if self.source.method == "itrent":
                        body_text = page.locator("body").inner_text(timeout=self.timeout)
                        if rendered_access_blocked(body_text):
                            raise CollectionError(f"Access/security check blocked rendered iTrent detail: {url}")
                        page.wait_for_function("() => document.querySelector('.Mhr-jobProfile')", timeout=self.timeout)
                    elif self.source.method == "oracle-cloud":
                        page.wait_for_function("() => document.querySelector('h1.job-details__title')", timeout=self.timeout)
                    html = page.content()
                    final_url = page.url
                else:
                    with urlopen(Request(url, headers={"User-Agent": "NottinghamshireJobs-Collector/0.1"}), timeout=self.timeout / 1000) as response:
                        html = response.read().decode(response.headers.get_content_charset() or "utf-8")
                        final_url = response.url
                if urlparse(final_url).netloc != urlparse(url).netloc:
                    raise CollectionError(f"Unexpected redirect: {final_url}")
                before, after = urlparse(url), urlparse(final_url)
                for identity_key in ("ref", "JobId", "emp", "WVID", "VACANCY_ID"):
                    expected = _query_value(url, identity_key)
                    if expected and _query_value(final_url, identity_key) != expected:
                        raise CollectionError(f"Redirect lost registered/advert identity: {final_url}")
                expected_id = re.search(r"-v\d+", before.path)
                if expected_id and expected_id.group() not in after.path:
                    raise CollectionError(f"Redirect lost HealthJobsUK advert identity: {final_url}")
                return html, self.save(html, final_url, key)
            except HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt:
                    raise CollectionError(f"HTTP request failed after retry budget ({exc.code}): {url}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt:
                    raise CollectionError(f"Request failed after retry budget: {url}") from exc
            time.sleep(1 + attempt)
        raise CollectionError("Retry budget exhausted")


def enumerate_source(source, transport, checkpoint, save_checkpoint):
    if checkpoint.get("enumeration_complete"):
        return checkpoint["rows"]
    rows = {}
    checkpoint.update(rows=[], pages=[], enumeration_complete=False)

    def capture(html, url, meta):
        for row in parse_list(source, html, url):
            identity = row.get("platform_id") or row["reference"]
            if identity in rows and rows[identity]["url"] != row["url"]:
                raise CollectionError(f"Conflicting advert link for {identity}")
            row["list_evidence"] = meta
            rows[identity] = row
        checkpoint["rows"] = list(rows.values())
        checkpoint["pages"].append(meta)
        save_checkpoint()

    if source.method == "jobtrain":
        page = transport.browser_page()
        response = page.goto(source.fixed_route, wait_until="domcontentloaded", timeout=transport.timeout)
        transport.requests += 1
        if response is None or response.status >= 400:
            raise CollectionError(f"NTU list HTTP {response.status if response else 'no response'}")
        decline = page.get_by_text("Decline", exact=True)
        if decline.count() == 1 and decline.is_visible():
            decline.click()
        # Wait on exposed count + actual cards, not networkidle or static-zero markup.
        page.wait_for_function("() => {const n=document.querySelector('#totalMatchRecords'); return n && /^\\d+$/.test(n.value) && (Number(n.value)===0 || document.querySelectorAll('.job-card a[href*=JobDetail]').length>0);}", timeout=transport.timeout)
        for step in range(100):
            html = page.content()
            meta = transport.save(html, page.url, f"ntu-list:{step}")
            capture(html, page.url, meta)
            totals = page.locator("#totalMatchRecords").evaluate_all("nodes => nodes.map(n => n.value)")
            if len(set(totals)) != 1 or not totals[0].isdigit():
                raise CollectionError("NTU rendered result counts conflict")
            total = int(totals[0])
            checkpoint["advertised_count"] = total
            if len(rows) > total:
                raise CollectionError("NTU result identities exceed exposed result count")
            more = page.locator("#searchResultsLoadMoreBtn")
            if not more.is_visible():
                if len(rows) != total:
                    raise CollectionError(f"NTU stopped at {len(rows)} of {total} jobs")
                if total == 0 and not re.search(r"no (?:current )?(?:jobs|vacancies|results)(?: found)?", Document(html).root.text(), re.I):
                    raise CollectionError("NTU zero lacks explicit rendered empty-result evidence")
                break
            before = len(rows)
            more.click(timeout=transport.timeout)
            page.wait_for_function("before => new Set([...document.querySelectorAll('.job-card a[href*=JobDetail]')].map(a=>a.href)).size > before", arg=before, timeout=transport.timeout)
        else:
            raise CollectionError("NTU normal Load More exceeded bounded page budget")
    elif source.method == "itrent":
        page = transport.browser_page()
        response = page.goto(source.fixed_route, wait_until="domcontentloaded", timeout=transport.timeout)
        transport.requests += 1
        if response is None or response.status >= 400:
            raise CollectionError(f"iTrent list HTTP {response.status if response else 'no response'}")
        page.wait_for_function("() => document.querySelector('#main-find-jobs')", timeout=transport.timeout)
        find_jobs = page.locator("#main-find-jobs")
        if not find_jobs.is_visible():
            raise CollectionError("iTrent Find jobs control is not visible")
        find_jobs.click(timeout=transport.timeout)
        page.wait_for_function("() => /\\d+\\s+jobs?\\s+match/i.test(document.body.innerText) || /\\d+\\s+open jobs/i.test(document.body.innerText) || /Results\\s*-\\s*\\d+\\s+match(?:es)?\\s+found/i.test(document.body.innerText)", timeout=transport.timeout)
        for step in range(100):
            html = page.content()
            meta = transport.save(html, page.url, f"itrent-list:{step}")
            capture(html, page.url, meta)
            total = _result_count(Document(html).root.text(), r"(\d+)\s+jobs?\s+match", r"(\d+)\s+open jobs", r"Results\s*-\s*(\d+)\s+match(?:es)?\s+found")
            if total is None:
                raise CollectionError("iTrent rendered result count disappeared")
            checkpoint["advertised_count"] = total
            if len(rows) > total:
                raise CollectionError("iTrent vacancy identities exceed exposed result count")
            more = page.locator(".Mhr-jobSearchMoreResultsButton")
            if not more.is_visible():
                if len(rows) != total:
                    raise CollectionError(f"iTrent stopped at {len(rows)} of {total} jobs")
                break
            before = len(rows)
            more.click(timeout=transport.timeout)
            page.wait_for_function("before => document.querySelectorAll('.Mhr-jobDetail--listItem[vac-id]').length > before", arg=before, timeout=transport.timeout)
        else:
            raise CollectionError("iTrent normal Show more results exceeded bounded page budget")
    elif source.method == "oracle-cloud":
        page = transport.browser_page()
        response = page.goto(source.fixed_route, wait_until="domcontentloaded", timeout=transport.timeout)
        transport.requests += 1
        if response is None or response.status >= 400:
            raise CollectionError(f"Oracle list HTTP {response.status if response else 'no response'}")
        page.wait_for_function("() => /Job search results\\s+\\d+/i.test(document.body.innerText) && (Number((document.body.innerText.match(/Job search results\\s+(\\d+)/i) || [])[1]) === 0 || document.querySelectorAll('a.job-list-item__link[href*=\\\"/job/\\\"]').length > 0)", timeout=transport.timeout)
        for step in range(100):
            html = page.content()
            meta = transport.save(html, page.url, f"oracle-list:{step}")
            capture(html, page.url, meta)
            total = _result_count(Document(html).root.text(), r"Job search results\s+(\d+)", r"(\d+)\s+Open Jobs")
            if total is None:
                raise CollectionError("Oracle rendered result count disappeared")
            checkpoint["advertised_count"] = total
            if len(rows) > total:
                raise CollectionError("Oracle vacancy identities exceed exposed result count")
            if len(rows) == total:
                break
            before = len(rows)
            page.locator("body").press("End")
            page.wait_for_function("before => new Set([...document.querySelectorAll('a.job-list-item__link[href*=\\\"/job/\\\"]')].map(a => a.href)).size > before", arg=before, timeout=transport.timeout)
        else:
            raise CollectionError("Oracle normal infinite scroll exceeded bounded page budget")
    else:
        url = source.fixed_route
        seen = set()
        while url:
            if url in seen or len(seen) >= 100:
                raise CollectionError("Normal pagination repeated/exceeded page budget")
            seen.add(url)
            html, meta = transport.fetch(url, rendered=source.method in RENDERED_DETAIL_METHODS)
            capture(html, meta["url"], meta)
            url = next_page(source, html, meta["url"])
    checkpoint["enumeration_complete"] = True
    save_checkpoint()
    return list(rows.values())


def collect(source_id, working_root, **options):
    """Keep shared run checkpoints sequential even if two invocations overlap."""
    root = Path(working_root)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".collector.lock"
    with lock.open("x", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    try:
        return _collect(source_id, root, **options)
    finally:
        lock.unlink()


def _collect(source_id, working_root, *, channel=None, headed=False, stop_after=None, transport_factory=Transport):
    registry = load_registry()
    source = registry.get(source_id)
    if source_id not in SUPPORTED_SOURCES:
        raise ValueError(f"No deterministic adapter is registered for source {source_id}")
    root = Path(working_root)
    store = WorkingStateStore(root)
    store.ensure()
    runs = {r.source_id: r for r in store.load_source_runs()}
    existing = {c.detail_url: c for c in store.load_raw_candidates() if c.source_id == source_id}
    previous = runs.get(source_id)
    checkpoint_path = root / f"{source_id}-checkpoint.json"
    if checkpoint_path.exists():
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CollectionError(f"Invalid or unreadable source checkpoint: {checkpoint_path.name}") from exc
        if not isinstance(checkpoint, dict):
            raise CollectionError("Source checkpoint must be a JSON object")
    else:
        checkpoint = {}
    for key, expected in (
        ("source_id", source_id),
        ("registry_id", registry.registry_id),
        ("registry_schema_version", registry.schema_version),
    ):
        observed = checkpoint.get(key)
        if observed is not None and observed != expected:
            raise CollectionError(f"Source checkpoint {key} disagrees with current registry/source")
        checkpoint[key] = expected
    if checkpoint.get("fixed_route", source.fixed_route) != source.fixed_route:
        raise CollectionError("Registry route changed; start a fresh run rather than reuse stale evidence")
    checkpoint["fixed_route"] = source.fixed_route
    if previous and previous.status is SourceRunStatus.RUNNING and not checkpoint_path.exists():
        raise CollectionError("Stale RUNNING source state has no checkpoint; start a fresh run")
    if previous and previous.status in {SourceRunStatus.OK, SourceRunStatus.EMPTY}:
        if len(existing) != previous.candidate_count or not checkpoint.get("enumeration_complete"):
            raise CollectionError("Completed source checkpoint disagrees with raw candidate evidence")
        return previous

    def save_checkpoint():
        temporary = checkpoint_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(checkpoint_path)

    method = {
        PILOTS[0]: "http-html",
        PILOTS[1]: "rendered-load-more",
        PILOTS[2]: "rendered-employer-pagination",
        "govuk-teaching-vacancies": "http-pagination",
        "nottingham-city-council": "oracle-rendered-infinite-scroll",
        **{source_name: "itrent-rendered-load-more" for source_name in ITRENT_SOURCES},
    }[source_id]
    run = SourceRun(source_id, collection_method=method)
    run.begin(now())
    runs[source_id] = run
    store.save_source_runs(runs.values())
    transport = transport_factory(root, source, channel=channel, headed=headed)
    candidates = []
    failures = []
    list_interrupted = False
    try:
        try:
            rows = enumerate_source(source, transport, checkpoint, save_checkpoint)
        except (Exception, KeyboardInterrupt) as exc:
            rows = checkpoint.get("rows", [])
            failures.append(f"List interrupted/incomplete: {type(exc).__name__}: {exc}")
            list_interrupted = isinstance(exc, KeyboardInterrupt)
        for row in rows:
            cached = existing.get(row["url"])
            candidate = cached or RawCandidate(source_id=source_id, source_family=source.family, raw_organization=row.get("organization", source.name), raw_title=row["title"], raw_location=row.get("location", ""), raw_salary=row.get("salary", ""), raw_deadline=row.get("deadline", ""), raw_contract=row.get("contract", ""), raw_work_pattern=row.get("work_pattern", ""), source_reference=row["reference"], source_platform_id=row["platform_id"], list_url=source.fixed_route, source_url=source.fixed_route, detail_url=row["url"], apply_url=row["url"], collected_at=now(), collection_method=method, provenance={"href_observed": True, "list_text": row.get("list_text", ""), "section": row.get("context", ""), "list_evidence": row.get("list_evidence", {})})
            candidates.append(candidate)
        store.replace_source_candidates(source_id, candidates)
        if list_interrupted:
            raise KeyboardInterrupt("Collection interrupted during list traversal")
        for index, candidate in enumerate(candidates):
            if stop_after is not None and index >= stop_after:
                raise CollectionError(f"Controlled interruption after {stop_after} detail items")
            if candidate.status == RawCandidateStatus.DETAIL_COMPLETE:
                continue
            try:
                html, meta = transport.fetch(candidate.detail_url, rendered=_source_is_rendered(source))
                facts = parse_detail(source, rows[index], html)
                apply_url = facts.pop("raw_apply_url", candidate.apply_url)
                provenance = {key: value for key, value in candidate.provenance.items() if key != "detail_error"}
                candidates[index] = replace(candidate, **facts, apply_url=apply_url, source_url=candidate.detail_url, status=RawCandidateStatus.DETAIL_COMPLETE, provenance={**provenance, "detail_evidence": meta})
            except (Exception, KeyboardInterrupt) as exc:
                failure = f"{candidate.detail_url}: {type(exc).__name__}: {exc}"
                failures.append(failure)
                candidates[index] = replace(candidate, provenance={**candidate.provenance, "detail_error": failure})
                if re.search(r"HTTP (?:401|403)|Access/security check", failure):
                    # One blocked transport is enough evidence; do not repeat it for every advert.
                    break
                if isinstance(exc, KeyboardInterrupt):
                    raise
            store.replace_source_candidates(source_id, candidates)
    except (Exception, KeyboardInterrupt) as exc:
        failures.append(f"{type(exc).__name__}: {exc}")
    finally:
        try:
            transport.close()
        except Exception as exc:
            failures.append(f"Transport close: {exc}")
        complete = checkpoint.get("enumeration_complete", False) and not failures
        outcome = (SourceRunStatus.OK if candidates else SourceRunStatus.EMPTY) if complete else (SourceRunStatus.PARTIAL if candidates else SourceRunStatus.ERROR)
        context = dict(pages=len(checkpoint.get("pages", [])), listed_count=len(checkpoint.get("rows", [])), detail_count=sum(c.status == RawCandidateStatus.DETAIL_COMPLETE for c in candidates), requests=transport.requests, cache_hits=transport.cache_hits, enumeration_complete=checkpoint.get("enumeration_complete", False), failures=failures, checkpoint=checkpoint_path.name, browser_channel=channel, headed=headed)
        run.collection_context = context
        explanation = "; ".join(failures) or "Normal path did not complete"
        run.complete(outcome, candidate_count=len(candidates), finished_at=now(), normal_collection_completed=complete, limitation=explanation if outcome == SourceRunStatus.PARTIAL else "", error=explanation if outcome == SourceRunStatus.ERROR else "")
        store.save_source_runs(runs.values())
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=SUPPORTED_SOURCES)
    parser.add_argument("--run", required=True, help="A named same-run directory under ignored .weekly-job-update")
    parser.add_argument("--browser-channel", default=None, help="Installed browser channel, e.g. msedge; default bundled Chromium")
    parser.add_argument("--headed", action="store_true", help="Ordinary minimised browser; no challenge bypass")
    parser.add_argument("--stop-after", type=int, help="Controlled detail interruption for failure/resume proof")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.run) or (args.stop_after is not None and args.stop_after < 0):
        parser.error("Run name must be a simple directory name; stop-after must be nonnegative")
    run = collect(args.source, DEFAULT_WORKING_ROOT / args.run, channel=args.browser_channel, headed=args.headed, stop_after=args.stop_after)
    print(json.dumps(run.to_mapping(), ensure_ascii=False, indent=2))
    return 0 if run.status in {SourceRunStatus.OK, SourceRunStatus.EMPTY} else 2


if __name__ == "__main__":
    raise SystemExit(main())
