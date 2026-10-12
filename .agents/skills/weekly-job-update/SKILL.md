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
