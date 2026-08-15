# Counterfactual validation methodology

Validation estimates how well control regions predict the test regions during
the pre-period. The current validation workflow runs Elastic Net for
structurally matched or user-selected controls and LASSO for data-optimised
controls. The separate production power contract supports explicit OLS,
Elastic Net and LASSO fit choices. Both workflows use frequency-aware inputs,
rolling-origin validation, placebo checks and diagnostic confidence ratings.

Review the primary out-of-sample error together with bias, overfitting,
autocorrelation and data sufficiency. Counterfactual Confidence is a documented
diagnostic hierarchy, not a composite recommendation score. A high expected
uplift cannot override weak validation.

Design-mode validation describes prospective credibility. Completed-test
evaluation is required before the observed-impact stage can be completed. The
application records historical/test periods, excluded periods, method results,
warnings and stage fingerprints.

## Minimum interpretation rule

Insufficient history, discontinuous dates, low KPI volume, unresolved mapping
errors and material missingness are limitations, not evidence of a good fit.
Improve the data, regions or period before making a formal recommendation.
