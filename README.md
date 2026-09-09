# Nottinghamshire Job Opportunities

Static public vacancy list for Transform Training. The site uses plain HTML, CSS and JavaScript and loads the replaceable `jobs.csv` file directly in the browser. It covers vacancies from local councils, NHS organisations, universities, schools, academy trusts, charities and voluntary/community organisations. It is also installable as a network-only web app on supported browsers; no service worker or offline cache is used.

## Weekly update

Normal Job Updates are prepared and audited outside the public site, then published through the permanent staging workflow. Do not manually reconstruct or append to `jobs.csv` on `main`.

Publication flow:

1. Produce the final verified CSV using the exact contract below.
2. Validate the structured dataset, row count, 56-day rule, duplicates and required sort order.
3. Calculate SHA-256 for the exact final CSV bytes.
4. Read the current `main` commit SHA.
5. Prepare Base64 chunks on `job-update-staging` under `.job-update/`.
6. Update `job-update-manifest.json` **last**. Only this manifest change triggers publication.
7. The `Publish jobs CSV` workflow assembles and validates the exact bytes, verifies the expected `main` SHA, and replaces only `main/jobs.csv`.
8. The workflow then checks the published repository bytes, waits for the GitHub Pages deployment, and verifies the public `jobs.csv` checksum.

If any validation or deployment check fails, the workflow stops rather than bypassing the gate.

## Staging manifest

`job-update-manifest.json` exists only on the `job-update-staging` branch during an update. Its contract is documented by `job-update-manifest.example.json` on `main`:

```json
{
  "date_checked": "2026-09-07",
  "row_count": 233,
  "sha256": "<sha256-of-exact-csv-bytes>",
  "base_main_sha": "<main-sha-read-before-publication>",
  "chunks": [
    ".job-update/chunk-001.b64",
    ".job-update/chunk-002.b64"
  ]
}
```

The chunk list is authoritative. Old extra chunks on the staging branch are ignored when they are not listed in the current manifest.

### Preparing staging files locally

The helper is standard-library Python only:

```powershell
py scripts/prepare_job_update.py jobs.csv `
  --output-dir staging-payload `
  --date-checked 2026-09-07 `
  --base-main-sha <current-main-sha>
```

This preserves the exact input bytes, calculates SHA-256 and row count, and writes ordered Base64 chunks plus the manifest. Upload all chunks first and the manifest last.

The workflow independently revalidates everything; the preparation helper is not a substitute for the validation gate.

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

The publication validator also enforces the controlled values for job area, location area, contract type and work pattern defined by the Job Update project.

## Validation

Run the standard-library test suite with:

```powershell
py -m unittest discover -s tests -v
```

Validate a prepared staging payload with:

```powershell
py scripts/validate_job_update.py `
  --manifest staging-payload/job-update-manifest.json `
  --root staging-payload `
  --output validated-jobs.csv `
  --actual-main-sha <current-main-sha>
```

The validator checks the exact schema/order, SHA-256, row count, enums, dates/times, inclusive 56-day rule, required fields, HTTP(S) URLs, duplicate keys and required sort order. The publication workflow additionally uses `--require-today` and rejects a stale update date or an explicit same-day deadline that has already passed in Europe/London.

## Run locally

Because browsers block `fetch()` from a `file://` page, use a small local static server:

```powershell
py -m http.server 8000
```

Then open <http://localhost:8000/>. No package manager, build step or runtime dependency is required.

## Install as a web app

The live HTTPS site includes `manifest.webmanifest` and branded square icons for installation from Android/desktop Chrome and iPhone Safari. The installed app always uses the network and requests the latest `jobs.csv`; this project deliberately has no service worker or offline behaviour.

## GitHub Pages

GitHub Pages deploys the repository root from `main`. Normal weekly updates publish only `jobs.csv`; staging chunks never go to `main` and therefore do not cause repeated public deployments.

The publication workflow verifies both the successful Pages deployment for the new `main` commit and the SHA-256 of the public `jobs.csv` before the update is considered complete.

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
- `.github/workflows/publish-jobs.yml` — permanent staging, validation, publication and public-verification workflow.
- `scripts/prepare_job_update.py` — prepares exact-byte Base64 staging chunks and manifest.
- `scripts/validate_job_update.py` — deterministic fail-closed publication validator.
- `tests/` — standard-library validator/preparation regression tests.
- `job-update-manifest.example.json` — documented staging manifest contract.