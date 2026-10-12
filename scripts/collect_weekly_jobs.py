"""Three evidence-only pilot adapters. Run one registered source per invocation.

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

from scripts.weekly_job_update import (
    DEFAULT_WORKING_ROOT, RawCandidate, RawCandidateStatus, SourceRun,
    SourceRunStatus, WorkingStateStore, load_registry,
)

PILOTS = ("university-of-nottingham", "nottingham-trent-university", "nottingham-university-hospitals")


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
    if any(marker in text for marker in ("complete the security check", "verify you are human", "access denied", "just a moment", "checking your browser")):
        raise CollectionError("Access/security check returned instead of vacancy evidence")
    return root


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
    else:
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


def parse_detail(source, row, html):
    root = check_document(html)
    facts = labelled(root)
    body = ""
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
    else:
        if not root.nodes(cls="hj-job-details"):
            raise CollectionError("HealthJobsUK job summary facts missing")
        containers = [n for n in root.nodes() if n.attrs.get("id") in {"hj-job-advert", "hj-job-description"}]
        body = " ".join(n.text() for n in containers) if containers else root.text()
    if not body:
        raise CollectionError("Advert has no readable body evidence")
    location = facts.get("location", row.get("location", ""))
    if source.source_id == PILOTS[2]:
        location = ", ".join(v for v in (facts.get("site", ""), facts.get("town", "")) if v)
    return dict(raw_location=location, raw_deadline=facts.get("closing date", facts.get("closing", row.get("deadline", ""))), raw_salary=facts.get("salary", row.get("salary", "")), raw_contract=facts.get("contract", facts.get("employment type", row.get("contract", ""))), raw_work_pattern=facts.get("hours", ""), source_reference=facts.get("reference", facts.get("job ref", row.get("reference", ""))), raw_organization=facts.get("employer", row.get("organization", source.name)), detail_body=body)


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
                    html = page.content()
                    final_url = page.url
                else:
                    with urlopen(Request(url, headers={"User-Agent": "NottinghamshireJobs-Collector/0.1"}), timeout=self.timeout / 1000) as response:
                        html = response.read().decode(response.headers.get_content_charset() or "utf-8")
                        final_url = response.url
                if urlparse(final_url).netloc != urlparse(url).netloc:
                    raise CollectionError(f"Unexpected redirect: {final_url}")
                before, after = urlparse(url), urlparse(final_url)
                for identity_key in ("ref", "JobId", "emp"):
                    expected = parse_qs(before.query).get(identity_key)
                    if expected and parse_qs(after.query).get(identity_key) != expected:
                        raise CollectionError(f"Redirect lost registered/advert identity: {final_url}")
                expected_id = re.search(r"-v\d+", before.path)
                if expected_id and expected_id.group() not in after.path:
                    raise CollectionError(f"Redirect lost HealthJobsUK advert identity: {final_url}")
                return html, self.save(html, final_url, key)
            except HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt:
                    raise
            except (URLError, TimeoutError):
                if attempt:
                    raise
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

    if source.source_id == PILOTS[1]:
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
    else:
        url = source.fixed_route
        seen = set()
        while url:
            if url in seen or len(seen) >= 100:
                raise CollectionError("Normal pagination repeated/exceeded page budget")
            seen.add(url)
            html, meta = transport.fetch(url, rendered=source.source_id == PILOTS[2])
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
    source = load_registry().get(source_id)
    if source_id not in PILOTS:
        raise ValueError("Only the three released pilot adapters are supported")
    root = Path(working_root)
    store = WorkingStateStore(root)
    store.ensure()
    runs = {r.source_id: r for r in store.load_source_runs()}
    existing = {c.detail_url: c for c in store.load_raw_candidates() if c.source_id == source_id}
    previous = runs.get(source_id)
    checkpoint_path = root / f"{source_id}-checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {}
    if checkpoint.get("fixed_route", source.fixed_route) != source.fixed_route:
        raise CollectionError("Registry route changed; start a fresh run rather than reuse stale evidence")
    checkpoint["fixed_route"] = source.fixed_route
    if previous and previous.status in {SourceRunStatus.OK, SourceRunStatus.EMPTY}:
        if len(existing) != previous.candidate_count or not checkpoint.get("enumeration_complete"):
            raise CollectionError("Completed source checkpoint disagrees with raw candidate evidence")
        return previous

    def save_checkpoint():
        temporary = checkpoint_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(checkpoint_path)

    method = {PILOTS[0]: "http-html", PILOTS[1]: "rendered-load-more", PILOTS[2]: "rendered-employer-pagination"}[source_id]
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
            candidate = cached or RawCandidate(source_id=source_id, source_family=source.family, raw_organization=row.get("organization", source.name), raw_title=row["title"], raw_location=row.get("location", ""), raw_salary=row.get("salary", ""), raw_deadline=row.get("deadline", ""), raw_contract=row.get("contract", ""), source_reference=row["reference"], source_platform_id=row["platform_id"], list_url=source.fixed_route, source_url=source.fixed_route, detail_url=row["url"], apply_url=row["url"], collected_at=now(), collection_method=method, provenance={"href_observed": True, "list_text": row.get("list_text", ""), "section": row.get("context", ""), "list_evidence": row.get("list_evidence", {})})
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
                html, meta = transport.fetch(candidate.detail_url, rendered=source_id == PILOTS[2])
                facts = parse_detail(source, rows[index], html)
                provenance = {key: value for key, value in candidate.provenance.items() if key != "detail_error"}
                candidates[index] = replace(candidate, **facts, source_url=candidate.detail_url, status=RawCandidateStatus.DETAIL_COMPLETE, provenance={**provenance, "detail_evidence": meta})
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
    parser.add_argument("--source", required=True, choices=PILOTS)
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
