# Production power and test sizing

The production contract in `geotestlab/power/production/` accepts the canonical
regional KPI dataset and an explicit `ProductionPowerConfig`. The current
config names the metric, regions, historical period, planned test dates, target
effects, frequency, simulation method, fit method, effect direction and
approved simulation settings.

There is an active prospective-horizon gap: current production execution still
uses source-available test dates as the analytical window. Planned campaign
dates, planned duration and the historical calibration/holdout horizon must be
separated before a genuinely future test is presented as supported. The
historical horizon must remain auditable and must not be labelled as the actual
campaign period.

The result includes power curves, target-power estimates, conditional
Clopper–Pearson intervals, MDE, requested and effective test periods, fit and
safety diagnostics, support status, warnings, blockers and input fingerprints.
There is no implicit best method. A result can be complete but unsupported or
stale, in which case it is not recommendation-usable.

Power is statistical detectability, not expected KPI response. Media delivery
and effectiveness evidence are separate contracts. The effect direction is
preserved: a one-sided positive MDE comparison does not treat an equal-sized
negative effect as meeting the target.

The scenario engine can build candidate shares and durations using historical
KPI volume, explicit population weights or custom regional weights. It retains
region constraints and never substitutes region count for market share. The
current backend scenario path is not yet a complete matched-and-validated
candidate pipeline; the Power UI still exposes selected-design execution.

The approved methodology and evidence gate are recorded in
[ADR-000](../product/decisions/ADR-000-power-methodology-approval-gate.md).
Open product decisions remain pending in the relevant ADRs.
