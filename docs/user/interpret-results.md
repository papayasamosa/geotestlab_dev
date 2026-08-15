# Interpret results safely

GeoTestLab intentionally answers several different questions. Read the
individual statuses before reading the recommendation.

| Question | Evidence | What it does not prove |
|---|---|---|
| Are regions comparable? | Match diagnostics and constraints | That the test has enough power |
| Is the counterfactual credible? | Rolling validation, placebo and confidence diagnostics | That media caused an effect |
| Is the design detectable? | Production power, target power and MDE | That the effect will occur |
| Can media deliver? | Budget, CPM, reach, frequency and thresholds | Incremental KPI response |
| Is an effect plausible? | Dated evidence bridge and low/central/high scenarios | Certainty of the realised effect |
| Which design should be chosen? | All gates plus the selected objective | Permission to ignore a failed gate |

## Recommendation statuses

- **Recommended** means all required gates pass under the selected objective.
- **Conditional** means the selected design has a recorded condition, such as
  an assumption-based effect bridge or an analyst override.
- **No qualifying design** means every candidate has at least one limiting
  factor. Fix the named factor or document a deliberate override.
- **Incomplete** means required candidate evidence is missing.

Unknown, stale, blocked and not-feasible results must not be silently promoted
to pass. A high expected uplift cannot rescue weak counterfactual validation;
reach or frequency cannot establish incremental KPI impact.

## Staleness

Changing KPI data, regions, dates, power settings, delivery inputs, evidence,
candidate rows or the recommendation objective can make a result stale. Re-run
the affected stage and then re-run the recommendation. The experiment record
keeps the stale marker and original fingerprint for auditability.
