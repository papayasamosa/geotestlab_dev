#!/usr/bin/env python3
"""Prerequisite checker for the MCP development tooling.

Usage:
    python scripts/check_mcp_prereqs.py

Checks Node.js/npx availability, the *presence* (never the value) of the
three MCP secret environment variables, DNS/HTTPS reachability of the three
remote MCP hostnames, and whether the local Streamlit command is available.
Reads and modifies nothing; prints a report to stdout.

See docs/development/mcp-tooling.md for setup instructions.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import urllib.error
import urllib.request

REQUIRED_ENV_VARS = ["GITHUB_PAT_TOKEN", "CONTEXT7_API_KEY", "HF_TOKEN"]
REMOTE_HOSTS = ["api.githubcopilot.com", "mcp.context7.com", "huggingface.co"]


def _run_version(command: list[str]) -> str | None:
    exe = shutil.which(command[0])
    if exe is None:
        return None
    try:
        result = subprocess.run(
            [exe, *command[1:]], capture_output=True, text=True, timeout=10, check=False
        )
    except OSError:
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else None


def check_node() -> None:
    version = _run_version(["node", "--version"])
    print(f"Node.js: {version or 'NOT FOUND'} (need >= 18)")


def check_npx() -> None:
    version = _run_version(["npx", "--version"])
    print(f"npx: {version or 'NOT FOUND'}")


def check_env_vars() -> None:
    for name in REQUIRED_ENV_VARS:
        present = name in os.environ and bool(os.environ[name])
        print(f"{name}: {'present' if present else 'absent'}")


def check_remote_hosts() -> None:
    for host in REMOTE_HOSTS:
        try:
            socket.getaddrinfo(host, 443)
        except OSError:
            print(f"{host}: DNS resolution FAILED")
            continue
        try:
            urllib.request.urlopen(f"https://{host}", timeout=8)
            print(f"{host}: reachable")
        except urllib.error.HTTPError:
            # Any HTTP response (even 4xx) means the host is reachable.
            print(f"{host}: reachable")
        except OSError as exc:
            print(f"{host}: unreachable ({exc})")


def check_streamlit() -> None:
    exe = shutil.which("streamlit")
    print(f"streamlit CLI: {'found at ' + exe if exe else 'NOT FOUND on PATH'}")


def main() -> None:
    print("--- Node.js / npx ---")
    check_node()
    check_npx()
    print("\n--- MCP secret environment variables (presence only) ---")
    check_env_vars()
    print("\n--- Remote MCP endpoint reachability ---")
    check_remote_hosts()
    print("\n--- Local Streamlit command ---")
    check_streamlit()


if __name__ == "__main__":
    main()
