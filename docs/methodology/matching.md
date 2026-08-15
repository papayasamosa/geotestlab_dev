# Matching methodology

GeoTestLab constructs test and control groups from the selected market and
geography level. Structural matching uses demographic/population features;
KPI-pattern matching uses indexed historical KPI shapes. The application keeps
the executed groups and matching inputs in the experiment record.

The matching diagnostics include weighted structural distance, standardised
mean differences, feature-level detail, population share and control-pool
information. Region constraints are explicit: force-includes, exclusions and
test/control-only rules are validated for contradictions.

Market share is based on the selected market-size measure and explicit weights,
not on the number of regions. Candidate scenario sizing therefore preserves
requested versus achieved share and indivisible-region limitations.

Matching quality is separate from counterfactual validation and power. A
balanced regional design is necessary but does not by itself establish a
credible historical counterfactual or a detectable effect.
