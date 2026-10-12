"""Participant-facing audit hints and URL policy, separate from CSV safety.

Summary flags request editorial review; their absence never proves semantic
quality. Link decisions consume explicit access evidence, not guessed routes.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


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
    flags = []
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
    return flags
