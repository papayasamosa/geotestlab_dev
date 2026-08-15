# Evaluate a completed test

## Before evaluation

Open the experiment record and compare the planned design with the executed
periods and regions. A frozen design is the reference for planned-versus-
analysed comparison. If inputs changed, resolve the stale stage before
interpreting a downstream result.

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
fingerprints, frozen versions, planned-versus-analysed comparison and unified
result summaries. These include validation, impact, power, media delivery,
effect plausibility and design recommendation data where available.

Keep the export with the source-data identity and the methodology version. Do
not treat a JSON export as approval: approval and design freeze remain explicit
workflow actions.
