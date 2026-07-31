# GeoTestLab

Build statistically balanced test and control groups for geo-testing — no coding required.

## Current status

Monolithic Streamlit application undergoing modular refactoring. The production source of truth is `geotestmatch.py`.

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
ruff check .
pytest -q -m "not slow"
```

The app automatically loads the bundled workbook from:
`data/Population Stats for Geo Tests - Master Sheet Only v2 (Standardised).xlsx`

## Workflow

GeoTestLab supports a four-stage workflow through four tabs:

1. **⚙️ Region Matching** — Select test geographies and match control regions using structural (demographic) similarity or KPI-pattern similarity.
2. **🔍 Validate Test Design** — Validate a proposed test design against historical KPI data using regularised regression and rolling-origin cross-validation.
3. **📊 Measure Test Impact** — Evaluate a completed test and estimate uplift.
4. **🧠 Bayesian TBR** — Estimate impact using Bayesian Time-Based Regression with MCMC diagnostics.

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
ruff format --check .    # Check formatting
ruff check .             # Lint
pytest -q -m "not slow"  # Fast tests (excludes Bayesian sampling)
pytest --cov=.           # With coverage
```

## Architecture

The application entry point is `geotestmatch.py` (Streamlit), which acts as a thin adapter over the `geotestlab/` package. The package is being split out of the monolith incrementally, one behaviour-preserving stage at a time:

- `geotestlab/data/` — ingestion, data-quality contract, region mapping, period-quality reports. (Stages 1–2)
- `geotestlab/matching/` — the pure matching core (Stage 4): no Streamlit imports, unit-tested directly.
  - `models.py` — immutable typed objects (`MatchConfig`, `FeatureWeightConfig`, `MatchConstraints`, `MatchDiagnostics`, `MatchResult`) and shared column constants.
  - `structural.py` — structural feature preparation (market-dataframe cleaning, weighted aggregation, median imputation).
  - `metrics.py` — population-weighted profiles, SMD, Weighted Structural Distance, the vectorised scorer, and NN pre-processing.
  - `kpi_pattern.py` — KPI-pattern feature preparation (index-to-100 pattern distance).
  - `constraints.py` — guided 'Set Rules & Auto-Build Groups' search + conflict validation.
  - `strategies.py` — Basic (Greedy Nearest Neighbor), Intermediate (Hill Climbing), Advanced (Stochastic Genetic Search).
- `geotestlab/modelling/`, `geotestlab/reporting/`, `geotestlab/ui/` — target subpackages (not yet extracted).

The Streamlit app keeps `@st.cache_data` wrappers around the pure package functions (aggregation, metric caching, KPI workbook parsing, NN pre-processing) so caching behaviour is unchanged. Numerical characterisation goldens (`tests/test_numerical_characterisation.py`) guard that every extraction is behaviour-preserving.

## Methodology caveat

This is a specialised geo-testing tool for experienced practitioners. Understand the methodology before relying on results. See `docs/methodology.md` (forthcoming) for details.

## Licence

Licensing is undecided. See discussion in PR #1.
