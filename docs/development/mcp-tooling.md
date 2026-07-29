# MCP development tooling

This document describes the Model Context Protocol (MCP) servers configured for
coding agents working on GeoTestLab, why each one is included, and how to set
them up, verify them, and remove them.

## What MCP is, in practical terms

MCP (Model Context Protocol) is an open protocol that lets a coding client (an
AI assistant such as Claude Code, Codex, or Cursor) call out to external tools
and data sources — a repository host, a documentation index, a browser, a model
hub — instead of relying only on what is pasted into the conversation or on the
model's training data.

**MCP servers are development tools used by the coding client. They are not
dependencies of the deployed Streamlit application.** Nothing in
`geotestmatch.py`, `requirements.txt`, `requirements-dev.txt`, or
`pyproject.toml` starts, imports, or depends on any MCP server. The architecture
is:

```text
Coding client
  |
  +-- GitHub MCP        (repository/PR/CI context)
  +-- Context7 MCP      (version-aware library docs)
  +-- Playwright MCP    (live Streamlit UI checks)
  +-- Hugging Face MCP  (model/dataset/Space research)
  |
Local GeoTestLab repository
  |
  +-- Python application and tests remain independent
```

## Why each server is included

| Server | Priority | Used for |
|---|---|---|
| [GitHub MCP](https://github.com/github/github-mcp-server) | High | Reading branches, commits, PRs, issues, reviews, and CI status; comparing a change with `main`; investigating failed Actions runs. Writes (create PR/issue) only when explicitly requested; merges/deletes/admin actions are never automatic. |
| [Context7 MCP](https://github.com/upstash/context7) | High | Version-aware documentation for Streamlit, pandas, NumPy, scikit-learn, SciPy, PyMC, ArviZ, Altair, Plotly, openpyxl, python-calamine, pytest, Ruff, and any newly proposed library. This repo currently locks `streamlit==1.60.0`, `pandas==3.0.5`, `numpy==2.4.6` (see `requirements.txt`) — match Context7 queries to those versions. |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) | High for UI work | Driving the local Streamlit app as a user: the four-stage workflow, widget state after reruns, keyboard focus and accessible labels, result cards/warnings/exclusions/stale states, responsive layout and 200% zoom. Complements — never replaces — unit tests, numerical golden tests, and Streamlit `AppTest`. |
| [Hugging Face MCP](https://github.com/huggingface/hf-mcp-server) | Secondary, task-specific | Searching models/datasets/papers/Spaces only when a task explicitly involves one. Not used for routine Streamlit work, GitHub operations, or core statistical methodology decisions. |

Full GeoTestLab-specific usage rules live in [`AGENTS.md`](../../AGENTS.md).

## Prerequisites

| Requirement | Status on this machine (checked 2026-07-29) |
|---|---|
| Node.js ≥ 18 | v24.18.0 — OK |
| `npx` available | v11.16.0 — OK |
| Network access to `api.githubcopilot.com`, `mcp.context7.com`, `huggingface.co` | reachable — OK |
| `GITHUB_PAT_TOKEN` set | not set — required before GitHub MCP will authenticate |
| `CONTEXT7_API_KEY` set | not set — required before Context7 MCP will authenticate |
| `HF_TOKEN` set | not set — optional; unauthenticated Hub search works without it, but higher rate limits and private-resource access need it |

Re-run the checks above at any time with `scripts/check_mcp_prereqs.py` (see
[below](#prerequisite-checker)).

## Configuration

### Where the config lives

This repository ships a project-scoped [`.mcp.json`](../../.mcp.json) at the
repo root. Claude Code (and other MCP-aware clients that honor `.mcp.json`)
loads it automatically and merges it with any user-level servers you've
configured. It contains **no secrets** — only environment-variable references
(`${GITHUB_PAT_TOKEN}`, `${CONTEXT7_API_KEY}`, `${HF_TOKEN}`) that the client
substitutes at connection time. This is the officially documented pattern for
sharing MCP configuration across a team without checking in credentials.

Claude Code prompts for one-time approval before connecting to servers it reads
from a project's `.mcp.json` (`claude mcp list` shows them as
`⏸ Pending approval` until you run `claude` interactively and accept).

If you'd rather not share the server list via git, remove `.mcp.json` from your
checkout and add the same four servers at user scope instead (`--scope user`
in the commands below) — they will then apply across all your projects but stay
private to you.

### Claude Code (the client used to author this configuration)

The `claude` CLI is the source of truth; the commands below reproduce the
`.mcp.json` in this repo (or add the equivalent at user scope):

```bash
# Project scope (writes to ./.mcp.json — already done for this repo)
claude mcp add --transport http github https://api.githubcopilot.com/mcp/ \
  --header "Authorization: Bearer ${GITHUB_PAT_TOKEN}" --scope project

claude mcp add --transport http context7 https://mcp.context7.com/mcp \
  --header "CONTEXT7_API_KEY: ${CONTEXT7_API_KEY}" --scope project

claude mcp add --transport stdio playwright --scope project -- npx @playwright/mcp@latest

claude mcp add --transport http huggingface https://huggingface.co/mcp \
  --header "Authorization: Bearer ${HF_TOKEN}" --scope project
```

Verify and authenticate:

```bash
claude mcp list          # shows connection/approval status for all four
/mcp                     # inside a Claude Code session — approve, authenticate, inspect tools
```

GitHub, Context7, and Hugging Face support OAuth as an alternative to a static
token for servers that advertise it; run `/mcp` and follow the sign-in prompt
if you'd rather not manage a PAT/API key manually. Playwright runs as a local
`npx` process and needs no authentication.

> Pin the Playwright version once you've confirmed it works, e.g.
> `@playwright/mcp@0.x.y`, instead of `@latest`, if you want reproducible CI-like
> behaviour. Record the pinned version here when you do.

### Other clients (Codex, Cursor, VS Code)

If you use a different coding client against this repository, configure the
same four servers using that client's own MCP mechanism — do not copy another
client's config syntax verbatim.

- **Codex** — merge into `~/.codex/config.toml`:

  ```toml
  [mcp_servers.github]
  url = "https://api.githubcopilot.com/mcp/"
  bearer_token_env_var = "GITHUB_PAT_TOKEN"
  required = false

  [mcp_servers.context7]
  url = "https://mcp.context7.com/mcp"
  env_http_headers = { CONTEXT7_API_KEY = "CONTEXT7_API_KEY" }
  required = false

  [mcp_servers.playwright]
  command = "npx"
  args = ["@playwright/mcp@latest"]
  startup_timeout_sec = 30
  tool_timeout_sec = 120
  required = false

  [mcp_servers.huggingface]
  url = "https://huggingface.co/mcp"
  bearer_token_env_var = "HF_TOKEN"
  required = false
  ```

  See a secret-free copy of this block at
  [`mcp-config-examples/codex-config.toml`](mcp-config-examples/codex-config.toml).

- **Cursor** — add the three remote servers by URL and Playwright as a command
  server (`npx @playwright/mcp@latest`) via Cursor's MCP settings or
  `mcp.json`; use Cursor's secure credential mechanism for the tokens if
  environment-variable substitution isn't supported by your version.

- **VS Code** — use the user-level MCP configuration; GitHub's remote server
  supports OAuth in current VS Code versions, so a PAT is optional there. Add
  Context7 and Hugging Face as remote HTTP servers and Playwright via `npx`, as
  documented by Microsoft.

Confirm the exact settings location for your client version against that
client's current official documentation before editing — it changes across
releases.

## Secrets

Required environment variables (names only — never commit values):

```text
GITHUB_PAT_TOKEN
CONTEXT7_API_KEY
HF_TOKEN
```

Set them outside the repository, at the user/session level. PowerShell:

```powershell
# Current session only
$env:GITHUB_PAT_TOKEN = "<set outside the repository>"
$env:CONTEXT7_API_KEY = "<set outside the repository>"
$env:HF_TOKEN = "<set outside the repository>"

# Persistent, user-level
[Environment]::SetEnvironmentVariable("GITHUB_PAT_TOKEN", "<secret>", "User")
[Environment]::SetEnvironmentVariable("CONTEXT7_API_KEY", "<secret>", "User")
[Environment]::SetEnvironmentVariable("HF_TOKEN", "<secret>", "User")
```

Restart the coding client after setting persistent variables so the MCP client
process picks them up — a `.env` file is not automatically loaded by Codex,
Cursor, VS Code, or Claude Code.

Security rules:

- Use a fine-grained GitHub PAT scoped to this repository, read-only where
  practical; expand scope only after a specific operation fails for a
  legitimate reason.
- Never place real tokens in `AGENTS.md`, README files, examples, screenshots,
  test fixtures, shell history, issue bodies, or pull requests.
- Prefer OAuth over static tokens where your client and the server both
  support it reliably.
- GitHub write operations (create/merge/close/delete/comment) always require
  explicit human approval — this is both an `AGENTS.md` policy and, in Claude
  Code, backed by its normal tool-approval prompts for any MCP tool call that
  isn't allow-listed.

## Verification performed

| Server | Check | Result |
|---|---|---|
| GitHub | DNS/HTTPS reachability to `api.githubcopilot.com` | Reachable |
| Context7 | DNS/HTTPS reachability to `mcp.context7.com` | Reachable |
| Hugging Face | DNS/HTTPS reachability to `huggingface.co` | Reachable (HTTP 200) |
| Playwright | `npx`/Node available locally | Node v24.18.0, npx v11.16.0 |

Full protocol-level verification (actually connecting, listing tools, and
running a read-only query against each server) requires an authenticated
`claude` session with the environment variables above set — the CLI is not
reachable as a standalone binary from this environment's non-interactive shell
sandbox. Once your tokens are set, run inside a Claude Code session:

1. **GitHub** — `/mcp`, confirm `github` shows `connected`, then ask Claude to
   list recent commits or open PRs on `papayasamosa/geotestlab_dev` (read-only).
2. **Context7** — ask Claude a narrow question about `st.session_state` or
   `streamlit.testing.v1.AppTest`; confirm the answer matches Streamlit 1.60.
3. **Playwright** — start the app (`streamlit run geotestmatch.py --server.headless true --server.port 8501`),
   ask Claude to open `http://127.0.0.1:8501` and click one harmless control,
   confirm the four workflow tabs render and no console error appears, then
   stop the Streamlit process.
4. **Hugging Face** — ask Claude to search the Hub for a relevant time-series
   or forecasting repository and return metadata only (no weight downloads).

## Troubleshooting

- **Server stuck at "Pending approval"** — run `claude` interactively in this
  repo and accept the workspace-trust / server-approval prompt, or run
  `claude mcp reset-project-choices` to re-prompt.
- **"Needs authentication"** — run `/mcp` and complete the OAuth flow, or
  confirm the relevant environment variable is set and the client was
  restarted after setting it.
- **Missing-variable warning in `claude mcp list`** — the referenced env var
  isn't visible to the MCP client process; set it at the user/session level
  (not just inside a subshell) and restart the client.
- **Playwright fails to launch** — confirm `npx @playwright/mcp@latest`
  installs without a proxy/registry error; corporate networks sometimes block
  the npm registry.
- **An MCP server is simply unavailable** — proceed with the rest of the task
  using repository code, tests, and official documentation; report which
  server was unavailable rather than fabricating its output.

## Uninstall / disable

- Disable without losing configuration: open `/mcp` in Claude Code and toggle
  the server off.
- Remove entirely: `claude mcp remove <name>` (for a project-scoped server this
  edits `.mcp.json`; delete the file's entry directly if you prefer).
- Revoke stored OAuth credentials: `/mcp` → "Clear authentication" for that
  server, or `claude mcp logout <name>`.
- Revoke a token at the source (GitHub PAT settings, Context7 dashboard,
  Hugging Face token settings) if it may have been exposed.

## Official sources

- GitHub MCP: <https://github.com/github/github-mcp-server>
- Context7 MCP: <https://github.com/upstash/context7>
- Playwright MCP: <https://github.com/microsoft/playwright-mcp>
- Hugging Face MCP: <https://github.com/huggingface/hf-mcp-server>
- Claude Code MCP reference: <https://code.claude.com/docs/en/mcp>
- Codex MCP configuration: <https://developers.openai.com/codex/mcp>
