# AGENTS.md

Instructions for coding agents (Claude Code, Codex, Cursor, or any other MCP-capable
client) working in this repository.

## MCP tool-use policy

- Use GitHub MCP to inspect the current repository, recent changes, pull requests,
  issues, and CI before repository-wide work. Treat GitHub writes as
  approval-required actions.
- Use Context7 before changing code that depends on third-party APIs. Match
  documentation to the version declared or locked by this repository.
- Use Playwright MCP for user-facing Streamlit interaction and accessibility checks
  after unit tests and Streamlit AppTest. Do not use browser checks as a substitute
  for numerical regression tests.
- Use Hugging Face MCP only for tasks that explicitly involve Hugging Face models,
  datasets, repositories, papers, or Spaces.
- Never include credentials in source files, prompts committed to the repository,
  logs, tests, issues, or pull requests.
- If an MCP result conflicts with repository code, tests, locked versions, or
  primary documentation, investigate the conflict rather than silently accepting
  the MCP result.
- Record which MCP sources materially informed a code change in the pull-request
  description.

## Local storage policy (D-drive rule)

- All newly created local environments and caches must use `D:` — never `C:`.
- Playwright browser storage must use `PLAYWRIGHT_BROWSERS_PATH` on `D:`.
- Hugging Face storage must use `HF_HOME` on `D:`.
- npm and pip caches must use `D:` (`npm_config_cache`, `PIP_CACHE_DIR`).
- No new system-wide installations; use session-scoped environment variables.
- Existing tools may be used from their current location, but new installs must
  not target `C:`.
- Do not commit machine-specific absolute repository paths or usernames.

Before changing matching, time-series validation, placebo, uplift, or Bayesian
behaviour, inspect the current implementation and numerical-characterisation
tests. MCP tools provide context and operational access; they do not override the
repository's regression baselines or methodological approval process.

See [docs/development/mcp-tooling.md](docs/development/mcp-tooling.md) for setup,
authentication, verification, and troubleshooting of the four MCP development
servers (GitHub, Context7, Playwright, Hugging Face) used with this repository.
