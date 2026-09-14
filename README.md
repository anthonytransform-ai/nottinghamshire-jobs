# Nottinghamshire Job Opportunities

Static public vacancy list for Transform Training. The site uses plain HTML, CSS and JavaScript and loads the replaceable `jobs.csv` file directly in the browser. It covers vacancies from local councils, NHS organisations, universities, schools, academy trusts, charities and voluntary/community organisations. It is also installable as a network-only web app on supported browsers; no service worker or offline cache is used.

## Weekly update

Normal Job Updates are prepared and audited outside the public site, then proposed through a dated one-file pull request. Do not manually append to `jobs.csv` and do not publish a routine Job Update directly to `main`.

Publication flow:

1. Produce the final verified CSV using the exact contract below.
2. Validate the structured dataset, row count, 56-day rule, duplicates and required sort order.
3. Calculate SHA-256 for the exact final CSV bytes.
4. Read the current `main` commit SHA.
5. Create a branch from that exact `main`, normally `job-update/YYYY-MM-DD`.
6. Replace the complete branch copy of `jobs.csv` with the audited CSV as one UTF-8 file.
7. Open a PR to `main`. A normal Job Update PR must change only `jobs.csv`.
8. The `Validate jobs CSV PR` workflow runs the validator and tests, confirms the one-file diff, and reports date checked, row count and SHA-256.
9. Anthony reviews the PR and uses **Squash and merge** when approved.
10. GitHub Pages deploys the new `main` commit. Verify the merged file, deployment and public CSV before considering the update complete.

The PR validation workflow is read-only: it never writes to `main` and never merges a PR.

## CSV contract

The columns must remain in this exact order:

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

The browser parser supports quoted values and commas inside fields. `closing_date` and `date_checked` use `YYYY-MM-DD`; `closing_time` uses `HH:MM` when present. Closing deadlines are evaluated in `Europe/London`, including same-day closing times, without changing the stored CSV value.

The `employer_type` field accepts these values:

- Council
- NHS
- VCSE
- Education

The validator also enforces the controlled values for job area, location area, contract type and work pattern defined by the Job Update project.

## Validation

Run the standard-library test suite with:

```powershell
py -m unittest discover -s tests -v
```

Validate a complete candidate CSV with:

```powershell
py scripts/validate_job_update.py jobs.csv --date-checked 2026-09-14
```

For a same-day Job Update candidate, use:

```powershell
py scripts/validate_job_update.py jobs.csv --require-today
```

The validator checks the exact schema/order, update-date consistency, row count, SHA-256, enums, dates/times, inclusive 56-day rule, required fields, HTTP(S) URLs, duplicate keys and required sort order. `--require-today` also rejects a stale update date and an explicit same-day deadline that has already passed in `Europe/London`.

The validator reads the complete `jobs.csv` directly. It does not reconstruct data from chunks and it does not publish or transform the file.

## Pull request rule

A routine Job Update should use a branch such as:

```text
job-update/2026-09-14
```

The final PR should contain exactly one changed file:

```text
jobs.csv
```

The PR description should include the date checked, eligible row count, closing-date window, candidate commit SHA, SHA-256, validation result, and any important partially verified or blocked mandatory sources.

If `main` changes while a candidate is being prepared, refresh or recreate the candidate from current `main` and validate again. Do not overwrite `main` to bypass the PR review gate.

## Merge and deployment

Anthony remains the publication gate. The recommended merge method for a Job Update PR is **Squash and merge**, so each published update appears as one clear commit on `main`.

After merge:

1. record the new `main` commit SHA;
2. confirm `main/jobs.csv` matches the audited candidate;
3. confirm its SHA-256 and row count;
4. confirm the GitHub Pages deployment for that exact `main` commit succeeds;
5. verify the public `jobs.csv` with cache bypassing where necessary;
6. verify public row count, update date and checksum when the endpoint can be independently retrieved.

Only after those checks should the online list be described as updated.

## Deprecated staging workflow

The earlier publication mechanism based on `job-update-staging`, Base64 `.job-update/chunk-*.b64` files and `job-update-manifest.json` is retired for normal Job Updates.

The repository no longer needs a manifest-triggered workflow that writes directly to `main`, nor the preparation helper used to create staging chunks. If a future file-size or connector limitation genuinely makes whole-file PR publication impractical, assess a new design explicitly rather than silently restoring the staging mechanism.

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

The public page includes the Cloudflare Web Analytics beacon in `index.html`. It provides lightweight page-view and visitor metrics in the Cloudflare dashboard without adding a visible counter to the site.

Analytics is independent of the vacancy-data publication pipeline. Normal weekly Job Updates should continue to replace only `jobs.csv`; the analytics beacon and token should not be changed as part of routine vacancy updates.

## Included files

- `index.html` — accessible page structure and code-native controls.
- `styles.css` — centralised Transform Training-inspired visual tokens and responsive layout.
- `app.js` — CSV parsing, Europe/London expiry handling, filtering, sorting, states and rendering.
- `jobs.csv` — current audited vacancy source.
- `logo_wbg.jpg` — supplied Transform Training logo used in the header.
- `manifest.webmanifest` — install name, standalone display settings and app metadata.
- `icons/` — Android, desktop and iPhone Home Screen icons derived from the supplied logo.
- `.github/workflows/validate-jobs-pr.yml` — read-only PR validation gate for routine Job Updates.
- `scripts/validate_job_update.py` — deterministic fail-closed whole-file CSV validator.
- `tests/` — standard-library validator regression tests.
