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

Runtime dependencies are declared in `pyproject.toml` (loose version ranges) and pinned into lock files:

```bash
# Regenerate runtime lock file (Python 3.11 only)
python -m piptools compile --extra=bayesian --strip-extras --annotation-style=line --no-emit-index-url --no-emit-options --no-emit-trusted-host --output-file=requirements.txt pyproject.toml

# Regenerate dev lock file (Python 3.11 only)
python -m piptools compile --extra=bayesian --extra=dev --strip-extras --annotation-style=line --no-emit-index-url --no-emit-options --no-emit-trusted-host --output-file=requirements-dev.txt pyproject.toml
```

**Important**: Always regenerate lock files in a clean Python 3.11 environment. Do not edit `requirements.txt` or `requirements-dev.txt` by hand.

## Lint and test

```bash
ruff format --check .    # Check formatting
ruff check .             # Lint
pytest -q -m "not slow"  # Fast tests (excludes Bayesian sampling)
pytest --cov=.           # With coverage
```

## Architecture

The application is currently monolithic (`geotestmatch.py`). The `utils/` package was removed in `fix/baseline-safety-net` as it was stale code not imported by the live application.

Target architecture (in progress): `src/geotestlab/` package with `data/`, `matching/`, `modelling/`, `reporting/`, and `ui/` subpackages.

## Methodology caveat

This is a specialised geo-testing tool for experienced practitioners. Understand the methodology before relying on results. See `docs/methodology.md` (forthcoming) for details.

## Licence

Licensing is undecided. See discussion in PR #1.
