# GeoTestLab

Build statistically balanced test and control groups for geo-testing — no coding required.

## Current status

`geotestmatch.py` remains the Streamlit application entry point. Data ingestion
(`geotestlab/data/`) and matching (`geotestlab/matching/`) have been extracted
into Streamlit-free, typed packages; validation and Bayesian logic remain
substantially within the application script and are scheduled for later
behaviour-preserving extraction.

The canonical product requirements live under `docs/product/`:
`01_GeoTestLab_Core_Product_Requirements_Document.md` defines the target
product, `02_Power_Analysis_and_Test_Sizing_Specification.md` defines the
planned prospective power capability, and
`03_PRD_Traceability_and_Delivery_Roadmap.md` reconciles current, partially
implemented and planned work.

## Requirements

- **Python 3.11 only** (3.12+ is not supported yet)

## Quick start (runtime)

```bash
# 1. Create a Python 3.11 virtual environment
python3.11 -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows

# 2. Install runtime dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 3. Run the app
streamlit run geotestmatch.py
```

## Quick start (development)

```bash
# 1. Create a Python 3.11 virtual environment
python3.11 -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows

# 2. Install all dependencies (runtime + test + lint tools)
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt

# 3. Verify
ruff format --check .
ruff check .
pytest --cov=geotestlab --cov-report=term-missing --cov-fail-under=90 -q -m "not slow"
```

The app automatically loads the bundled workbook from:
`data/Population Stats for Geo Tests - Master Sheet Only v2 (Standardised).xlsx`

## Workflow

The current UI has four tabs:

1. **⚙️ Region Matching** — Select test geographies and match control regions using structural (demographic) similarity or KPI-pattern similarity.
2. **🔍 Validate Test Design** — Validate a proposed test design against historical KPI data using regularised regression and rolling-origin cross-validation.
3. **📊 Measure Test Impact** — Evaluate a completed test and estimate uplift.
4. **🧠 Bayesian TBR** — Estimate impact using Bayesian Time-Based Regression with MCMC diagnostics.

The target product model (see
`docs/product/01_GeoTestLab_Core_Product_Requirements_Document.md`) defines
**five stages**:
define and match regions; validate the design; size and power the test;
measure completed-test impact; and Bayesian analysis and reporting.
Prospective power analysis and test sizing are **planned, not yet
implemented** — the current empirical power preview is not the approved
product capability.

## Dependency management

Canonical lock platform: Linux, Python 3.11.

`requirements.txt` and `requirements-dev.txt` are release and CI locks generated
on Linux Python 3.11. Windows development is supported, but strict byte-for-byte
Windows transitive dependency locking is not currently promised.

Runtime dependencies are declared in `pyproject.toml` (loose version ranges) and pinned into lock files:

```bash
# Regenerate runtime lock file (Python 3.11 only)
python -m piptools compile --extra=bayesian --strip-extras --annotation-style=line --no-emit-index-url --no-emit-options --no-emit-trusted-host --output-file=requirements.txt pyproject.toml

# Regenerate dev lock file (Python 3.11 only)
python -m piptools compile --extra=bayesian --extra=dev --strip-extras --annotation-style=line --no-emit-index-url --no-emit-options --no-emit-trusted-host --output-file=requirements-dev.txt pyproject.toml
```

**Important**: Always regenerate lock files in a clean Linux Python 3.11 environment (matching CI). Do not edit `requirements.txt` or `requirements-dev.txt` by hand.

## Lint and test

```bash
ruff format --check .
ruff check .
pytest --cov=geotestlab --cov-report=term-missing --cov-fail-under=90 -q -m "not slow"
pytest tests/test_numerical_characterisation.py -q -m slow
python scripts/compile_requirements.py --check
```

## Coding agents

Coding agents (LLM assistants and MCP-driven tooling) working in this
repository must follow the local-storage (D-drive) policy, the MCP tool-use
policy, and the remaining repository rules defined in `AGENTS.md`.

## Architecture

The application entry point is `geotestmatch.py` (Streamlit). It calls into the
`geotestlab/` package for extracted behaviour while validation, reporting and
Bayesian logic remain substantially in the application script. The package is
being split out of the application incrementally, one behaviour-preserving
stage at a time:

- `geotestlab/data/` — ingestion, data-quality contract, region mapping, period-quality reports. (Stages 1–2)
- `geotestlab/matching/` — the pure matching core (Stage 4): no Streamlit imports, unit-tested directly.
  - `models.py` — immutable typed objects (`MatchConfig`, `FeatureWeightConfig`, `MatchConstraints`, `MatchDiagnostics`, `MatchResult`) and shared column constants.
  - `structural.py` — structural feature preparation (market-dataframe cleaning, weighted aggregation, median imputation).
  - `metrics.py` — population-weighted profiles, SMD, Weighted Structural Distance, the vectorised scorer, and NN pre-processing.
  - `kpi_pattern.py` — KPI-pattern feature preparation (index-to-100 pattern distance).
  - `constraints.py` — guided 'Set Rules & Auto-Build Groups' search + conflict validation.
  - `strategies.py` — Basic (Greedy Nearest Neighbor), Intermediate (Hill Climbing), Advanced (Stochastic Genetic Search).
- `geotestlab/validation/`, `geotestlab/modelling/`, `geotestlab/reporting/`, `geotestlab/ui/` — target subpackages (not yet extracted); validation and Bayesian logic currently live in `geotestmatch.py`.

The Streamlit app keeps `@st.cache_data` wrappers around the pure package functions (aggregation, metric caching, KPI workbook parsing, NN pre-processing) so caching behaviour is unchanged. Numerical characterisation goldens (`tests/test_numerical_characterisation.py`) guard that every extraction is behaviour-preserving.

## Methodology caveat

This is a specialised geo-testing tool for experienced practitioners. Understand the methodology before relying on results. See `docs/methodology.md` (forthcoming) for details.

## Licence

Licensing is undecided. See discussion in PR #1.

## Product documentation

- [GeoTestLab Core Product Requirements Document](docs/product/01_GeoTestLab_Core_Product_Requirements_Document.md)
- [Power Analysis and Test Sizing Specification](docs/product/02_Power_Analysis_and_Test_Sizing_Specification.md)
- [PRD Traceability and Delivery Roadmap](docs/product/03_PRD_Traceability_and_Delivery_Roadmap.md)
