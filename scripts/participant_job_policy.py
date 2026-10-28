"""Participant-facing audit hints and URL policy, separate from CSV safety.

Quality flags request editorial review; their absence never proves semantic
quality. The CLI reads a candidate CSV and prints advisory findings only.
Link decisions consume explicit access evidence, not guessed routes.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

from scripts.validate_job_update import parse_csv_bytes


def text_review_flags(text):
    """Flag strong extraction-residue signals without interpreting source facts."""
    flags = []
    if re.search(r"</?(?:p|div|span|br|li|ul|ol|a|strong|em|script|style|h[1-6])\b[^>]*>", text, re.I):
        flags.append("markup_residue")
    if re.search(r"<script\b|\bfunction\s+[A-Za-z_$][\w$]*\s*\([^)]*\)\s*\{|\b(?:document|window)\.[\w$]+\s*\(|\b(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=[^;\n]+;", text, re.I):
        flags.append("script_residue")
    if re.search(r"\{\{[^{}\n]+\}\}|\$\{[^{}\n]+\}|\[object Object\]", text) or text.strip() in {"undefined", "null", "NaN"}:
        flags.append("unresolved_placeholder")
    return flags


def salary_review_flags(salary):
    """Labels from other advert fields suggest an over-wide salary extraction."""
    if re.search(r"\b(?:directorate|location|closing\s+date|job\s+reference|contract(?:\s+type)?|working\s+hours)\s*:", salary, re.I):
        return ["salary_contains_other_fields"]
    return []


def has_itrent_session(url):
    return any(key.casefold() == "usession" for key in parse_qs(urlparse(url).query, keep_blank_values=True))


def participant_destination(source, observed_url, *, fresh_session_usable=False):
    if source.method == "itrent" and (has_itrent_session(observed_url) or not fresh_session_usable):
        return source.fixed_route
    return observed_url


def validate_participant_url(source, url):
    if source.method == "itrent" and has_itrent_session(url):
        raise ValueError("iTrent participant apply_url must not contain USESSION; use the stable registry board when detail is session-bound")


def eligibility_review_flags(title):
    """Bounded public-eligibility hint, not automatic broad 'internal' exclusion."""
    if re.search(r"\binternal\s+(?:vacancy\s+)?only\b", title, re.I):
        return ["explicit_internal_only_requires_eligibility_review"]
    return []


def summary_review_flags(summary):
    """Find known defect patterns; short factual summaries still need judgement."""
    if not summary.strip():
        return ["blank_requires_detail_limitation"]
    flags = text_review_flags(summary)
    if re.search(r"\b(?:read|show|see|view)\s+more\s*(?:\.{3}|\u2026|[.!?])?\s*$", summary, re.I):
        flags.append("unexpanded_description")
    if re.search(r"(?:\.{3}|\u2026)\s*$", summary):
        flags.append("possible_truncation_requires_review")
    if len(summary.split()) < 30:
        flags.append("short_requires_semantic_review")
    if re.search(r"build a rewarding career|doing things differently|be part of something bigger|diverse community\.\s*inclusive research", summary, re.I):
        flags.append("employer_branding")
    if re.search(r"\bArea\b.*\bLocation\b.*\bSalary\b|^\s*(?:Contract|Working [Hh]ours|Hours|Location|Salary)\s*:", summary):
        flags.append("metadata_first")
    if re.search(r"we.ve got an exciting opportunity|we offer.*(?:benefits|pension)|join our.*(?:fantastic|dynamic|excellent)|our vision|creating unforgettable|^The University of Nottingham has been providing|^This is a great opportunity|^Are you (?:a |an )?(?:passionate|enthusiastic)", summary, re.I):
        flags.append("promotional_requires_semantic_review")
    if re.match(r"\s*(?:About you|Qualified Teacher Status|Degree in|You (?:must|will need)|Candidates? (?:must|should)|(?:Relevant )?Experience (?:of|in)|Relevant teaching experience|Essential criteria|Clear understanding|Is (?:exceptionally|committed)|Your ideas on)", summary, re.I):
        flags.append("requirements_first")
    if re.match(r"(?:We are looking for|You will have|Be (?:a .*teacher|willing)|Have excellent)", summary, re.I):
        flags.append("recruitment_or_criteria_prefix_requires_review")
    if re.search(r"(?:to ensure a high|highest standard of|supporting with|work as part of a|and a|at all)\.$|;\.", summary, re.I):
        flags.append("truncated_sentence")
    if len(summary.split()) == 80:
        flags.append("possible_truncation_requires_review")
    if re.search(r"Hours:.*Contract:.*Salary:|Closing date:.*Interviews:", summary, re.I):
        flags.append("metadata_first")
    if re.search(r"\b(?:seeking to appoint|seeking a dedicated|are looking for|is seeking)\b|^37 hours per w\b", summary, re.I):
        flags.append("recruitment_prefix_requires_review")
    if re.search(r"Protected Characteristics|Disability Confident|equality and diversity in.*employment", summary, re.I):
        flags.append("employer_edi_boilerplate")
    return list(dict.fromkeys(flags))


def quality_review_findings(rows, *, record_numbers=None):
    """Review finished rows without changing, excluding or validating them.

    The CSV caller supplies original record numbers, including blank records;
    a quoted multiline record is still one record. In-memory callers default
    to consecutive records after the header. Employer groups of at least three
    rows give an all-blank-field hint, not a claim about source completeness.
    A missing job_summary key, as in a legacy feed, is not an extraction defect.
    """
    rows = list(rows)
    if record_numbers is None:
        record_numbers = range(2, len(rows) + 2)
    findings = []
    employers = {}
    summaries = {}
    reasons = {
        "markup_residue": "Text contains HTML tags; check the retained advert evidence.",
        "script_residue": "Text contains script syntax; check which page content was extracted.",
        "unresolved_placeholder": "Text contains an unresolved template or object value.",
        "salary_contains_other_fields": "Salary contains labels from other advert fields.",
        "unexpanded_description": "Summary ends with an expansion control; check for unread role text.",
        "possible_truncation_requires_review": "Summary may be cut short; compare with retained role evidence.",
        "repeated_summary": "Different roles have the same substantial summary; check for generic or copied text.",
        "employer_field_entirely_blank": "This field is blank across at least three employer rows; check whether the source genuinely omits it.",
    }

    def add(code, field, numbers, **context):
        findings.append(dict(code=code, field=field, row_numbers=numbers,
            reason=reasons.get(code, code.replace("_", " ").capitalize()), **context))

    for number, row in zip(record_numbers, rows, strict=True):
        for field, text in row.items():
            if field == "job_summary":
                flags = summary_review_flags(text)
            else:
                flags = text_review_flags(text)
                if field == "salary":
                    flags += salary_review_flags(text)
            for code in flags:
                add(code, field, [number])
        employer = " ".join(row.get("organization", "").split()).casefold()
        if employer:
            employers.setdefault(employer, []).append((number, row))
        summary = " ".join(row.get("job_summary", "").split()).casefold()
        if len(summary.split()) >= 30:
            summaries.setdefault(summary, []).append((number, row))

    for group in summaries.values():
        roles = {
            tuple(" ".join(row.get(field, "").split()).casefold()
                  for field in ("organization", "job_title", "job_reference"))
            for _, row in group
        }
        if len(roles) > 1:
            add("repeated_summary", "job_summary", [number for number, _ in group])
    for group in employers.values():
        if len(group) < 3:
            continue
        for field in ("salary", "job_summary"):
            if all(field in row and not row[field].strip() for _, row in group):
                add("employer_field_entirely_blank", field,
                    [number for number, _ in group], organization=group[0][1]["organization"])
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read a candidate CSV and report advisory quality findings; never modifies or rejects vacancy rows.")
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args(argv)
    candidate_bytes = args.candidate.read_bytes()
    rows, columns = parse_csv_bytes(candidate_bytes)
    # The shared parser deliberately skips blank records. Read their positions
    # from the same bytes without changing that parser or counting physical lines.
    reader = csv.reader(io.StringIO(candidate_bytes.decode("utf-8-sig"), newline=""), strict=True)
    next(reader)  # Header already checked by the shared parser.
    record_numbers = [number for number, record in enumerate(reader, start=2)
                      if any(value.strip() for value in record)]
    if "job_summary" not in columns:
        # The shared parser supplies a blank compatibility value for legacy rows.
        rows = [{key: value for key, value in row.items() if key != "job_summary"} for row in rows]
    findings = quality_review_findings(rows, record_numbers=record_numbers)
    print(json.dumps(dict(advisory_only=True, row_count=len(rows),
        finding_count=len(findings), findings=findings), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
