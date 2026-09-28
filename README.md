# Nottinghamshire Job Opportunities

Static public vacancy list for Transform Training. The site uses plain HTML, CSS and JavaScript and loads the replaceable `jobs.csv` file directly in the browser. It covers vacancies from local councils, NHS organisations, universities, schools, academy trusts, charities and voluntary/community organisations. It is also installable as a network-only web app on supported browsers; no service worker or offline cache is used.

## Weekly update

Normal Job Updates are prepared and audited outside the public site, then proposed through a dated one-file pull request. Do not manually append to `jobs.csv` and do not publish a routine Job Update directly to `main`.

Publication flow:

1. Produce the final verified CSV using the active public-feed contract and current Job Search Playbook.
2. Validate only the structural/security conditions required for the website to consume the file safely.
3. Calculate SHA-256 for the exact final CSV bytes.
4. Read the current `main` commit SHA.
5. Create a branch from that exact `main`, normally `job-update/YYYY-MM-DD`.
6. Replace the complete branch copy of `jobs.csv` with the audited CSV as one UTF-8 file.
7. Open a PR to `main`. A normal Job Update PR must change only `jobs.csv`.
8. The `Validate jobs CSV PR` workflow runs the validator and tests, confirms the one-file diff, and reports row count and SHA-256.
9. Anthony reviews the PR and uses **Squash and merge** when approved.
10. GitHub Pages deploys the new `main` commit. Verify the merged file, deployment and public CSV before considering the update complete.

The PR validation workflow is read-only: it never writes to `main` and never merges a PR.

Vacancy eligibility, source verification, classification, summaries, closing-date judgement and other editorial/data-quality decisions belong to the current Job Search Playbook and review process. The repository validator must not duplicate those policies in ways that can mechanically discard otherwise useful vacancies.

## `job_summary` schema migration

The repository supports a public `job_summary` field while retaining read compatibility with the earlier 15-column feed.

- `app.js` accepts both the legacy 15-column feed and the 16-column feed with `job_summary` appended. A legacy row is treated as `job_summary = ""`.
- The deterministic validator accepts either contract so historical/current source states remain readable during the transition.
- The validator does not require a summary value.
- No runtime AI, backend, database or authentication is introduced by this field.

## Public CSV contracts

### Legacy compatible contract

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
```

### 16-column contract

The new field is appended, not inserted between existing positional fields:

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

The browser parser supports quoted values and commas, quotation marks and line breaks inside quoted fields. A fixed `closing_date`, when known, normally uses `YYYY-MM-DD`; `closing_time`, when known for a fixed date, normally uses `HH:MM`. A missing or non-date closing value is treated by the website as **Closing date not stated** rather than removing the vacancy. Dated vacancies that are clearly past their stated deadline can still be hidden by the browser's current-vacancy presentation logic.

The Job Search Playbook may use consistent values for fields such as employer type, job area, location area, contract type and work pattern to improve filtering and usability. Those are editorial conventions, not mechanical CSV rejection rules.

### `job_summary` contract

`job_summary` is a discovery/orientation field: a concise factual explanation of what the person would mainly be doing in the role. The employer's official advert remains the authority for full and current vacancy detail.

- Target length: about 2–3 sentences / roughly 40–80 words when the source supports that amount of useful detail.
- Grounding: current official employer/recruitment content used during normal vacancy verification only; never infer duties from the job title alone.
- Exclude suitability/eligibility language, recommendations, participant-specific language, unsupported claims and long person-specification lists.
- The value may be blank when sufficient trustworthy current detail is unavailable.
- A blank summary must not remove an otherwise useful vacancy from publication.
- Do not start a second unbounded crawl, browser run or Firecrawl pass solely to fill missing summaries.

Summary wording/whitespace is not a repository validation gate. The browser escapes vacancy text before rendering, including summary content.

## Public feed contract

`jobs.csv` is also the public read-only discovery feed for approved consumers. Consumers should not treat it as a vacancy-history database.

- Each published file is a complete replacement of the current verified set, not an append-only history.
- `job_reference` is optional. When present it is useful source identity, but consumers must not assume every source provides one.
- `apply_url` is the intended primary public vacancy destination. It may point to an individual advert/application route or, where genuinely necessary, a shared employer recruitment/vacancies page used by several distinct jobs.
- Distinct jobs are allowed to share the same `apply_url`; consumers must not use that URL alone as vacancy identity.
- `source_url` is retained source information from the weekly verification process and may be blank, or the same as or different from `apply_url`.
- `job_summary` helps people understand the role before opening the advert; it is not a suitability decision, person specification or replacement for the official advert.
- `date_checked` can record when Transform verified a row for that weekly update. Missing or mixed values do not make the CSV unsafe to render and therefore are not validator failures.
- Missing source facts remain missing. Consumers must not invent references, deep links, requirements, deadlines or lifecycle state to fill gaps.
- Nottinghamshire Jobs is a public provider only. Participant-private profile, evidence, Match or application data must never be written to this repository or feed.

The public website uses the same link rule: if several current feed rows share one `apply_url`, the row remains visible but the action is labelled **Open vacancies page** and any available `job_reference` is shown as an additional lookup cue.

## Website behaviour for summaries and incomplete source facts

When `job_summary` is present, the vacancy card shows a **What you'd do** section beneath the role identity and before factual metadata. Blank summaries create no empty placeholder.

Keyword search includes `job_summary` together with title, organisation, job area and location fields.

The website deliberately tolerates missing nonessential vacancy facts. Existing fallbacks include **Untitled vacancy**, **Organisation not stated**, **Job area not stated**, **Location not stated**, **Work pattern not stated**, **Salary not stated** and **Closing date not stated**. Vacancies without a fixed closing date remain visible. For closing-date sorting, undated vacancies are placed after dated vacancies.

`apply_url` is different: a displayed vacancy needs a safe actionable destination. The validator and browser therefore continue to require/accept only HTTP(S) application destinations, and the browser rejects unsafe URL schemes before rendering an application link.

## Validation

Run the standard-library Python test suite with:

```powershell
py -m unittest discover -s tests -v
```

Run the browser/parser/link-policy regression tests with Node's built-in test runner:

```powershell
node --test tests/job-link-policy.test.js
```

No package manager or third-party JavaScript test framework is required.

Validate a complete candidate with:

```powershell
py scripts/validate_job_update.py jobs.csv
```

The validator intentionally checks only conditions needed to prevent a broken or unsafe website feed:

- valid UTF-8;
- a supported exact 15- or 16-column header/order;
- well-formed CSV and the correct field count for each nonblank row;
- a nonblank HTTP(S) `apply_url` for each vacancy row;
- successful whole-file reading plus row count and SHA-256 reporting.

It deliberately does **not** reject rows because of blank optional fields, closing-date presence/format/age, closing time, `date_checked`, controlled classification values, duplicates, source URL, sort order, summary content/whitespace or similar editorial/data-quality rules. Those matters are governed by the current Job Search Playbook and participant-facing review rather than by a fail-closed mechanical gate.

The validator reads the complete `jobs.csv` directly. It does not reconstruct data from chunks and it does not publish or transform the file.

## Pull request rule

A routine Job Update should use a branch such as `job-update/2026-09-27`. The final weekly PR should contain exactly one changed file: `jobs.csv`.

A source/schema compatibility PR may change website source, tests, validator and documentation; it must not be presented as a weekly publication PR. Such a source PR should leave the public `jobs.csv` unchanged unless Anthony explicitly combines the work.

If `main` changes while a candidate is being prepared, refresh or recreate the candidate from current `main` and validate again. Do not overwrite `main` to bypass the PR review gate.

## Merge and deployment

Anthony remains the publication gate. The recommended merge method for a Job Update PR is **Squash and merge**, so each published update appears as one clear commit on `main`.

After merge:

1. record the new `main` commit SHA;
2. confirm `main/jobs.csv` matches the audited candidate;
3. confirm its SHA-256 and row count;
4. confirm the GitHub Pages deployment for that exact `main` commit succeeds;
5. verify the public `jobs.csv` with cache bypassing where necessary;
6. verify public row count and checksum when the endpoint can be independently retrieved.

Only after the relevant checks should the online list be described as updated.

## Deprecated staging workflow

The earlier publication mechanism based on `job-update-staging`, Base64 `.job-update/chunk-*.b64` files and `job-update-manifest.json` is retired for normal Job Updates. If a future file-size or connector limitation genuinely makes whole-file PR publication impractical, assess a new design explicitly rather than silently restoring the staging mechanism.

## Run locally

Because browsers block `fetch()` from a `file://` page, use a small local static server:

```powershell
py -m http.server 8000
```

Then open <http://localhost:8000/>. No package manager, build step or runtime dependency is required.

## Install as a web app

The live HTTPS site includes `manifest.webmanifest` and branded square icons for installation from Android/desktop Chrome and iPhone Safari. The installed app always uses the network and requests the latest `jobs.csv`; this project deliberately has no service worker or offline behaviour.

## GitHub Pages

GitHub Pages deploys the repository root from `main`. Normal weekly updates change only `jobs.csv`, so each approved update produces one public deployment after merge.

## Web analytics

The public page includes the Cloudflare Web Analytics beacon in `index.html`. It provides lightweight page-view and visitor metrics in the Cloudflare dashboard without adding a visible counter to the site. Analytics is independent of the vacancy-data publication pipeline and must not be changed as part of routine vacancy updates.

## Included files

- `index.html` — accessible page structure, guidance and code-native controls.
- `styles.css` — centralised Transform Training-inspired visual tokens and responsive vacancy-card layout.
- `app.js` — 15/16-column CSV parsing, summary search/rendering, Europe/London expiry handling, filtering, sorting, states and link behaviour.
- `jobs.csv` — current audited vacancy source.
- `logo_wbg.jpg` — supplied Transform Training logo used in the header.
- `manifest.webmanifest` — install name, standalone display settings and app metadata.
- `icons/` — Android, desktop and iPhone Home Screen icons derived from the supplied logo.
- `.github/workflows/validate-jobs-pr.yml` — read-only structural/security PR validation gate for routine Job Updates.
- `.github/workflows/validate-source-pr.yml` — source-change regression checks; it does not run for a routine `jobs.csv`-only Job Update.
- `scripts/validate_job_update.py` — whole-file structural/security validator.
- `tests/` — Python validator tests plus Node standard-library parser/search/render/link regression tests.
