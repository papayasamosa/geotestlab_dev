# GeoTestLab

Build statistically balanced test and control groups for geo-testing — no coding required.

## Current status

`geotestmatch.py` remains the Streamlit application entry point, but it now
keeps the UI and thin adapters; the domain logic lives in Streamlit-free, typed
packages under `geotestlab/`:

- `geotestlab/data/` — ingestion, data quality, region mapping, period quality.
- `geotestlab/matching/` — structural and KPI-pattern matching.
- `geotestlab/validation/` — counterfactual validation (model matrix,
  regularised models, rolling origin, placebo, Counterfactual Confidence).
- `geotestlab/bayesian/` — Bayesian TBR core (AR(1), priors, model, sampling
  service, diagnostics), with the PyMC trace kept separate from the
  serialisable result.
- `geotestlab/experiment/` — experiment identity, stage fingerprints,
  staleness, and immutable design-freeze foundations.
- `geotestlab/power/` — **an experimental evidence harness** for prospective
  power analysis; it remains separate from the production power engine.

Validation and Bayesian logic no longer live substantially in the application
script; they have been extracted into `geotestlab/validation/` and
`geotestlab/bayesian/`.

The canonical product requirements live under `docs/product/`: `PRD.md`
defines the target product, `power-analysis-and-test-sizing.md` defines the
planned prospective power capability, and `roadmap-and-traceability.md`
reconciles current, partially implemented and planned work.

## Requirements

- **Python 3.11 only** (3.12+ is not supported yet)

## Quick start (runtime)

```bash
# 1. Create a Python 3.11 virtual environment
python3.11 -m venv .venv
source .venv/bin/activate   # Linux/macOS

# 2. Install runtime dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 3. Run the app
streamlit run geotestmatch.py
```

**Windows (PowerShell).** Do not create the environment with a bare relative
`.venv` — on a shared or work-managed machine that silently lands on `C:` and
mixes with system state. Create it explicitly on a non-system drive instead
(adjust the drive letter if `D:` is unavailable on your machine):

```powershell
# 1. Create a Python 3.11 virtual environment on a non-system drive
py -3.11 -m venv D:\GeoTestLabDev\venvs\geotestlab
D:\GeoTestLabDev\venvs\geotestlab\Scripts\Activate.ps1

# Keep the pip cache off C: too
$env:PIP_CACHE_DIR = "D:\GeoTestLabDev\cache\pip"

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

# 2. Install all dependencies (runtime + test + lint tools)
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt

# 3. Verify
ruff format --check .
ruff check .
pytest --cov=geotestlab --cov-report=term-missing --cov-fail-under=90 -q -m "not slow"
```

**Windows (PowerShell).** Same non-system-drive rule as above:

```powershell
# 1. Create a Python 3.11 virtual environment on a non-system drive
py -3.11 -m venv D:\GeoTestLabDev\venvs\geotestlab
D:\GeoTestLabDev\venvs\geotestlab\Scripts\Activate.ps1
$env:PIP_CACHE_DIR = "D:\GeoTestLabDev\cache\pip"

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

The target product model (see `docs/product/PRD.md`) defines **five stages**:
define and match regions; validate the design; size and power the test;
measure completed-test impact; and Bayesian analysis and reporting.
Prospective power analysis and test sizing are **under production
implementation**; the current empirical power preview is not the production
power capability.

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
`geotestlab/` packages for extracted domain behaviour; the app script keeps
thin adapters (for example `run_validation_method` and the Bayesian run
handler) and the UI. The extraction is behaviour-preserving and one package at
a time:

- `geotestlab/data/` — ingestion, data-quality contract, region mapping, period-quality reports. (Stages 1–2)
- `geotestlab/matching/` — the pure matching core (Stage 4): no Streamlit imports, unit-tested directly.
  - `models.py` — immutable typed objects (`MatchConfig`, `FeatureWeightConfig`, `MatchConstraints`, `MatchDiagnostics`, `MatchResult`) and shared column constants.
  - `structural.py` — structural feature preparation (market-dataframe cleaning, weighted aggregation, median imputation).
  - `metrics.py` — population-weighted profiles, SMD, Weighted Structural Distance, the vectorised scorer, and NN pre-processing.
  - `kpi_pattern.py` — KPI-pattern feature preparation (index-to-100 pattern distance).
  - `constraints.py` — guided 'Set Rules & Auto-Build Groups' search + conflict validation.
  - `strategies.py` — Basic (Greedy Nearest Neighbor), Intermediate (Hill Climbing), Advanced (Stochastic Genetic Search).
- `geotestlab/validation/` — typed counterfactual validation: frequency config, model matrix, regularised models, rolling-origin validation, placebo, Counterfactual Confidence and the `run_validation` service.
- `geotestlab/bayesian/` — typed Bayesian TBR core: AR(1), priors, features, model construction, prediction, diagnostics and the `run_bayesian` service; the PyMC trace is kept separate from the serialisable `BayesianResult` summary.
- `geotestlab/experiment/` — experiment identity (`EXP-YYYYMMDD-XXXX`), deterministic stage fingerprints, stage-scoped staleness, immutable frozen design versions, and a local experiment-record export (foundations of FR-16 and FR-22, not the complete contracts).
- `geotestlab/power/` — **methodology evidence harness**: synthetic power cases,
  model-based counterfactual simulation, placebo/residual methods, MDE search
  and fit-method comparison evidence. The methodology pack is approved under
  ADR-000; this experimental harness is still not the production power engine
  (FR-10/FR-11).

The Streamlit app keeps `@st.cache_data` wrappers around the pure package functions (aggregation, metric caching, KPI workbook parsing, NN pre-processing) so caching behaviour is unchanged. Numerical characterisation goldens (`tests/test_numerical_characterisation.py`) guard that every extraction is behaviour-preserving.

## Methodology caveat

This is a specialised geo-testing tool for experienced practitioners. Understand the methodology before relying on results. See `docs/methodology.md` (forthcoming) for details.

## Licence

Licensing is undecided. See discussion in PR #1.

## Product documentation

- [GeoTestLab Core Product Requirements Document](docs/product/PRD.md)
- [Power Analysis and Test Sizing Specification](docs/product/power-analysis-and-test-sizing.md)
- [PRD Traceability and Delivery Roadmap](docs/product/roadmap-and-traceability.md)
