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

## Executable collection and representative weekly path

Before opening any source work unit, read the bounded mechanical access recipe
or assessment for its registry source or family in
`scripts/collector-access-recipes.md` when one exists. This applies to both
deterministic adapters and intentionally agent-assisted sources. The recipes
reference registry IDs; `references/source-registry.json` remains the sole
route/fallback owner. Changed markup or access needs targeted diagnosis, not
repeated portal rediscovery.

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
py -X utf8 -m scripts.collect_weekly_jobs --source govuk-teaching-vacancies --run RUN_NAME
py -X utf8 -m scripts.collect_weekly_jobs --source nottingham-city-council --run RUN_NAME --browser-channel msedge
py -X utf8 -m scripts.collect_weekly_jobs --source SOURCE_ID --run RUN_NAME --browser-channel msedge
```

The final generic command is used once for each exact registry record whose
method is `itrent`; it loads that record's WVID from the canonical JSON and
must not be replaced with another employer's ID. The same one-command-per-ID
rule applies to every supported source; never merge employers merely because
they share a recruitment host.

The deterministic collector currently covers the established University,
Jobtrain and HealthJobsUK family methods plus `govuk-teaching-vacancies`, the
`oracle-cloud` Nottingham City source and every registered `itrent` source.
These are adapter families, not a second source registry. Iterate the JSON
registry in listed order at orchestration/judgement level and use the source ID
from the current record for each invocation. The normal weekly boundary still
requires finishing one source before the next.

Any registry method not covered by those deterministic adapters remains
agent-assisted. First apply any settled source-access recipe or assessment;
then use the current Playbook and that record's registered route and simple
fallback. This includes `tal`, `council-direct`, `healthjobsuk-trac` records
without a deterministic completion proof, `college-direct` and `vcse-direct`
records. A human-verification response is a source limitation, never an EMPTY
result; record PARTIAL/ERROR and continue under Playbook rules. If behaviour
has changed, perform only bounded diagnosis. If the known boundary is still
present, retain the limitation and do not rediscover or bypass it. In
particular, the current Nottinghamshire TAL Altcha behaviour remains
agent-assisted and must not trigger a CAPTCHA, proxy or stealth workaround.

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

### Historical ANT-259 controlled integration shadow (reference only)

Anthony's explicit ANT-259 pilot boundary permits retaining today's trusted
non-pilot rows and replacing only the three freshly collected and judged pilot
portions. This helper is historical comparison evidence, not the normal
ANT-260 full-run path and does not constitute a fresh 19-source sweep.
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

### ANT-260 representative full-run proof

After the deterministic adapters are integrated, a representative acceptance
run uses a fresh ignored run directory and one common Europe/London
`date_checked`. Iterate all 19 current registry records in order. For each
source, complete one Source Work Unit before moving on:

1. invoke the deterministic adapter when the registry method is covered above;
2. otherwise use the current Playbook/registered agent-assisted method;
3. record the actual source status (`OK`, `EMPTY`, `PARTIAL` or `ERROR`),
   candidate count, judged include/exclude counts and material limitation;
4. finish every retained candidate into the one shared 16-column judgement
   path, including the participant-facing `apply_url` and grounded summary
   audit; and
5. close the source before opening the next one.

For the six iTrent records, run each exact source ID separately and retain the
actual WVID, rendered count, candidate/detail count and any limitation in the
run manifest. Ashfield's family proof does not substitute for the other five
configured weekly sources.

The full-run candidate and evidence are local and ignored. The candidate must
be serialized as exactly the Playbook's 16 columns, reviewed with the
participant-facing exception audit, and validated by the repository validator
against those exact bytes. Record the candidate row count and SHA-256, source
outcomes, job-specific versus shared destinations, summary exceptions,
cross-source deduplication, meaningful retries/manual navigation/intervention,
resumability evidence, and the comparison with the current trusted workflow.
Do not replace root `jobs.csv`, open a routine publication PR, or describe the
full-run candidate as production adoption.

If a deterministic source returns blocked, incomplete or detail-failure
evidence, preserve its useful candidates and limitation as PARTIAL/ERROR; do
not turn the failure into EMPTY or silently fall back to a different source.
If an agent-assisted source cannot be completed through the current registered
route/fallback, record that fact and continue the remaining fixed sources.

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
