# PR #5 agent-first architecture inventory

Checkpoint reviewed: 97f98daafe662e31176bfe6fa03386f1d394d946

The weekly workflow now treats Codex as the source-research and semantic
verification layer. Repository code receives a dated, structured source
evidence document and performs deterministic validation, eligibility,
deduplication, audit and CSV publication preparation. It does not attempt to
discover changing recruitment-site DOMs on behalf of the weekly operator.

## KEEP

| Module or contract | Decision |
| --- | --- |
| RawVacancy, SourceResult, NormalizedVacancy | Keep as the stable evidence-to-publication data contracts; add explicit agent-supplied semantic fields. |
| eligibility.py | Keep the hard Nottinghamshire, host/service, employment, deadline and current-status policy. |
| dedupe.py | Keep deterministic reference-first and factual-fallback deduplication. |
| normalise.py, csv_writer.py | Keep the exact public CSV contract and normalisation boundary. |
| audit.py | Keep the per-source audit ledger, completeness reconciliation and anomaly reporting. |
| review.py, configuration.py | Keep optional run-local exception resolution, with dates, references and live status remaining source-owned. |
| scripts/validate_job_update.py | Keep the existing fail-closed whole-file validator unchanged in purpose. |
| config/job_sources.toml, Playbook source knowledge | Keep every mandatory source, but describe it for the agent rather than for a parser factory. |
| job_update/adapters/oracle_hcm.py | Keep as the one stable collector: the public Oracle requisition endpoint exposes structured records and TotalJobsCount. |
| http_client.py, a small adapter protocol/common helper | Keep only to support the Oracle collector and deterministic fixture tests. |
| .github/workflows/validate-engine.yml | Keep and retarget it to the structured-ingestion/build contracts. |
| The static public site and one-file/manual-squash publication gate | Keep unchanged. |

## REMOVE

| Module or contract | Reason |
| --- | --- |
| browser.py | A generic autonomous browser framework duplicates Codex navigation and encourages brittle DOM assumptions. |
| direct_council.py, gedling.py, itrent.py | Mutable council and iTrent HTML/DOM parsers are not stable weekly infrastructure. |
| tal.py | TAL anti-bot, board variants and changing routes are agent research concerns. |
| nhs.py | NHS employer search and underlying Trac/HealthJobsUK/NHS Jobs selection require current reasoning, not a generic HTML parser. |
| teaching_vacancies.py | Pagination, address verification and current detail pages are agent-researched evidence. |
| ntu_jobtrain.py, university_nottingham.py | Recruitment-site DOM and detail behaviour are mutable and not proven stable collectors. |
| academy_trust.py, nottingham_cvs.py | Trust/VCSE routes and source-specific detail pages are current source-research work. |
| Obsolete parser-only fixtures and parser-specific tests | They encode the architecture being removed rather than the supported weekly contract. |

## REDUCE

| Module or contract | Reduction |
| --- | --- |
| registry.py | Load source identity, Playbook notes, expected host/service, completeness evidence and optional stable collector metadata; no mandatory adapter mapping. |
| pipeline.py | Build from source_results.json without network access; expose stable collection only as an explicit optional operation. |
| cli.py | Make ingest and build the normal path; keep collect explicit for retained collectors; make doctor local-only by default. |
| classify.py | Validate exact controlled enums and retain only obvious fallback mappings. Agent-supplied job_area and location_area are preferred when evidenced. |
| adapters/base.py, adapters/common.py, html_tools.py | Keep only the small protocol/helpers needed by Oracle and tests. |
| requirements-job-update.txt | Remove Playwright; retain only stable-collector HTTP support and timezone data. |
| README and tests | Document and verify structured agent ingestion rather than website parser behaviour. |

## Resulting workflow

1. Codex reads the current Playbook and registry and researches every mandatory
   source afresh.
2. Codex writes source_results.json for the dated run using the documented
   schema, including source status, completeness evidence, factual fields,
   semantic enum decisions and provenance.
3. py -m job_update ingest validates the complete mandatory-source document.
4. py -m job_update build performs deterministic policy, deduplication, audit,
   review-queue, CSV and whole-file validation work without network access.
5. Codex resolves only genuine evidence conflicts or ambiguous records, then
   rebuilds from the same source evidence.
6. The final candidate is reviewed and published through the existing one-file
   jobs.csv PR and Anthony's manual Squash and merge gate.

Firecrawl and runtime OpenAI API calls remain outside the repository.
