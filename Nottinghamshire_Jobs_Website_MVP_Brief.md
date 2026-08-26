# Nottinghamshire Job Opportunities — MVP Product & Design Brief

**Organisation:** Transform Training  
**Project:** Job Update public website  
**Version:** MVP / V1  
**Primary audience:** Job seekers and Transform Training service users in Nottinghamshire  
**Publication model:** Static public website powered by a replaceable `jobs.csv` file  
**Hosting target:** GitHub Pages  
**Technology:** Plain HTML, CSS and JavaScript. No framework, backend, database, login or AI.

---

# 1. Product Goal

Create a very simple public webpage where job seekers can quickly find current paid vacancies in Nottinghamshire without scrolling through a long newsletter list.

The website becomes the main public vacancy list.

Transform Training's newsletter should only need to tell users that the job list has been updated and provide the permanent website link.

The site must be:

- easy for service users to search and filter;
- clear on desktop and mobile;
- fast to load;
- accessible;
- simple to maintain;
- easy to update weekly by replacing one CSV file;
- independent of AI at browsing time;
- independent of any database or server-side application.

---

# 2. Core Publishing Workflow

The weekly workflow should be:

1. Run the Job Update research process.
2. Produce a verified website-ready `jobs.csv`.
3. Replace the existing `jobs.csv` in the GitHub repository.
4. Commit/publish the change.
5. GitHub Pages automatically serves the updated vacancy list at the same permanent URL.

The website code should not need editing during a normal weekly update.

---

# 3. Technical Architecture

Use only:

- `index.html`
- `styles.css`
- `app.js`
- `jobs.csv`
- `README.md`

Recommended repository structure:

```text
nottinghamshire-jobs/
├── index.html
├── styles.css
├── app.js
├── jobs.csv
└── README.md
```

Do not introduce:

- React;
- Vue;
- Angular;
- npm/pnpm/yarn;
- a bundler;
- a database;
- Firebase/Supabase;
- authentication;
- serverless functions;
- an AI API;
- analytics unless added later by explicit request.

All filtering and sorting should happen client-side in the browser.

---

# 4. Website Data Contract

Load vacancy data from `jobs.csv`.

Use these columns in exactly this order:

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

## Controlled values

### employer_type

Use only:

- Council
- NHS
- VCSE

### job_area

Use exactly one of:

- Administration & Business Support
- Care & Support
- Children & Young People
- Community & Outreach
- Customer Service
- Education & Training
- Finance & Procurement
- Health & Clinical
- HR & People
- Housing & Homelessness
- IT & Digital
- Legal & Governance
- Management & Leadership
- Planning, Environment & Regulatory
- Property, Facilities & Operations
- Transport & Driving
- Leisure, Sport & Culture
- Other

### location_area

Use only:

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

### contract_type

Use only:

- Permanent
- Fixed-term
- Temporary
- Apprenticeship
- Bank/Casual/Sessional
- Freelance
- Other

### work_pattern

Use only:

- Full-time
- Part-time
- Full-time or Part-time
- Variable/Sessional
- Not stated

### dates

`closing_date` and `date_checked` use:

```text
YYYY-MM-DD
```

`closing_time` uses:

```text
HH:MM
```

only when explicitly supplied. It may otherwise be blank.

---

# 5. Automatic Expiry Behaviour

The website must automatically hide a vacancy after its closing deadline.

Rules:

1. If `closing_date` is earlier than today's date in Europe/London, do not display the vacancy.
2. If `closing_date` is today and `closing_time` is present, hide it after that time.
3. If `closing_date` is today and `closing_time` is blank, keep it visible for the whole date.
4. Never alter or infer the stored closing date/time.
5. Automatic expiry is a display behaviour only; `jobs.csv` remains the source dataset until the next weekly replacement.

---

# 6. Main User Experience

The first screen should make the purpose immediately clear.

Suggested content hierarchy:

## Header

**Transform Training**

Optional small secondary text:

**Nottinghamshire Job Opportunities**

Do not create a complex navigation menu for V1.

## Main heading

**Find current jobs in Nottinghamshire**

Supporting text:

> Search current paid vacancies from local councils, NHS organisations, charities and voluntary/community organisations.

Show:

- **Last checked:** derived from the newest `date_checked` value in the dataset.
- **Current vacancies:** calculated number of jobs currently visible after expiry filtering.

## Search and filters

Provide:

1. **Keyword search**
2. **Job Area**
3. **Organisation**
4. **Location**
5. **Sort**

Default sort:

**Closing soonest**

Users should be able to combine filters.

Example:

```text
[ Search job title or keyword...                  ]

[ Job area: All ▼ ] [ Organisation: All ▼ ] [ Location: All ▼ ]

72 jobs found                             [ Sort: Closing soonest ▼ ]
```

Include a clear **Reset filters** action whenever any filter/search is active.

---

# 7. Search Behaviour

The keyword search should be case-insensitive.

Search at least:

- `job_title`
- `organization`
- `job_area`
- `location`

Search should update results immediately as the user types.

No submit button is required.

---

# 8. Filters

## Job Area

Populate dynamically from the actual dataset.

Default:

**All job areas**

## Organisation

Populate dynamically from the actual dataset.

Default:

**All organisations**

Sort organisations alphabetically.

## Location

Use `location_area`.

Default:

**All locations**

Do not expose raw internal source fields as filters.

---

# 9. Sorting

Provide:

- Closing soonest
- Organisation A–Z
- Job title A–Z

Optional if straightforward:

- Closing latest

Do not include "Newest added" in V1 because the current dataset does not include a verified first-added date.

---

# 10. Vacancy Presentation

## Desktop

Use a clean list/table hybrid.

Do not display all 15 CSV fields.

Primary visible information:

- Job title
- Organisation
- Job area
- Location
- Closing date
- Salary
- Contract/work pattern
- View & Apply button

Suggested row structure:

```text
JOB TITLE
Organisation
Job Area

Location                    Contract / Work pattern
Salary                      Closing date

                                         [ View & Apply ]
```

Avoid a dense spreadsheet appearance.

## Mobile

Switch naturally to stacked vacancy cards/list items.

Do not require horizontal scrolling.

Each result should remain easy to scan.

Suggested order:

1. Job title
2. Organisation
3. Job area
4. Location
5. Salary
6. Contract/work pattern
7. Closing date
8. View & Apply

---

# 11. Apply Action

Every vacancy must have a clear:

**View & Apply**

button/link.

It must use `apply_url`.

Open the official vacancy/advert page.

Use a normal hyperlink that remains usable with keyboard navigation.

If `apply_url` is missing, the vacancy should not normally be present because the Job Update workflow requires an official current advert/application URL.

---

# 12. Closing Date Presentation

Display dates in UK-readable format:

```text
3 Sep 2026
```

If an explicit closing time exists:

```text
3 Sep 2026, 12:00
```

Add a simple derived urgency label where useful:

- **Closes today**
- **Closes tomorrow**
- **Closes in 2 days**

Do not overuse colours or warning styling.

The actual closing date must always remain visible.

---

# 13. Empty and Error States

## No matching jobs

Show:

**No jobs match these filters.**

Supporting text:

> Try changing or clearing one of your filters.

Provide:

**Reset filters**

## CSV cannot be loaded

Show a clear service-user-safe message:

**The job list is temporarily unavailable. Please try again later.**

Do not expose JavaScript errors, file paths or technical details.

## No current vacancies

If the CSV loads but all vacancies have expired:

**There are currently no vacancies in the list. Please check again after the next update.**

---

# 14. Introductory Guidance

Include a short information panel beneath or near the heading:

> This job list is updated regularly by Transform Training. Vacancies can close early or be withdrawn, so always check the employer's official advert before applying.

Do not expose:

- Job Search Playbook;
- APIs;
- recruitment-system mechanics;
- completeness audits;
- internal research methods.

---

# 15. Footer

Keep minimal.

Suggested:

**Transform Training — Nottinghamshire Job Opportunities**

Then:

> Job information is provided to help job seekers discover opportunities. Always check the employer's official advert for current details before applying.

No account/login links.

---

# 16. Visual Direction

The site should feel:

- trustworthy;
- calm;
- practical;
- welcoming;
- modern but not "techy";
- designed for public/community service use rather than a commercial recruitment platform.

Avoid:

- dashboard aesthetics;
- gradients for decoration;
- glassmorphism;
- excessive rounded cards;
- bright status badges everywhere;
- animations that distract;
- AI-style visual motifs;
- oversized hero sections;
- stock photographs;
- illustrations unless later requested.

Use generous whitespace and strong typography.

The vacancy content should be the visual priority.

---

# 17. Design System

Keep styling centralised in CSS variables so the whole site can later be rebranded easily.

At minimum define tokens for:

```css
:root {
  --color-background: ...;
  --color-surface: ...;
  --color-text: ...;
  --color-text-muted: ...;
  --color-border: ...;
  --color-primary: ...;
  --color-primary-hover: ...;
  --color-focus: ...;

  --font-family: ...;

  --space-1: ...;
  --space-2: ...;
  --space-3: ...;
  --space-4: ...;
  --space-5: ...;
  --space-6: ...;

  --radius-small: ...;
  --radius-medium: ...;

  --content-width: ...;
}
```

Repeated controls and vacancy rows/cards should use shared CSS classes rather than one-off styles.

Do not invent a Transform Training logo. If no official logo asset is supplied, use text branding only.

---

# 18. Accessibility

Target WCAG 2.2 AA good practice.

Requirements:

- semantic HTML;
- one clear H1;
- proper labels for all search/filter controls;
- visible keyboard focus;
- sufficient colour contrast;
- no information conveyed by colour alone;
- buttons/links with clear accessible names;
- logical keyboard order;
- responsive text without clipping;
- no horizontal scrolling on normal mobile widths;
- tap targets large enough for mobile use;
- native select controls are acceptable and preferred for simplicity.

Use an ARIA live region for the changing result count if appropriate.

Respect `prefers-reduced-motion`.

---

# 19. Responsive Behaviour

Test at minimum:

- 1440px desktop
- 1024px laptop/tablet landscape
- 768px tablet
- 390px mobile

On narrower screens:

- stack search/filter controls;
- avoid tiny columns;
- convert results to vertical list/card presentation;
- keep View & Apply prominent;
- maintain readable type sizes;
- never require sideways scrolling.

---

# 20. Performance

The dataset is expected to contain tens or low hundreds of vacancies.

Load the entire CSV once and handle it client-side.

Do not add pagination in V1 unless real testing shows it is needed.

Filtering/searching should feel immediate.

No large JavaScript libraries are needed.

---

# 21. CSV Parsing

Implement robust CSV parsing.

The data may contain:

- commas in salary text;
- commas in job titles;
- ampersands;
- apostrophes;
- quoted values;
- blank optional fields.

Do not parse CSV by simply splitting each row on commas.

Either:

- implement standards-compliant CSV parsing in the project; or
- use one very small, well-established browser-safe CSV parser only if genuinely necessary.

Prefer zero dependencies where practical.

---

# 22. Date and Time Handling

Expiry behaviour must use the **Europe/London** timezone rather than the visitor's timezone.

This matters when a user accesses the site from outside the UK.

Do not treat a UK closing deadline as midnight in the user's local timezone.

Use explicit logic for:

- closing date only;
- closing date + closing time;
- daylight-saving changes.

---

# 23. Privacy and Security

The site collects no personal data.

V1 must have:

- no account;
- no form submission;
- no CV upload;
- no cookies required by application functionality;
- no tracking scripts;
- no AI;
- no personalisation.

External application links should use safe link attributes where appropriate.

---

# 24. GitHub Pages Deployment

Configure the repository so it can be published directly through GitHub Pages.

Preferred outcome:

```text
https://<account-or-organisation>.github.io/nottinghamshire-jobs/
```

The repository should contain a short README explaining:

1. how to replace `jobs.csv`;
2. how to commit the update;
3. how to confirm the live site updated;
4. that the CSV column names/order must not be changed;
5. how to test the page locally if needed.

Do not require a build/deploy command for normal updates.

A custom Transform Training domain/subdomain can be added later.

---

# 25. Weekly Update Experience

The normal administrator task must be:

**Replace one file: `jobs.csv`.**

Nothing else.

The page should automatically derive:

- current vacancy count;
- filter options;
- organisation list;
- job-area list;
- locations;
- last checked date;
- expiry visibility.

Do not hard-code those values into HTML.

---

# 26. V1 Non-Goals

Do not build:

- user accounts;
- saved jobs;
- favourites;
- application tracking;
- email alerts;
- notifications;
- AI matching;
- CV analysis;
- CV upload;
- employer accounts;
- employer submissions;
- salary sliders;
- maps;
- location radius search;
- complex pagination;
- admin dashboard;
- CMS;
- database;
- API backend.

These may be considered only after real user feedback.

---

# 27. Required Test Data

Before deployment, test using a realistic `jobs.csv` containing enough rows to cover:

- Council, NHS and VCSE employers;
- several job areas;
- several Nottinghamshire locations;
- permanent, fixed-term and sessional/freelance work;
- full-time and part-time roles;
- salary ranges containing commas;
- a vacancy closing today with a time;
- a vacancy closing today without a time;
- a vacancy closing tomorrow;
- an already expired vacancy that must be hidden;
- blank optional values;
- long NHS/council job titles;
- duplicate-looking titles with different references.

Do not publish fake sample vacancies to the final public site.

---

# 28. Functional Acceptance Criteria

The MVP is complete only when all of these work:

- [ ] Page loads directly from GitHub Pages.
- [ ] `jobs.csv` loads successfully.
- [ ] Expired jobs are automatically hidden.
- [ ] UK closing times are handled in Europe/London.
- [ ] Keyword search works immediately.
- [ ] Job Area filter works.
- [ ] Organisation filter works.
- [ ] Location filter works.
- [ ] Filters can be combined.
- [ ] Reset filters works.
- [ ] Result count updates correctly.
- [ ] Closing-soonest is the default sort.
- [ ] Organisation A–Z sorting works.
- [ ] Job title A–Z sorting works.
- [ ] Apply links use the correct `apply_url`.
- [ ] Last checked date is derived from CSV data.
- [ ] Desktop presentation is easy to scan.
- [ ] Mobile presentation requires no horizontal scrolling.
- [ ] Empty-search state is clear.
- [ ] CSV-load failure state is clear.
- [ ] Keyboard navigation works.
- [ ] Focus states are visible.
- [ ] No user data is collected.
- [ ] No AI or backend service is required.
- [ ] Replacing only `jobs.csv` updates the next publication.

---

# 29. Visual Acceptance Criteria

The design should pass these checks:

- [ ] Vacancy results, not decoration, dominate the page.
- [ ] Search and filters are immediately discoverable.
- [ ] Closing dates are easy to notice.
- [ ] Job title has the strongest hierarchy within a result.
- [ ] Organisation and location are easy to scan.
- [ ] Apply action is visually clear but not oversized.
- [ ] Mobile cards remain compact enough to browse many jobs.
- [ ] Typography remains readable at 200% zoom.
- [ ] No generic commercial job-board clutter.
- [ ] No AI-style decorative UI.
- [ ] Design tokens are centralised and easy to rebrand later.

---

# 30. Browser QA

Before handoff:

1. Test the site with a local server.
2. Test filtering, search, sorting and reset behaviour.
3. Test all empty/error states.
4. Test desktop and mobile layouts.
5. Verify keyboard-only navigation.
6. Verify a sample of official application links.
7. Verify expired vacancies are removed from view.
8. Verify same-day closing-time behaviour.
9. Verify the page works after replacing `jobs.csv` with a second test dataset.
10. Verify GitHub Pages production deployment.

---

# 31. Deliverables

The implementation should deliver:

```text
index.html
styles.css
app.js
jobs.csv
README.md
```

Also provide:

- deployed GitHub Pages URL;
- repository URL;
- one desktop screenshot;
- one mobile screenshot;
- confirmation that the weekly update requires replacing only `jobs.csv`;
- any material limitations discovered during implementation.

---

# 32. MVP Success Definition

The MVP succeeds when a service user can open one permanent link, find a suitable Nottinghamshire vacancy within seconds using search/filters, see the key information, and go directly to the employer's official advert.

It also succeeds when Transform Training can publish the next weekly update by replacing one CSV file without editing website code.
