# State and fingerprints

An `ExperimentRecord` identifies a workflow session and stores stage statuses,
result fingerprints, stale flags, frozen versions, notes and an input summary.
The current stage keys are matching, counterfactual validation, statistical
power, media delivery, effect plausibility and observed impact.

Each analytical contract hashes the inputs that materially define its result.
On rerun, current fingerprints are compared with the stored result identity:

- equal fingerprints keep a completed stage current;
- changed current inputs mark an existing result stale;
- a new successful result replaces the stored result fingerprint;
- cleared or missing current evidence cannot fall back to an older result.

Recommendation fingerprints additionally include candidate rows, the explicit
objective and override rationale. Export fingerprints are audit identities, not
secrets or source-data substitutes.
