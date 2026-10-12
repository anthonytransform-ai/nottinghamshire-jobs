# Job Search Playbook — Weekly Update

**Project:** Nottinghamshire Jobs / Transform Training
**Purpose:** Find, verify, classify and publish useful current paid vacancies in Nottinghamshire for job seekers.

---

## 1. Weekly objective

The Weekly Job Update exists to help job seekers find useful current jobs.

> **Go to the fixed known sources, collect the genuine current Nottinghamshire vacancies they expose, finish each included vacancy into a useful participant-facing row, and publish the verified dataset.**

The weekly update is not a technical audit of recruitment platforms. Do not delay useful verified vacancies because a platform cannot be proved perfectly enumerable.

The quality of the weekly update is judged primarily by the usefulness and trustworthiness of the vacancy rows that are published.

---

## 2. Operating model — one source at a time

The weekly workflow is deliberately sequential.

> **Open one source → collect that source's candidate jobs → finish that source's included rows → close that source → move to the next source.**

Do **not** collect unfinished list-level rows from many sources and plan to enrich them later.

### Current-vacancy timing rule

A useful current vacancy does **not** need a fixed closing date. Include a live vacancy when it is currently open and accepting applications. If the advert states a deadline, verify that it has not passed. Rolling, open-until-filled and no-deadline vacancies can remain eligible while the advert is live. Never invent a closing date just to satisfy the CSV or validator.

### 2.1 Source work unit

For each fixed source, complete these four stages before moving on:

1. **Open** — go directly to the fixed registry route. Use the registry's one simple fallback only when needed.
2. **Collect** — capture the current candidate vacancies exposed by the normal list, pagination or load-more path. Preserve each source-exposed individual href/ID/reference.
3. **Finish rows** — process the candidates from this source one by one. Filter, open the individual advert where available, verify the required facts, set the best `apply_url`, capture the reference/details and write `job_summary` when the advert provides useful role content.
4. **Close source** — confirm that no included vacancy from this source remains unfinished merely because the workflow stopped at the list page. Then mark the source finished and move on.

### 2.2 Source completion gate

A source may be marked **finished** when:

- its normal visible list/pagination has been processed as far as reasonably accessible through the registered route;
- every captured candidate has either been excluded for a row-level reason or completed into a usable row;
- source-exposed individual advert links have been retained and followed where normally accessible;
- every remaining shared/list/board `apply_url` reflects a genuine source limitation rather than skipped click-through;
- every blank `job_summary` reflects genuinely unavailable/insufficient detail rather than skipped normal advert reading.

This gate is about finishing the rows already found. It is **not** a requirement to prove a recruitment system's total population.

### 2.3 Attention rule

While working on Source A, do not start Source B unless Source A has passed the source completion gate.

If the weekly run is interrupted, resume from the first source not yet marked finished. Do not restart already finished same-run sources unless their evidence has clearly become stale or Anthony asks for a rerun.

A simple temporary checklist is sufficient:

```text
[ ] not started
[~] current source
[x] source finished
```

Do not turn this checklist into a source-completeness ledger.

---

## 3. Fixed weekly Source Registry

The canonical machine-readable registry is
`.agents/skills/weekly-job-update/references/source-registry.json`. It is the
single maintained owner of the 19 fixed source identities, source families,
collection methods, fixed routes, individual-route patterns, platform identity
and registered fallbacks. Load it before a weekly run and iterate its records
in listed order; do not rediscover these recruitment systems every week.

The registry's `fixed_route` must remain the most specific stable current-
vacancy list/search surface we know, rather than a generic careers landing page
when a better stable list URL exists. Critical suffixes and query parameters
belong in that JSON record so the agent does not have to infer them later.

This Playbook retains the operating and judgement rules for using those source
records: one-source-at-a-time collection, ordinary pagination, row-level
exclusions, individual-advert completion, fallback boundaries and final
classification. It must refer to registry records rather than restating their
routes, methods or fallback configuration. Do not maintain a competing source
list or route table here.

The registry's source-family order is councils, NHS, education and VCSE. The
19 records in the registry are the complete fixed weekly source set.

### 3.1 Councils

Load the first nine records in registry order. Use each record's fixed route,
individual-route pattern, method and registered fallback; the source-specific
technical notes in Section 12 preserve the recurring operating traps without
duplicating those values here.

### 3.2 NHS

Load the three NHS records in registry order. Filter each Trust by actual work
base, complete qualifying individual adverts and exclude an individual advert
that is expired or withdrawn even if its collection still lists it.

If a collection still lists a vacancy whose individual page is expired or withdrawn, exclude that vacancy. Do not investigate whether the whole collection is stale.

### 3.3 Education

Load the six education records in registry order. The University and NTU
surface-specific rules are retained in Section 12; complete the individual
advert before closing each source. Exclude external apprenticeships advertised
to learners when processing college staff vacancies.

### 3.4 VCSE

Load the final VCSE record from the registry. If the fixed page is unavailable,
use only its registered fallback and follow current vacancy or employer links;
do not broadly rediscover charity jobs.

---

## 4. Normal weekly run

### Phase 0 — Start the run

1. Read this Playbook.
2. Set the current date/time in **Europe/London**.
3. Use one common `date_checked` value for the whole weekly dataset.
4. Create the temporary 19-source checklist.
5. Begin with the first source. Only one source is active at a time.

### Phase 1 — Complete the 19 fixed sources sequentially

For each source, run the Source Work Unit from Section 2.

#### A. Open the source

- Go directly to the fixed route in the registry.
- If the normal route is blocked, use only the source's registered simple fallback.
- Do not rediscover the recruitment platform or broaden into a general employer job search.

#### B. Collect this source's candidates

Capture the current vacancies exposed by the normal visible list, ordinary pagination or load-more controls.

For each candidate, preserve whatever the source already exposes, especially:

- title;
- organisation/employer where shown;
- displayed location;
- closing date/time where shown;
- salary/pay where shown;
- advertised reference where shown;
- platform vacancy/job ID where shown;
- **actual source-exposed individual href/path**.

Do not discard individual hrefs/IDs after extracting list-level fields.

Follow ordinary pagination/load-more for this source. Do not stop at the first page simply because enough jobs have already been found.

There is no requirement to reconcile the captured set against a backend count before proceeding.

#### C. Apply cheap exclusions

Before opening every detail page, remove obvious non-candidates such as:

- expired jobs;
- clearly out-of-county roles;
- Internal Only roles;
- unpaid/non-employment opportunities;
- talent pools/register-interest items;
- obvious employer-scope exclusions;
- obvious duplicates already captured from the same source.

If an essential fact is ambiguous, keep the candidate and resolve it from the individual advert.

#### D. Finish the remaining candidates one by one

For each remaining candidate:

1. follow the source-exposed individual advert or deterministic job-specific route when available;
2. confirm current/open status; capture the closing date/time when one is stated, but do not require a deadline for eligibility;
3. verify the actual Nottinghamshire work base or qualifying host/service relationship;
4. capture the advertised employer and reference where present;
5. capture contract/work pattern/salary where available and needed;
6. retain the best current job-specific `apply_url`;
7. retain the strongest current verification `source_url`;
8. classify `employer_type`, `job_area`, `location_area`, `contract_type` and `work_pattern`;
9. when the advert contains useful role-purpose/main-duties content, write the grounded `job_summary` now;
10. add the completed row to the working dataset, or exclude the candidate for a specific row-level reason.

Do not defer the individual-advert work to a later all-sources enrichment pass.

#### E. Close this source

Before changing to the next source, check:

- no qualifying candidate from this source remains as an unfinished list-level row;
- every available source-exposed individual job link has been used as the participant destination or consciously rejected for a specific reason;
- shared/list/board `apply_url`s have a genuine source limitation;
- blank summaries have a genuine detail limitation;
- all included rows from this source are complete enough to publish if the weekly run ended now.

Then mark this source `[x]` and move to the next source.

### Phase 2 — Optional fixed supplements

Only after all 19 fixed sources are finished, inspect fixed supplementary sources when useful.

Use the **same Source Work Unit**: collect and finish one supplementary source before opening another.

Supplementary sources are not an open-ended market search.

### Phase 3 — Consolidate the finished rows

After all fixed sources are finished:

1. combine the already completed rows;
2. deduplicate cross-source mirrors;
3. apply the final controlled classifications consistently;
4. sort deterministically;
5. generate the exact 16-column `jobs.csv`.

Do not rebuild the dataset manually from prose notes.

### Phase 4 — Participant-facing quality audit

Audit only the finished dataset:

- count total rows;
- count job-specific `apply_url`s;
- count shared/list/board `apply_url`s;
- count non-blank `job_summary`s;
- count blank `job_summary`s.

Review only the exceptions:

- every shared/list/board `apply_url` must have a genuine source limitation;
- every blank `job_summary` must have a genuine detail limitation;
- if a source normally exposes individual adverts but many rows still point to its board, return to that source and repair those rows before publication.

There is no percentage target. The purpose is to catch skipped normal row completion.

### Phase 5 — Deterministic validation

Run the repository validator against the **exact final candidate file**.

Do not report validation as passed unless the validator was actually executed successfully against those exact bytes.

### Phase 6 — GitHub publication candidate

For a normal weekly update:

1. start from current `main`;
2. create the normal dated update branch;
3. replace **only `jobs.csv`**;
4. commit and push the exact validated candidate;
5. open the pull request to `main`;
6. report the result to Anthony.

Do not merge unless Anthony explicitly asks.

---

## 5. Supplementary fixed sources

These are bounded supplements, not additional mandatory completeness sweeps.

| Source | Fixed route / use |
|---|---|
| Nottinghamshire TAL Talent Bank | `https://nottinghamshire.tal.net/vx/lang-en-GB/mobile-0/appcentre-ext/brand-8/candidate/jobboard/talentbank/1` — inspect quickly after the fixed sources. Include only genuine current paid vacancies; normal register-interest material that is not an actual vacancy does not qualify. A missing or rolling closing date is not itself an exclusion reason. |
| Nottingham City school jobs / eTeach | `https://www.eteach.com/schools/nottingham-city-council-5845` — useful fixed Nottingham-city school supplement with individual adverts. |
| Major local academy-trust routes | Use the project's known fixed trust careers routes when useful. They are optional supplements, not a second mandatory school sweep. |

Do not add open-ended weekly requirements such as “other useful NHS employers”, “other universities”, “other FE colleges” or “other credible VCSE sources”. Broader discovery requires a separate reason or request.

---

## 6. Vacancy eligibility

Include a vacancy when all of the following are true:

- genuine paid job;
- approved employer type: `Council`, `NHS`, `Education` or `VCSE`;
- actual work base is in Nottinghamshire, or the advert clearly establishes a qualifying Nottinghamshire host/service relationship;
- currently open;
- currently open and accepting applications.

A fixed closing date is **not required**. If the advert states a closing date/time, it must not already have passed. Vacancies advertised as rolling, open until filled, or with no stated deadline can qualify while the current advert is live and accepting applications. There is no maximum future closing-date horizon when a date is stated.

Exclude:

- expired or withdrawn vacancies;
- talent pools or register-interest pages that are not current vacancies;
- unpaid volunteering or unpaid work experience;
- scholarships, bursaries, studentships or study opportunities that are not employment;
- internal-only vacancies unavailable to the public;
- jobs with no verified Nottinghamshire base/qualifying host relationship;
- obvious duplicates;
- vacancies whose essential row-level facts cannot be verified without guessing.

A source-access limitation is not itself a row-level exclusion reason.

Neither is the absence of a fixed closing date. Do not reject an otherwise useful live vacancy because the employer uses rolling recruitment, open-until-filled wording, or simply does not publish a deadline.

---

## 7. Employer and host/service rules

Shared recruitment systems can contain jobs for different employers. Classify the actual vacancy, not the platform hostname.

For `Council`, `NHS` and `Education`, a role may qualify when the contractual employer is an agency, subsidiary or contractor **only when the current advert explicitly shows that the role is based at, or directly provides the relevant service for, an in-scope Nottinghamshire host**.

Examples:

- contractor-employed catering role specifically based at an in-scope NHS hospital → `NHS`;
- agency vacancy explicitly for a Nottinghamshire council service/base → `Council`;
- contractor-employed facilities role specifically based at an in-scope college/school/university → `Education`.

Do not include a generic agency/contractor vacancy when the client or host is not identified.

For `VCSE`, host association does not widen the category. The actual organisation must itself be a credible charity, voluntary/community organisation, social enterprise or CIC within project scope.

### `organization`

Use the public-facing advertised employer when the advert clearly names a distinct contractual employer. Otherwise use the host organisation.

---

## 8. Geography

Eligibility is based on the **actual work location**, not the employer's headquarters.

Qualifying geography includes:

- Nottingham
- Broxtowe
- Ashfield
- Bassetlaw
- Gedling
- Mansfield
- Newark & Sherwood
- Rushcliffe
- Nottinghamshire-wide
- Multiple Nottinghamshire locations

Hybrid/home-working roles qualify only when they are clearly attached to a Nottinghamshire base or substantive Nottinghamshire service.

Exclude Derbyshire, Leicestershire, Lincolnshire or other out-of-county bases unless the vacancy also has a genuine required Nottinghamshire base covered by the role.

When one portal contains local and non-local vacancies, filter the individual rows by their actual base. Do not investigate why the portal contains out-of-county jobs.

---

## 9. Classification rules

### 9.1 `employer_type`

Use exactly one of:

- `Council`
- `NHS`
- `Education`
- `VCSE`

### 9.2 `job_area`

Classify by the **main function of the job**, not the employer sector.

Allowed values:

- `Administration & Business Support`
- `Care & Support`
- `Children & Young People`
- `Community & Outreach`
- `Customer Service`
- `Education & Training`
- `Finance & Procurement`
- `Health & Clinical`
- `HR & People`
- `Housing & Homelessness`
- `IT & Digital`
- `Legal & Governance`
- `Management & Leadership`
- `Planning, Environment & Regulatory`
- `Property, Facilities & Operations`
- `Transport & Driving`
- `Leisure, Sport & Culture`
- `Other`

Examples:

- school cleaner → `Property, Facilities & Operations`
- university receptionist → `Customer Service` or `Administration & Business Support`, depending on the role
- teaching assistant → `Education & Training` or `Children & Young People`, depending on the main function
- trust HR administrator → `HR & People`
- hospital finance officer → `Finance & Procurement`, not `Health & Clinical`

Use `Other` only when no existing area reasonably describes the main function.

### 9.3 `location_area`

Use exactly one of:

- `Nottingham`
- `Broxtowe`
- `Ashfield`
- `Bassetlaw`
- `Gedling`
- `Mansfield`
- `Newark & Sherwood`
- `Rushcliffe`
- `Nottinghamshire-wide`
- `Multiple Nottinghamshire locations`

Use `location` for the more specific participant-facing wording from the advert, such as `Beeston`, `Queen's Medical Centre, Nottingham`, `Worksop` or `Multiple sites across Nottinghamshire`.

### 9.4 `contract_type`

Use exactly one of:

- `Permanent`
- `Fixed-term`
- `Temporary`
- `Apprenticeship`
- `Bank/Casual/Sessional`
- `Freelance`
- `Other`

Map from the advert's actual contractual wording. Do not infer permanence when the source does not state it.

### 9.5 `work_pattern`

Use exactly one of:

- `Full-time`
- `Part-time`
- `Full-time or Part-time`
- `Variable/Sessional`
- `Not stated`

Do not infer full-time/part-time solely from salary or title.

---

## 10. Individual adverts and URLs

### 10.1 `apply_url`

`apply_url` is the participant-facing destination.

Prefer, in order:

1. source-exposed current individual vacancy/application page;
2. deterministic current job-specific route when the source exposes the required ID;
3. shared vacancies page only when the source genuinely does not provide a safely usable individual route or the registered normal method cannot resolve one.

When a list displays a clickable job title, preserve that actual target and follow it during the current source's row-finishing stage.

Do not replace a source-exposed job-specific target with the board URL merely because the board is easier to fetch.

If the current list exposes a genuine job-specific href but the detail page cannot be rendered, keep that href as `apply_url` when it is clearly the current vacancy destination.

Do not manufacture a job URL from a title or guessed slug.

A repeated/shared `apply_url` across several vacancies is a quality warning. If the source normally exposes individual adverts, return to that source before publication and repair the rows.

### 10.2 `source_url`

`source_url` records the strongest current page used to verify the vacancy. It may be:

- the same individual advert as `apply_url`;
- the official list/board page;
- the exact official indexed fallback used when direct access was blocked.

`source_url` is evidence context; it is not automatically a second application destination.

### 10.3 Human reference versus platform ID

Keep the advertised job reference separate from technical platform IDs unless the source clearly shows they are the same.

For iTrent, do not assume a human-readable `REQ...` reference is the same as `VACANCY_ID`.

---

## 11. `job_summary`

`job_summary` helps a job seeker quickly understand what the role mainly involves and is rendered directly by the website.

Use current advert content only.

Good source content includes:

- role purpose;
- job overview;
- main duties;
- concise role description.

Rules:

- normally about 2–3 sentences / roughly 40–80 words;
- one plain-text paragraph;
- normalise unnecessary whitespace to single spaces;
- no embedded line breaks, tabs or control characters;
- commas and quotation marks are allowed when correctly CSV-quoted;
- describe what the person would mainly do;
- no suitability judgement or participant-specific recommendation;
- no invented duties;
- do not infer a summary from the job title alone;
- avoid copying long requirements/person-specification lists.

If the individual advert is opened during normal verification and contains substantive role-purpose/main-duties content, write the summary **before leaving that vacancy**.

A successfully read advert with useful role content and a blank `job_summary` is an unfinished row.

If a current individual advert is available but has not yet been opened, open it once as part of normal row completion. If it is blocked, unavailable or lacks enough useful role content, leave `job_summary` blank.

Do **not** start search-engine recovery, PDF hunting or alternate-route investigation solely to fill a summary.

A blank summary does not make an otherwise valid vacancy ineligible, but it must result from genuine detail unavailability/insufficiency rather than skipped normal click-through.

There is no numerical summary-coverage target.

---

## 12. Source-specific technical notes

These notes explain recurring technical traps. They do not replace the one-source-at-a-time workflow.

### 12.1 Nottinghamshire TAL

- Use the `nottinghamshire-tal` registry record and its fixed route.
- A human-verification screen does not mean there are no jobs.
- The registry record identifies the stable board identity; any disposable session or indexing token in a rendered URL does not change that identity.
- If direct access fails, use fresh search/indexing restricted to `nottinghamshire.tal.net` to reach the current official board/content.
- This exact-domain fallback is permitted access to the known source; it is not source rediscovery.
- Preserve and follow the current source-exposed individual link matching the registry's individual-route pattern.
- Do not reconcile competing cached/indexed board counts.
- Classify each vacancy normally; a school/trust vacancy on TAL can be `Education` rather than `Council`.

### 12.2 Nottingham City Oracle

- Use the `nottingham-city-council` registry record and its fixed route.
- Static extraction may be incomplete; use rendered/current results.
- Preserve the current Oracle job ID and use the registry's individual-route pattern when available.
- The public requisition endpoint may be used as an optional efficiency mechanism if useful, but the weekly run does not need to prove an API population count.

### 12.3 iTrent

- Use the exact employer record and WVID in the registry.
- WVID matters where employers share a host.
- Direct retrieval may return 403; rendered access or fresh exact-domain indexing is the normal fallback.
- Capture the current vacancy ID/individual href from the current source rather than guessing; use the registry's individual-route pattern where it supplies one.
- Ignore transient session parameters when a stable job-specific URL is available.

### 12.4 HealthJobsUK / Trac

- Use the exact employer collection from the relevant registry record.
- Filter by actual work base where a Trust advertises out-of-county roles.
- Open individual adverts for current status, any stated deadline, reference, site and duties.
- If a listed advert is expired, exclude the vacancy and continue.

### 12.5 University of Nottingham

Use the `university-of-nottingham` registry record and always open its
`fixed_route` directly. That record is the canonical all-vacancies surface and
the normal weekly starting point, not a category reconstruction or a generic
homepage. Use its `individual_route_pattern` for the source-exposed vacancy
links.

- Capture the visible current vacancy rows from that registry route.
- Exclude obvious Internal Only, non-employment studentships, China/Ningbo and clear non-Nottinghamshire jobs cheaply.
- Finish every retained candidate through its individual advert before closing the University of Nottingham source work unit.
- No weekly category/site rediscovery is needed.

### 12.6 Nottingham Trent University

Use the `nottingham-trent-university` registry record and start from its
`fixed_route` rather than the portal root. The final jobs surface is kept in
the registry so the weekly run does not need to infer a route from a redirect.

- Static zero is not authoritative when the rendered/current portal contains jobs.
- Use the rendered/current list and its normal Load More / page sequence, then capture the source-exposed Jobtrain IDs/links.
- Finish qualifying rows through the registry's individual-route pattern before closing the NTU source work unit.
- Do not investigate Jobtrain internals every week.

### 12.7 GOV.UK Teaching Vacancies

- Use the fixed Nottinghamshire query.
- Follow the normal `page=` sequence.
- Check the actual school address because results can include jobs “in or near” Nottinghamshire.
- Preserve and follow each individual `/jobs/<slug>` advert.
- Use a clearly better direct employer application destination only when the GOV.UK advert exposes it.

### 12.8 Nottingham CVS

- Start from the fixed jobs page.
- If direct retrieval fails, use a fresh indexed copy of that exact page.
- Follow onward current vacancy/employer links where available.
- Include paid in-scope VCSE jobs with a Nottinghamshire base while the current advert is live and accepting applications. A fixed deadline is not required.

---

## 13. Deduplication

The same vacancy may appear on more than one source.

Keep one row per distinct vacancy.

Strong duplicate signals include:

- same organisation + same advertised job/reference ID;
- same organisation + same title + same location + same closing date when one exists;
- same vacancy mirrored across an employer site, GOV.UK, NHS/Trac, TAL or another recruitment platform.

Prefer the strongest current source and best current individual `apply_url`.

Do not treat distinct vacancies as duplicates merely because they share a generic board URL.

If two adverts have the same title but different references, locations or materially separate adverts, retain them separately.

---

## 14. Canonical 16-column CSV

The final public file is `jobs.csv` with **exactly these 16 columns in this order**:

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

### Field rules

| Field | Rule |
|---|---|
| `organization` | Public-facing advertised employer, or host organisation where no distinct employer is stated. |
| `employer_type` | Exact controlled value: Council / NHS / Education / VCSE. |
| `job_title` | Preserve the source title accurately. |
| `job_area` | Controlled role-function classification from Section 9. |
| `location` | Most useful verified participant-facing work location wording. |
| `location_area` | Controlled Nottinghamshire area from Section 9. |
| `closing_date` | `YYYY-MM-DD` when the advert states a fixed deadline; otherwise blank. A blank value does not make a live vacancy ineligible. |
| `closing_time` | `HH:MM` when explicitly stated; otherwise blank. |
| `contract_type` | Controlled value from Section 9. |
| `work_pattern` | Controlled value from Section 9. |
| `salary` | Preserve useful advertised pay wording; do not invent or annualise unless the source does so. |
| `apply_url` | Best current participant-facing job-specific destination available through the normal source method. |
| `job_reference` | Advertised/public reference when provided; otherwise blank. Do not invent one. |
| `date_checked` | Common weekly update date in `YYYY-MM-DD`. |
| `source_url` | Strongest current verification/source page. |
| `job_summary` | Grounded concise role summary when available; blank only under the rules in Section 11. |

---

## 15. Participant-facing quality audit

Run this after all source work units are finished and the cross-source dataset is consolidated.

Record internally:

- total vacancy rows;
- job-specific `apply_url` count;
- shared/list/board `apply_url` count;
- non-blank `job_summary` count;
- blank `job_summary` count.

Then review only the exceptions:

1. Every shared/list/board `apply_url` must have a genuine source limitation. If the source exposed a job-specific route and it was simply not followed, return to that source and repair the row.
2. Every blank `job_summary` must reflect genuine detail unavailability/insufficiency. If an available individual advert was skipped, return to that source and complete the row.
3. If many rows from one source share its board URL even though that source normally exposes clickable adverts, treat that as an execution defect.
4. `source_url` may equal `apply_url` when the individual advert is also the verification source. Do not force them to differ.

There is no required percentage target. The audit exists to distinguish genuine source limitations from skipped normal work.

A blank `closing_date` is not a quality failure when the current advert genuinely has no fixed deadline. Do not manufacture a date or exclude the row to make the dataset look more complete.

---

## 16. Deterministic CSV validation

Validate the generated file rather than manually repairing it after
serialization. Keep the repository's mechanical safety gate separate from the
broader Playbook/editorial review; neither gate should be described as proving
the other.

### 16.1 Repository structural/security validator

Execute `py -m scripts.validate_job_update jobs.csv` against the **exact final
`jobs.csv` candidate** that will be committed/pushed. The current repository
validator proves only:

- valid UTF-8 and well-formed CSV structure;
- the supported 15-/16-column header and field-count contract;
- a nonblank HTTP(S) `apply_url` for each row; and
- complete-file reading with deterministic row-count and checksum reporting.

It does **not** mechanically prove `date_checked` consistency, canonical dates,
closing-time format or expiry relation, controlled classifications, required
editorial fields or `source_url`, duplicate rules, summary wording or
normalisation, or deterministic sort. Do not report any of those broader checks
as enforced by the repository validator, and do not broaden that validator as
part of a weekly run.

### 16.2 Playbook/editorial/data-quality review

Separately apply the full Playbook checks to the exact candidate:

- one consistent `date_checked`;
- canonical `YYYY-MM-DD` dates;
- blank or valid `HH:MM` closing times;
- when `closing_date` is non-blank, require `closing_date >= date_checked`; blank is valid for a live vacancy with no fixed stated deadline;
- controlled enum values and required fields, including a strong current `source_url`;
- duplicate rules;
- normalised single-paragraph `job_summary` when non-blank; and
- deterministic sort: organisation A–Z, dated vacancies by closing date earliest first, undated/rolling vacancies after dated vacancies, then job title A–Z.

Do not report validation as passed because the validator code was inspected or
because the CSV appears valid manually. Report the repository gate as passed
only after the exact candidate validation actually succeeds, and report the
editorial/data-quality review separately. Neither gate proves recruitment-
platform completeness or replaces the participant-facing quality audit.

---

## 17. Publication workflow

A weekly publication is based on the usefulness and trustworthiness of the verified dataset, not on a completeness score for every recruitment platform.

A blocked or partly accessible source should be reported briefly as a limitation but does not automatically block publication of other verified current jobs.

Do not publish rows whose own required facts are uncertain or stale.

Normal repository path:

> **finished rows → validated 16-column `jobs.csv` → dated update branch → one-file pull request → Anthony review/merge → public verification**

For a normal weekly update:

- change `jobs.csv` only;
- do not edit website code, styling, workflow or configuration;
- record update date and row count;
- run the repository validator against the exact candidate;
- open the update PR;
- do not merge without Anthony's explicit approval;
- after Anthony merges, verify the public CSV/website reflects the new dataset when asked/authorised by the current workflow.

Hold publication for a genuine dataset/publication problem, such as:

- invalid CSV structure;
- stale or unverified rows;
- material generic board `apply_url`s caused by skipped available click-through;
- blank summaries caused by skipped available advert reading;
- material broken required URLs;
- repository validation failure;
- explicit Anthony decision that a known gap is too material.

Do not hold publication merely because recruitment-platform completeness cannot be mathematically proven.

---

## 18. Method maintenance is separate

When a fixed route stops working:

1. try the registry's one simple fallback;
2. finish the rows that normal method can support;
3. close the source with the access limitation recorded briefly;
4. continue the weekly run;
5. if the route genuinely changed or the problem repeats, handle it as a separate method-maintenance task.

Do not spend the normal weekly run reverse-engineering recruitment systems, chasing backend totals or exhausting multiple fallback ladders.

### Current narrow maintenance items

The following may need one-time technical confirmation outside the normal weekly run:

- Ashfield iTrent — confirm a current individual advert route/pattern;
- Mansfield iTrent — confirm a current individual advert route/pattern;
- Newark & Sherwood iTrent — confirm a current individual advert route/pattern;
- West Nottinghamshire College iTrent — confirm a current individual advert route/pattern.

Known operational behaviours already sufficient for weekly work include:

- `nottinghamshire-tal`: use the registry's stable board identity and registered exact-domain fallback; rendered session tokens are disposable;
- Bassetlaw and RNN iTrent: use the registry WVID and individual-route pattern;
- `nottingham-city-council`: use the registry site and individual-route pattern; API remains optional;
- `nottingham-trent-university`: a static zero is not authoritative;
- `nottingham-cvs`: use the registry fixed page and registered indexed-copy fallback.

---

## 19. Weekly boundaries

Do not:

- rediscover the 19 known recruitment sites each week;
- build a large unfinished cross-source candidate backlog;
- move to the next source while qualifying rows from the current source remain unfinished without a genuine limitation;
- treat source-total reconciliation as the purpose of the update;
- chase historical vacancy counts;
- require a backend/API count before processing genuine visible jobs;
- withhold verified rows because other jobs might exist on the same platform;
- use broad ranked web search instead of the known official source;
- run open-ended crawler/source-discovery work;
- exhaust multiple fallback ladders for one source;
- carry previous-week rows forward without fresh verification;
- infer mandatory facts from titles/employer names;
- search the web solely to fill a blank `job_summary`;
- let optional supplements turn the run into an indefinite market search.

---

## 20. Weekly completion definition

A normal Weekly Job Update is complete when:

- all 19 fixed sources have been visited using their registry routes;
- each source was handled as one work unit and marked finished before moving on;
- the registered simple fallback was used where needed;
- the current candidates exposed through those normal routes were considered;
- every included vacancy passed the row-level eligibility rules;
- live rolling/open-until-filled/no-deadline vacancies were retained when otherwise eligible;
- source-exposed individual adverts/job-specific routes were retained and followed where the normal method allowed;
- shared/list/board `apply_url`s remaining in the dataset reflect genuine source limitations;
- successfully read adverts with useful duties contain grounded `job_summary`s;
- blank summaries reflect genuine detail limitations;
- classifications are consistent;
- duplicates are removed;
- the exact 16-column schema is used;
- the participant-facing quality audit is complete;
- the repository validator was actually executed against the exact final candidate and passed;
- material source limitations are reported briefly;
- the candidate is ready for the normal one-file PR path.

The final question is:

> **Have we finished the strongest useful, trustworthy current Nottinghamshire job list we can from the fixed known sources this week?**

Not:

> **Have we proved every recruitment platform is technically complete?**
