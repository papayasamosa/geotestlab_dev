# Release readiness and operating boundary

This document is the release checklist for the current GeoTestLab repository.
It describes what is implemented, what can be reproduced from source, and
which decisions remain with the owner. It does not grant a software licence or
turn the application into a hosted multi-user service.

## Current release posture

The application is suitable for controlled local analyst use when the analyst
can review the methodology, source-data handling and exported record. It is not
currently presented as a production SaaS or a regulated system. The visible
application name is now `GeoTestLab`; the temporary `TEST` prefix has been
removed as part of this deliberate release-readiness pass.

The implemented first-release surface is intentionally bounded:

- prospective planning covers matching, validation, production power/test
  sizing, Meta delivery feasibility, effect plausibility and typed design
  recommendation;
- completed-test evaluation and Bayesian TBR remain available as separate
  evaluation stages;
- Meta is the only registered media platform profile; broader platform
  profiles are future work;
- evidence-quality policy and the objective/policy decisions called out by the
  product ADRs remain explicit gates, rather than being silently inferred.

## Versioning and reproducible builds

- The package version is currently `0.1.0` in `pyproject.toml`.
- Frozen design records and exports obtain their tool version from installed
  package metadata through `geotestlab.experiment.version.tool_version()`.
- Python 3.11 is the supported runtime (`runtime.txt` and `pyproject.toml`).
- `requirements.txt` and `requirements-dev.txt` are Python-3.11
  `pip-compile` locks. The CI lock-verification job must pass before merging.
- There is no release tag in the repository yet. For a formal release, bump
  `pyproject.toml`, regenerate both lock files with the repository compile
  script, run the full CI gate, and create an annotated `vX.Y.Z` tag pointing
  to the merged commit. The exported tool version and tag must agree.

No methodology version, evidence-suite version, numerical golden or seed may
be changed as part of a packaging-only release. A methodology change requires
the relevant approval and regression evidence described by the product ADRs.

## Deployment boundary

Run the application from the repository root with Python 3.11:

```text
streamlit run geotestmatch.py
```

The default geography workbook is the committed file under `data/`. A
deployment may point to a different compatible workbook with
`GEOTESTLAB_DATA_PATH`; that workbook is an input dependency and must be
versioned and controlled by the deployment owner. The runtime and dependency
locks should be used as the build inputs. Never put credentials, API keys or
private connection strings in source, lock files, prompts, exports or logs.

Before a hosted deployment, the owner must decide how authentication,
networking, secrets, file isolation, backups, retention and concurrent users
will be handled. Those controls are outside the current repository contract.

## Persistence and reload expectations

The application state is held in the Streamlit session. The experiment-record
export is a local JSON handoff containing identity, fingerprints, stage status,
reproducibility metadata, frozen design versions and compact stakeholder and
technical summaries. It does not embed raw KPI observations or source
workbooks. A later session can load that JSON, but source files must be
supplied again before analyses are recomputed.

There is no central database, account-level storage, automatic backup,
multi-user merge or durable server-side audit trail. Treat downloaded records
and source workbooks as business-controlled files and store them only in an
approved location with the organisation's retention and access controls.

## Confidentiality and logging

Uploaded KPI workbooks, geography inputs and experiment exports may contain
confidential commercial information. Users should:

- keep raw workbooks and exported records out of Git, issue comments, pull
  requests and unapproved shared storage;
- inspect an export before sharing it, especially its labels, notes and
  summaries;
- avoid entering secrets or unnecessary personal/confidential data into
  analyst notes; and
- remember that a deployment platform may retain uploaded files or logs under
  its own policy, which must be reviewed separately.

The UI translates expected validation and input failures into actionable
warnings or errors and blocks unsafe downstream stages. This is a user-facing
error boundary, not a promise that every unexpected runtime failure is
recoverable. The application does not define a production logging, monitoring
or audit-trail policy; any deployment must ensure operational logs exclude raw
KPI values, uploaded file contents and credentials.

## Performance and assurance baseline

The repository's authoritative assurance is the GitHub CI suite: Ruff, lock
verification, unit/AppTest coverage, numerical characterisation and reduced
Bayesian sampling checks. The end-to-end prospective planning AppTest and its
adjacent suites are part of the regression surface. Local wall-clock timings
are diagnostic only and are not service-level objectives because they vary by
CPU, Python environment, workbook size and Streamlit cache state.

Before a release, record the CI run for the exact merge commit and confirm:

1. required checks are green;
2. numerical goldens and Bayesian smoke checks are unchanged unless an
   approved methodology change explains them;
3. the planning workflow AppTest completes from upload through freeze/export;
4. a local JSON export reloads with its source-data-missing state made explicit;
5. the supported Python and lock-file checks pass; and
6. a user-facing accessibility/responsive review is completed in an available
   browser test environment. Playwright MCP was unavailable during the current
   repository pass, so that last review is recorded as an explicit release
   follow-up rather than claimed as complete.

## Open owner decisions

These items are intentionally not guessed by a coding agent:

- choose and record the repository's software licence before redistribution;
- define the target deployment, authentication, persistence, retention and
  incident-response controls before hosted or multi-user use;
- resolve the product evidence-quality and objective/policy decisions tracked
  by the relevant ADRs; and
- decide whether additional media platform profiles are needed after the
  Meta-first release surface has been used.

## Release checklist

- [ ] Owner/legal licence decision recorded and the repository licence file
  added if redistribution is approved.
- [ ] Version bumped, lock files regenerated and an annotated `vX.Y.Z` tag
  created from the merged release commit.
- [ ] CI, numerical and Bayesian checks green for that commit.
- [ ] Deployment owner has approved secrets, file-retention, access and
  backup controls.
- [ ] Source workbook version and `GEOTESTLAB_DATA_PATH` (if used) recorded.
- [ ] Local export/reload and stale-input behavior verified with representative
  non-production data.
- [ ] Browser accessibility/responsive review completed and attached to the
  release record.
