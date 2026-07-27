# GeoTestLab

Build statistically balanced test and control groups for geo-testing — no coding required.

## Current status

Monolithic Streamlit application undergoing modular refactoring. The production source of truth is `geotestmatch.py`.

## Requirements

- **Python 3.11 only** (3.12+ is not supported yet)

## Quick start

```bash
# 1. Create a Python 3.11 virtual environment
python3.11 -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows

# 2. Install dependencies
pip install -r requirements-dev.txt
pip install -e . --no-deps

# 3. Run the app
streamlit run geotestmatch.py
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
# Regenerate runtime lock file
pip-compile --output-file=requirements.txt pyproject.toml

# Regenerate dev lock file
pip-compile --extra=dev --output-file=requirements-dev.txt pyproject.toml
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
