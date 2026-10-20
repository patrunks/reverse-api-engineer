"""Operator approval for agent tool calls.

Upstream RAE auto-approves every tool call. The agent reads pages it does not
control and a page can inject instructions, so this fork asks the operator
before anything that runs code on the host or writes outside the run folder.
Browsing itself (MCP browser tools, agent-browser session commands) stays
unattended. ``tool_approval = "auto"`` restores the upstream behavior.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

import questionary
from claude_agent_sdk import HookMatcher
from claude_agent_sdk.types import HookEvent
from rich.console import Console
from rich.markup import escape

from .agent_browser import agent_browser_shell_invoker
from .utils import get_config_path

APPROVAL_MODES = ("ask", "auto")
DEFAULT_APPROVAL_MODE = "ask"

NON_INTERACTIVE_DENIAL = (
    "Denied: this action needs operator approval and the CLI is running non-interactively. "
    "Continue without it. The operator can set tool_approval to 'auto' to allow such actions."
)
OPERATOR_DENIAL = "Denied by the operator. Continue without this action."
OPERATOR_TIMEOUT_SECONDS = 3600

SHELL_TOOLS = frozenset({"Bash", "PowerShell"})

# Claude tools that must reach can_use_tool; a tool listed in allowed_tools skips it.
REVIEWED_CLAUDE_TOOLS = frozenset({"Bash", "PowerShell", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep"})

# Arguments that name a host path, across Claude tools (Read, Write, Edit, Grep...)
# and browser MCP tools (screenshots, script output, heap snapshots...).
PATH_ARGUMENTS = ("file_path", "notebook_path", "path", "filePath", "filename")

# Browser MCP tools that reach past the page: Playwright's run_code executes in
# node:vm, which is not a security boundary; uploads send local files to the
# site; extensions and PWAs run outside the page sandbox.
HOST_REACHING_BROWSER_TOOLS = frozenset(
    {
        "browser_run_code",
        "browser_file_upload",
        "browser_install",
        "upload_file",
        "install_extension",
        "uninstall_extension",
        "reload_extension",
        "trigger_extension_action",
        "install_pwa",
        "uninstall_pwa",
        "launch_pwa",
    }
)

# agent-browser subcommands that only drive the run's own browser session.
# Left out on purpose: upload, download, install, upgrade, auth, plugin, state, chat.
AGENT_BROWSER_SESSION_SUBCOMMANDS = frozenset(
    {
        "open",
        "goto",
        "navigate",
        "back",
        "forward",
        "reload",
        "close",
        "snapshot",
        "screenshot",
        "pdf",
        "click",
        "dblclick",
        "fill",
        "type",
        "press",
        "keyboard",
        "hover",
        "focus",
        "select",
        "check",
        "uncheck",
        "scroll",
        "scrollintoview",
        "drag",
        "mouse",
        "highlight",
        "wait",
        "get",
        "is",
        "find",
        "eval",
        "network",
        "tab",
        "frame",
        "dialog",
        "console",
        "errors",
        "cookies",
        "storage",
        "set",
        "skills",
        "doctor",
        "help",
    }
)

# Global flags that swap the throwaway session for the operator's browser,
# profile or files, or launch arbitrary executables. Matched as prefixes.
AGENT_BROWSER_RISKY_FLAGS = (
    "--profile",
    "--auto-connect",
    "--cdp",
    "--executable-path",
    "--extension",
    "--init-script",
    "--enable",
    "--state",
    "--restore",
    "--allow-file-access",
    "--args",
    "--provider",
    "--ca-cert",
    "--use-system-ca",
    "--proxy",
    "--confirm-actions",
    "--confirm-interactive",
    "--stdin",
)

_AGENT_BROWSER_VALUE_FLAGS = frozenset({"--session", "--namespace", "--session-name", "--device", "--user-agent"})
_SHELL_OPERATOR_CHARS = frozenset("();<>|&")

# Parallel tool calls must not stack questionary prompts on the same terminal.
_PROMPT_LOCK = asyncio.Lock()


def _config_manager_snapshot() -> dict[str, Any]:
    try:
        from .config import ConfigManager

        return ConfigManager(get_config_path()).config.copy()
    except Exception:
        return {}


def approval_mode() -> str:
    """``ask`` (default) or ``auto``; env ``RAE_TOOL_APPROVAL`` overrides config ``tool_approval``."""

    value = os.environ.get("RAE_TOOL_APPROVAL", "").strip().lower()
    if not value:
        value = str(_config_manager_snapshot().get("tool_approval") or DEFAULT_APPROVAL_MODE).strip().lower()
    return value if value in APPROVAL_MODES else DEFAULT_APPROVAL_MODE


def _shell_tokens(command: str) -> list[str] | None:
    """Split a command the way a POSIX shell would, or None if it can do more than run one program."""

    # Expansions and command substitution still run inside double quotes.
    if any(ch in command for ch in "$`\n\r"):
        return None
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None
    if any(token and set(token) <= _SHELL_OPERATOR_CHARS for token in tokens):
        return None
    return tokens


def _agent_browser_prefixes() -> list[list[str]]:
    prefixes = [["agent-browser"]]
    invoker = shlex.split(agent_browser_shell_invoker())
    if invoker and invoker not in prefixes:
        prefixes.append(invoker)
    return prefixes


def is_session_browser_command(command: str) -> bool:
    """True for a single agent-browser call that only drives the run's own browser session."""

    tokens = _shell_tokens(command.strip())
    if not tokens:
        return False
    for prefix in _agent_browser_prefixes():
        if tokens[: len(prefix)] == prefix:
            args = tokens[len(prefix) :]
            break
    else:
        return False

    subcommand = None
    skip_value = False
    for arg in args:
        if skip_value:
            skip_value = False
            continue
        if arg.startswith("-"):
            name = arg.split("=", 1)[0]
            if name.startswith(AGENT_BROWSER_RISKY_FLAGS):
                return False
            skip_value = name in _AGENT_BROWSER_VALUE_FLAGS and "=" not in arg
            continue
        if subcommand is None:
            subcommand = arg
    if subcommand is None:
        return args in (["--help"], ["-h"])
    return subcommand in AGENT_BROWSER_SESSION_SUBCOMMANDS


def _is_within(target: str, workspace: Path) -> bool:
    if not target:
        return False
    path = Path(target).expanduser()
    if not path.is_absolute():
        path = workspace / path
    try:
        return path.resolve().is_relative_to(workspace.resolve())
    except (OSError, RuntimeError):
        return False


def _reaches_host(tool_name: str) -> bool:
    # Claude names MCP tools mcp__<server>__<tool>; OpenCode uses <server>_<tool>.
    return any(tool_name == tool or tool_name.endswith("_" + tool) for tool in HOST_REACHING_BROWSER_TOOLS)


def risky_action(tool_name: str, tool_input: Mapping[str, Any], workspace: Path) -> str | None:
    """Describe what the call would do if it needs approval, or None when it can run unattended."""

    if tool_name in SHELL_TOOLS:
        command = str(tool_input.get("command") or "")
        return None if is_session_browser_command(command) else f"run a shell command: {command}"
    if _reaches_host(tool_name):
        details = json.dumps(dict(tool_input), default=str)[:400]
        return f"use {tool_name}, which reaches beyond the browser page: {details}"
    # Reads count too: a file read outside the run folder can be sent out by the next navigation.
    for key in PATH_ARGUMENTS:
        target = tool_input.get(key)
        if isinstance(target, str) and target and not _is_within(target, workspace):
            return f"use {tool_name} on a path outside the run folder: {target}"
    return None


class ClaudeToolGate:
    """Reviews each Claude tool call once, from a PreToolUse hook backed by can_use_tool.

    can_use_tool alone is not enough: Claude Code auto-approves commands it deems
    read-only (``echo``, ``ls``...) without consulting it, so the hook is the gate.
    Claude Code still calls can_use_tool after some hook approvals (e.g. Write);
    remembering what the hook approved keeps the operator from being asked twice,
    while a call the hook never decided (timeout, error) still gets a full review.
    """

    def __init__(self, review: Callable[[str, Mapping[str, Any]], Awaitable[str | None]]) -> None:
        self._review = review
        self._approved: set[str] = set()

    @staticmethod
    def _key(tool_name: str, tool_input: Mapping[str, Any]) -> str:
        return json.dumps([tool_name, tool_input], sort_keys=True, default=str)

    async def _pre_tool_use(self, input_data: Any, tool_use_id: str | None, context: Any) -> Any:
        tool_name = str(input_data.get("tool_name") or "")
        # No decision: AskUserQuestion must reach can_use_tool, which fills in the answers.
        if tool_name == "AskUserQuestion":
            return {}
        tool_input = input_data.get("tool_input") or {}
        denial = await self._review(tool_name, tool_input)
        if denial is None:
            self._approved.add(self._key(tool_name, tool_input))
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": denial,
            }
        }

    def hooks(self) -> dict[HookEvent, list[HookMatcher]]:
        # The operator may take a while to answer; the SDK default would time out after 60s.
        return {"PreToolUse": [HookMatcher(matcher=None, hooks=[self._pre_tool_use], timeout=OPERATOR_TIMEOUT_SECONDS)]}

    async def permission(self, tool_name: str, tool_input: Mapping[str, Any]) -> str | None:
        """can_use_tool side: None if allowed, else the denial message."""
        key = self._key(tool_name, tool_input)
        if key in self._approved:
            self._approved.discard(key)
            return None
        return await self._review(tool_name, tool_input)


def copilot_permission_as_tool_call(request: Any) -> tuple[str, dict[str, Any]]:
    """Translate a Copilot SDK ``PermissionRequest`` into the (tool_name, tool_input) reviewed here."""

    def field(name: str) -> Any:
        return request.get(name) if isinstance(request, Mapping) else getattr(request, name, None)

    kind = field("kind")
    kind = str(getattr(kind, "value", kind) or "")
    if kind == "shell":
        return "Bash", {"command": field("full_command_text") or ""}
    if kind in ("read", "write"):
        return kind.capitalize(), {"file_path": field("path") or field("file_name") or ""}
    if kind == "mcp":
        args = field("args")
        return str(field("tool_name") or "mcp"), dict(args) if isinstance(args, Mapping) else {}
    return kind or "unknown", {}


async def ask_operator(action: str, *, interactive: bool, console: Console) -> str | None:
    """Return None when the operator allows ``action``, else the denial message for the agent."""

    if approval_mode() == "auto":
        return None
    if not interactive:
        console.print(f"  [yellow]![/yellow] [dim]blocked (non-interactive): {escape(action)}[/dim]")
        return NON_INTERACTIVE_DENIAL
    async with _PROMPT_LOCK:
        console.print()
        console.print(f"  [yellow]?[/yellow] [bold]The agent wants to {escape(action)}[/bold]")
        approved = await questionary.confirm(" Allow?", default=False, qmark="").ask_async()
    return None if approved else OPERATOR_DENIAL


async def review_tool_call(
    tool_name: str,
    tool_input: Mapping[str, Any],
    *,
    workspace: Path,
    interactive: bool,
    console: Console,
) -> str | None:
    """Return None if the tool call may run, else the denial message for the agent."""

    action = risky_action(tool_name, tool_input, workspace)
    if action is None:
        return None
    return await ask_operator(action, interactive=interactive, console=console)
