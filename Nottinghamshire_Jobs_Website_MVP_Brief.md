# Nottinghamshire Job Opportunities — Product & Design Brief

**Organisation:** Transform Training  
**Project:** Job Update public website  
**Version:** V1.1 — role-summary compatibility migration  
**Primary audience:** Job seekers and Transform Training service users in Nottinghamshire  
**Publication model:** Static public website powered by a replaceable `jobs.csv` file  
**Hosting:** GitHub Pages  
**Technology:** Plain HTML, CSS and JavaScript. No framework, backend, database, login or runtime AI.

---

# 1. Product goal

Provide a simple public page where job seekers can quickly find current paid vacancies in Nottinghamshire, understand the basic nature of a role before opening the employer advert, and then continue to the official source.

The intended journey is:

> **filter to opportunities that may interest me → quickly understand what each job mainly involves → choose one to explore on the employer's official advert**

The site must remain easy to search, accessible, responsive, fast, simple to maintain and independent of any runtime AI or server-side application.

`job_summary` is a discovery/orientation aid only. It is not a suitability assessment, eligibility decision, recommendation, person specification or replacement for the official advert.

---

# 2. Publishing and schema migration

The normal weekly administrator task remains **replace one file: `jobs.csv`**. Website source code should not need editing during an ordinary Job Update after this migration is complete.

The schema change is deliberately staged:

## Phase 1 — compatibility preparation

- The public `jobs.csv` remains the existing 15-column feed.
- The browser must accept both the legacy 15-column header and the proposed 16-column header.
- For a legacy row, the browser treats `job_summary` as blank.
- The deterministic validator may accept either exact header during this short transition so existing weekly publication remains possible.
- A 16-column feed must **not** be published merely because the Nottinghamshire Jobs website is ready.

## Phase 2 — feed cutover

Only after Anthony confirms approved downstream consumers are ready:

- publish the first fully audited 16-column `jobs.csv`;
- verify the public CSV, this website and approved downstream consumers;
- verify row count, update date and checksum through the existing publication process.

## Phase 3 — final canonical contract

After successful cutover:

- routine publication validation must require the final 16-column contract;
- browser legacy-read compatibility may remain if useful and low-risk;
- ordinary weekly Job Update PRs return to changing `jobs.csv` only.

---

# 3. Data contract

The final canonical public feed appends `job_summary` as the last column:

```text
organization
employer_type
job_title
job_area
location
location_area
closing_date
closing_time
contract_type
work_pattern
salary
apply_url
job_reference
date_checked
source_url
job_summary
```

During Phase 1 only, the legacy header ending at `source_url` remains valid for publication.

Existing controlled values for `employer_type`, `job_area`, `location_area`, `contract_type`, `work_pattern`, dates, times, URLs, duplicate control and deterministic sorting remain unchanged.

## `job_summary` contract

Purpose: a concise, plain-language factual explanation of what the person would mainly be doing in the role.

Rules:

- normally around 2–3 sentences / roughly 40–80 words;
- plain text, one paragraph;
- whitespace normalised to single spaces with no line breaks, tabs or control characters;
- commas and quotation marks are allowed when correctly CSV-quoted;
- grounded only in current official employer/recruitment content available through the normal verification route;
- never inferred from the job title alone;
- may be blank when trustworthy current detail is insufficient or unavailable;
- a blank summary must not remove an otherwise eligible vacancy.

Do not include suitability language such as “good fit” or “ideal for”, application recommendations, participant-specific language, unsupported claims or a long person-specification list.

---

# 4. Main user experience

The first screen should make the purpose immediately clear.

Main heading: **Find current jobs in Nottinghamshire**.

Supporting text should explain that the list contains current paid vacancies from the in-scope Nottinghamshire employers.

Show:

- **Last checked:** newest `date_checked` in the dataset;
- **Current vacancies:** number of jobs currently visible after expiry filtering.

Provide a short guidance panel with this meaning:

> Short role summaries, where shown, are prepared from current vacancy information to help you understand the job. Always check the employer's official advert for full and current details.

Do not expose internal research methods, Playbook mechanics, AI processes, recruitment APIs or audit fields.

---

# 5. Search and filters

Provide:

1. Keyword search
2. Job Area
3. Organisation
4. Location
5. Sort
6. Reset filters when search/filtering is active

Keyword search is case-insensitive and updates immediately. It must search at least:

- `job_title`;
- `organization`;
- `job_area`;
- `location` / `location_area`;
- `job_summary`.

Filter values are derived from the current visible dataset. Default sort is **Closing soonest**. Preserve Organisation A–Z, Job title A–Z and Closing latest where already supported.

---

# 6. Vacancy information hierarchy

Do not present the result list as a dense spreadsheet. The role summary is important enough to sit in the main information hierarchy rather than being squeezed into a narrow metadata column.

## Desktop

Target hierarchy:

```text
JOB TITLE
Organisation
Job area

What you'd do
[2–3 sentence job_summary]

Location / work pattern / contract     Salary     Closing date     [ View & Apply ]
```

The summary should have enough horizontal width for comfortable reading and may span the main content width beneath role identity. Factual metadata remains compact and scan-friendly.

When `job_summary` is blank, omit the summary block completely and do not leave an empty heading or artificial gap.

## Mobile

Use stacked cards with this order:

1. Job title
2. Organisation
3. Job area
4. What you'd do / job summary, when present
5. Location
6. Salary
7. Contract / work pattern
8. Closing date
9. View & Apply

The summary is shown in full for V1. Do not add a Read more/accordion interaction unless real evidence later shows it is necessary.

No normal mobile width may require horizontal scrolling.

---

# 7. Apply action and shared routes

Use `apply_url` for the public action.

For a stable individual vacancy route, label the action **View & Apply**.

If several distinct current vacancies legitimately share the same recruitment page, preserve the existing shared-route behaviour: label the action **Open vacancies page** and show `job_reference` as an additional lookup cue when available. A shared URL alone must never collapse distinct jobs.

External links must remain keyboard accessible and use safe link attributes.

---

# 8. Closing dates and automatic expiry

Preserve the existing Europe/London logic:

1. Hide jobs whose `closing_date` is before today's UK date.
2. For a job closing today with an explicit `closing_time`, hide it after that time.
3. For a job closing today without a time, keep it visible for the whole date.
4. Never infer or modify the stored deadline.
5. Keep the readable UK date and existing urgency labels.

---

# 9. CSV parsing and failure behaviour

CSV parsing must support quoted commas and quotation marks correctly; it must not split rows naively on commas.

During Phase 1 the parser must explicitly recognise only:

- the exact legacy 15-column header; or
- the exact 16-column header with `job_summary` appended.

Reject malformed/unsupported header shapes rather than silently shifting positional data. A legacy row receives `job_summary = ""` internally.

Keep the existing service-user-safe states for no matches, no current vacancies and CSV-load failure.

---

# 10. Accessibility and visual direction

Target WCAG 2.2 AA good practice. Preserve semantic HTML, one clear H1, labelled controls, visible keyboard focus, logical keyboard order, sufficient contrast, large enough tap targets, responsive text and `prefers-reduced-motion` support.

The site should remain calm, practical, accessible and community-service oriented. Avoid dashboard/AI aesthetics, decorative gradients, unnecessary animation, dense badges, stock imagery or commercial job-board clutter.

Vacancy content remains the visual priority.

---

# 11. Technical architecture and privacy

Keep the existing static architecture:

- GitHub Pages;
- `index.html`;
- `styles.css`;
- `app.js`;
- `jobs.csv`;
- documentation and deterministic tests/validator.

Do not introduce React/Vue/Angular, a package-manager runtime dependency, backend, database, authentication, serverless function or runtime AI.

No participant-private profile, Match, CV, application or suitability data belongs in this repository or feed.

The existing lightweight web analytics configuration is independent of vacancy enrichment and should not be changed as part of an ordinary Job Update.

---

# 12. Deterministic validation

During Phase 1 the validator must fail closed while accepting the two explicitly supported schemas. Existing eligibility-derived structural rules remain intact.

For a 16-column row:

- `job_summary` may be blank;
- it must already be normalised as one plain paragraph;
- line breaks, tabs and control characters are invalid;
- valid CSV commas and escaped quotation marks must not corrupt field count.

Regression coverage must include legacy parsing, 16-column parsing, blank summary, valid summary, comma/quote-containing summary, malformed rows and existing link-policy behaviour.

At feed cutover, use an explicit validator mode that requires the summary column. After successful migration, make that 16-column requirement the routine publication default.

---

# 13. Browser acceptance criteria

Before Phase 1 handoff verify at minimum:

- [ ] current legacy 15-column `jobs.csv` still loads;
- [ ] 16-column test data loads;
- [ ] legacy rows render with no summary block;
- [ ] a non-empty summary renders under **What you'd do**;
- [ ] summary text participates in keyword search;
- [ ] blank summary leaves no empty heading/gap;
- [ ] expiry behaviour is unchanged;
- [ ] filters and sorting are unchanged;
- [ ] individual/shared apply-link behaviour is unchanged;
- [ ] desktop list remains scan-friendly;
- [ ] mobile order matches this brief and has no horizontal overflow;
- [ ] keyboard focus remains visible;
- [ ] no runtime AI, backend or database has been introduced.

---

# 14. Weekly research boundary

Summary enrichment belongs to normal vacancy verification, not a separate unbounded crawl.

Use summary detail when the official/full advert is already read, a substantive role-purpose/short-description is already provided, or the normal source-specific verification method already uses one ordinary detail fetch.

Do not escalate to expensive browser/crawler/recovery work solely because a summary is missing. Publish an otherwise valid vacancy with a blank summary when sufficient current detail is not available.

Track summary coverage and missing-summary reasons internally during the first several weekly runs. Do not set a mandatory coverage target until real operating evidence justifies one.

---

# 15. Non-goals

Do not implement in this migration:

- structured public requirements/person-specification fields;
- participant-specific AI opportunity discovery;
- AI recommendations, rankings or suitability scores;
- participant-private data;
- saved jobs, accounts, application tracking, alerts, employer submissions, CMS or admin dashboard.

Those require separate future decisions.

---

# 16. Success definition

The change succeeds when a service user can scan a vacancy, understand in a short factual paragraph what the work mainly involves when reliable detail is available, and then continue to the employer's official advert; while Transform Training retains the same simple static publication model and safe weekly replacement workflow.
