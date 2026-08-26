# Nottinghamshire Job Opportunities

Static public vacancy list for Transform Training. The site uses plain HTML, CSS and JavaScript and loads the replaceable `jobs.csv` file directly in the browser. It is also installable as a network-only web app on supported browsers; no service worker or offline cache is used.

## Weekly update

The normal update is to replace one file: `jobs.csv`.

1. Export or prepare a verified vacancy file using the exact header and column order already in `jobs.csv`.
2. Replace `jobs.csv` without changing the column names or order.
3. Commit and publish the file through the repository's normal GitHub Pages workflow.
4. Open the permanent site link, hard-refresh it, and confirm the new `Last checked`, vacancy count, filters and a sample of application links.

Only publish verified vacancies. The page has a safe no-current-vacancies state for weeks when the verified export contains no current vacancies.

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

## Run locally

Because browsers block `fetch()` from a `file://` page, use a small local static server:

```powershell
py -m http.server 8000
```

Then open <http://localhost:8000/>. No package manager, build step or runtime dependency is required.

## Install as a web app

The live HTTPS site includes `manifest.webmanifest` and branded square icons for installation from Android/desktop Chrome and iPhone Safari. The installed app always uses the network and requests the latest `jobs.csv`; this project deliberately has no service worker or offline behaviour.

## GitHub Pages

Set GitHub Pages to deploy from the repository's chosen branch and the repository root. The static files are already arranged for direct serving; normal weekly updates do not require a build or code change.

## Included files

- `index.html` — accessible page structure and code-native controls.
- `styles.css` — centralised Transform Training-inspired visual tokens and responsive layout.
- `app.js` — CSV parsing, Europe/London expiry handling, filtering, sorting, states and rendering.
- `jobs.csv` — weekly-updated vacancy source.
- `logo_wbg.jpg` — supplied Transform Training logo used in the header.
- `manifest.webmanifest` — install name, standalone display settings and app metadata.
- `icons/` — Android, desktop and iPhone Home Screen icons derived from the supplied logo.
