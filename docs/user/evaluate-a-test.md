# Evaluate a completed test

## Before evaluation

Open the experiment record and compare the planned design with the executed
periods and regions. A frozen design is the reference for planned-versus-
analysed comparison. In **Measure Test Impact**, use **Use active frozen design**
to load the active version's executed regions and planned periods as evaluation
defaults. If the current KPI source fingerprint differs, review it explicitly
before running the evaluation.

## Measure observed impact

Use **Measure Test Impact** with the completed-test dates and the selected
counterfactual method. Review actual versus counterfactual series, uplift,
uncertainty, validation diagnostics and blockers. A design-mode validation is
not an observed-impact result.

## Bayesian assurance

Use **Bayesian TBR** when the data and sampling profile support it. Review
convergence, effective sample size, divergences and the posterior predictive
interval. The reduced-sampling CI smoke job proves the execution path only; it
does not establish production MCMC assurance.

## Export the record

The experiment-record download contains the identity, stage statuses and
fingerprints, every frozen version, planned-versus-analysed comparison and
unified result summaries. Frozen versions include executed regions and metrics,
source and data-quality identities, power/support limitations, recommendation
evidence, approval metadata and package/dependency metadata. Media and effect
sections say `not_supplied` when no value was provided; they are never inferred
from spend or other unrelated inputs.

Keep the export with the source-data identity and the methodology version. Do
not treat a JSON export as approval: approval and design freeze remain explicit
workflow actions.
