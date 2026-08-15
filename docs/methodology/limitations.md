# Limitations and safety rules

- The production power contract is limited by historical length, data
  continuity, frequency support, fit diagnostics and simulation support status.
- Candidate scenario sizing cannot make an indivisible region or unavailable
  post-history date disappear.
- Media forecasts are platform- and scope-dependent. Supplied forecasts are
  not observations, and calculated delivery is not incrementality.
- Effect plausibility depends on the evidence bridge. Without one, spend
  sufficiency is unknown.
- Conditional and overridden recommendations require explicit review. The
  override reason is part of the export.
- The approved design freeze is a local workflow record, not a replacement for
  organisational approval controls or a central persistence service. Each
  approval is immutable and versioned, and later approvals create new versions.
- Local JSON export records package/dependency metadata and source/methodology
  identities. It remains a file-based hand-off; production persistence and
  multi-user access remain follow-on work.
- Bayesian CI sampling is a path smoke test, not a claim of production
  convergence.
- Licensing remains undecided.
