---
name: weekly-job-update
description: Run the Workflow-First Nottinghamshire Jobs weekly update. Use for requests such as "Weekly Job Update", "update the Nottinghamshire Jobs list", or "generate the weekly jobs CSV". Routes fixed-source collection, row completion, quality audit, validation, and the bounded publication candidate.
---

# Weekly Job Update

This skill is the repo-local control surface for the Nottinghamshire Jobs weekly
workflow. It is discoverable for the established weekly trigger and for direct
requests to update the Nottinghamshire Jobs list or generate its weekly CSV.

## Read the detail only when needed

Before a weekly run, read these version-controlled references:

1. `references/source-registry.json` — the one canonical machine-readable list
   of the 19 fixed sources, their routes, source families, methods and registered
   fallbacks;
2. `references/playbook.md` — the accepted Workflow-First operating method,
   including eligibility, classification, row completion, quality audit and
   publication rules.

Do not maintain another hand-edited source registry in this Skill, `AGENTS.md`,
or a collector. Future deterministic collectors must load the JSON registry.
Human-readable source guidance may explain how to use the registry, but the JSON
entry owns source identity and fixed-route metadata.

The shared source-neutral contracts and resumable local state helpers are in
`scripts/weekly_job_update.py`. They use only the Python standard library.

## Workflow control

Follow the Playbook one source at a time:

1. create or resume the local run state under `.weekly-job-update/`;
2. open the current source through its registered route and only its registered
   simple fallback when needed;
3. capture source-exposed candidates and individual links as raw evidence;
4. finish or explicitly exclude each candidate before closing that source;
5. persist the source outcome, then move to the next fixed source;
6. consolidate completed rows, deduplicate, run the participant-facing quality
   audit, and validate the exact final CSV candidate;
7. prepare the normal bounded one-file publication candidate only after the
   previous gates pass.

The source lifecycle is explicit:

`NOT_STARTED → RUNNING → OK / EMPTY / PARTIAL / ERROR`

`EMPTY` means a normal collection completed successfully and exposed zero
candidates. A blocked, incomplete, or failed source is `PARTIAL` or `ERROR`,
never `EMPTY`.

Raw candidates preserve uncertain source text as evidence. Do not coerce an
uncertain value into a final Nottinghamshire Jobs classification. Collectors
may persist raw candidates, draft candidates and final candidate state through
the shared local state helper; no database or service is required.

## Executable collector pilot

Before using a pilot adapter, read the bounded mechanical access recipes in
`scripts/collector-access-recipes.md`. The recipes reference registry IDs;
`references/source-registry.json` remains the sole route/fallback owner. Changed
markup or access needs targeted diagnosis, not repeated portal rediscovery.

Collection tooling is separate from the public static site. Install the pinned
Python development dependency from `scripts/requirements-collection.txt` only
when it is missing. Use an installed ordinary browser channel where available
(e.g. `msedge` on Windows), or provision Playwright Chromium through its normal
installer. There is no crawler framework, database or service.

Run one registered source at a time into a named ignored working directory:

```text
py -X utf8 -m scripts.collect_weekly_jobs --source university-of-nottingham --run RUN_NAME
py -X utf8 -m scripts.collect_weekly_jobs --source nottingham-trent-university --run RUN_NAME --browser-channel msedge
py -X utf8 -m scripts.collect_weekly_jobs --source nottingham-university-hospitals --run RUN_NAME --browser-channel msedge --headed
```

Use the registry order at orchestration/judgement level. These command examples
show adapter invocation, not permission to collect several unfinished sources.
The normal weekly boundary still requires finishing one source before the next.

The collector emits the shared source-run record and raw candidates. Consume
`source-runs.json`, `raw-candidates.jsonl`, per-source checkpoints and captured
HTML evidence from `.weekly-job-update/RUN_NAME/`; do not recrawl completed list
pages to recreate facts already captured. Complete raw evidence stays raw:
apply current Playbook eligibility, work-base/host, classification, deduplication
and summary judgement. `OK` describes collection, not eligibility or publication.

Exit code 2 means PARTIAL/ERROR; read its method, counts and recorded failures.
Do not convert it to EMPTY. Verified rows may proceed with an explicit source
limitation. Same-run invocation skips an already completed source; a partial run
reuses completed details and completed enumeration checkpoints. Fresh weekly
work needs a fresh run name. `--stop-after N` is a controlled detail interruption
for failure/resume proof, not a weekly coverage limit. A hard-killed process may
leave RUNNING and a lock; check its recorded PID before removing a stale lock.

For row finishing, persist explicit decisions per captured identity with an
include/exclude outcome and reason. Included rows retain all 16 CSV string fields
and an explicit destination/summary exception assessment. The local helper in
`scripts/prepare_weekly_shadow.py` checks that no raw identity remains unfinished;
it does not make eligibility/classification/deduplication decisions for the agent.

### ANT-259 controlled integration shadow

Anthony's explicit pilot boundary permits retaining today's trusted non-pilot
rows and replacing only the three freshly collected and judged pilot portions.
Identify those portions by source/employer evidence, finish each pilot source's
`SOURCE_ID-decisions.json`, and use:

```text
py -X utf8 -m scripts.prepare_weekly_shadow --run RUN_NAME --checked-date YYYY-MM-DD
py -X utf8 -m scripts.validate_job_update .weekly-job-update/RUN_NAME/shadow-jobs.csv
```

Read the manifest, review/deduplicate the final rows and perform the participant
exception audit. The helper holds the trusted non-pilot fields constant and
reports inherited exceptions separately. Do not claim a fresh 19-source sweep,
newly verified non-pilot limitation reasons, or a production-ready public update
from this controlled comparison. Record exact row count/checksum, source
comparisons, controlled failure/resume evidence and remaining limitations.

The shadow CSV and live evidence remain ignored. Public `jobs.csv` is unchanged.
The current trusted production workflow remains active pending Anthony's later
adoption decision; a validated shadow candidate does not grant adoption or merge.

## Ownership and boundaries

- The current accepted Playbook owns weekly operating semantics and editorial
  judgement.
- The JSON registry owns fixed source identity, route and method metadata.
- Collectors are upstream evidence-gathering adapters. They do not own final
  eligibility, classification, `job_summary`, publication or merge authority.
- The repository validator remains the narrow structural/security consumer-safety
  gate. It is not a substitute for the Playbook's participant-facing audit.
- Host-specific differences are adapters/routing only; C and J use the same
  workflow and contracts.
- The final public contract remains the exact 16-column `jobs.csv`. Anthony
  retains merge/publication authority.

Temporary vacancy evidence and resumable run state stay local and untracked.
Do not switch the production weekly workflow, change `jobs.csv`, merge, deploy,
or broaden source discovery as part of using this Skill unless a separate
current instruction authorises that action.
