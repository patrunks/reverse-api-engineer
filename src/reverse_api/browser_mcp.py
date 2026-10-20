"""Pinned npm packages and launch arguments for the browser MCP servers.

Packages run through ``npx -y`` on every session, so an unpinned ``@latest``
would execute whatever was published most recently. Pins are overridable
through config or environment variables, like the OpenCode and agent-browser pins.
"""

from __future__ import annotations

import os
from typing import Any

from .utils import get_config_path

DEFAULT_PLAYWRIGHT_MCP_PACKAGE = "rae-playwright-mcp@0.0.8"
DEFAULT_CHROME_MCP_PACKAGE = "chrome-devtools-mcp@1.10.1"

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _config_manager_snapshot() -> dict[str, Any]:
    try:
        from .config import ConfigManager

        return ConfigManager(get_config_path()).config.copy()
    except Exception:
        return {}


def playwright_mcp_package() -> str:
    """npm specifier for the Playwright MCP server (``RAE_PLAYWRIGHT_MCP_PACKAGE``)."""

    env = os.environ.get("RAE_PLAYWRIGHT_MCP_PACKAGE", "").strip()
    if env:
        return env
    return str(_config_manager_snapshot().get("playwright_mcp_npx_package") or DEFAULT_PLAYWRIGHT_MCP_PACKAGE)


def chrome_mcp_package() -> str:
    """npm specifier for the Chrome DevTools MCP server (``RAE_CHROME_MCP_PACKAGE``)."""

    env = os.environ.get("RAE_CHROME_MCP_PACKAGE", "").strip()
    if env:
        return env
    return str(_config_manager_snapshot().get("chrome_mcp_npx_package") or DEFAULT_CHROME_MCP_PACKAGE)


def chrome_mcp_auto_connect() -> bool:
    """Whether chrome-mcp may attach to the operator's own Chrome (``RAE_CHROME_MCP_AUTO_CONNECT``)."""

    env = os.environ.get("RAE_CHROME_MCP_AUTO_CONNECT")
    if env is not None:
        return env.strip().lower() in _TRUE_VALUES
    return bool(_config_manager_snapshot().get("chrome_mcp_auto_connect", False))


def chrome_mcp_args(headless: bool) -> list[str]:
    """Package and flags for chrome-devtools-mcp, without the ``npx -y`` prefix.

    ``--autoConnect`` hands the agent the operator's signed-in Chrome profile,
    so it is opt-in; by default the server launches a throwaway ``--isolated``
    profile. Auto-connect needs a headed Chrome, so headless always isolates.
    """

    args = [chrome_mcp_package(), "--no-usage-statistics"]
    if headless:
        args += ["--headless", "--isolated"]
    elif chrome_mcp_auto_connect():
        args.append("--autoConnect")
    else:
        args.append("--isolated")
    return args


def chrome_mcp_profile_note(headless: bool) -> str:
    """Prompt sentence telling the agent which Chrome profile ``chrome_mcp_args`` gives it."""

    if not headless and chrome_mcp_auto_connect():
        return (
            "You are connected to the user's REAL Chrome browser with their existing sessions, cookies, and authentication. "
            "You do NOT need to log in where they're already authenticated."
        )
    return (
        "You are driving a fresh, isolated Chrome profile with no existing sessions or cookies; it is discarded when the run ends. "
        "If the mission needs an account, log in through the page, or use AskUserQuestion to get what you need from the operator."
    )


def playwright_mcp_args(run_id: str, headless: bool) -> list[str]:
    """Package and flags for the Playwright MCP server, without the ``npx -y`` prefix.

    ``--isolated`` keeps the profile in memory; otherwise cookies from every
    run accumulate in a persistent profile on disk.
    """

    args = [playwright_mcp_package(), "run-mcp-server", "--run-id", run_id, "--isolated"]
    if headless:
        args.append("--headless")
    return args
