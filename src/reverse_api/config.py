"""Configuration management for reverse-api."""

import json
from pathlib import Path
from typing import Any

DEFAULT_OPENCODE_PROVIDER = "opencode"
DEFAULT_OPENCODE_MODEL = "big-pickle"

DEFAULT_CONFIG = {
    "agent_provider": "auto",  # "auto" | "chrome-mcp" | "agent-browser"
    "agent_browser_notes": "",  # extra instructions merged into agent-browser prompt / RAE_AGENT_BROWSER_NOTES env
    "agent_browser_npx_package": "agent-browser@0.38.2",
    # Exact npm pins for the browser MCP servers; npx would otherwise run whatever was published last.
    "playwright_mcp_npx_package": "rae-playwright-mcp@0.0.8",
    "chrome_mcp_npx_package": "chrome-devtools-mcp@1.10.1",
    # True lets chrome-mcp attach to your own signed-in Chrome; False launches a throwaway profile.
    "chrome_mcp_auto_connect": False,
    # "ask": confirm shell commands and writes outside the run folder; "auto": approve everything (upstream behavior).
    "tool_approval": "ask",
    "claude_code_model": "claude-sonnet-4-6",
    "collector_model": "claude-sonnet-4-6",  # Model for collector mode
    "cursor_model": "composer-2.5",  # Model id for Cursor SDK (see Cursor.models.list())
    # When True, local agents load broader Cursor setting layers (plugins/team) so WebFetch/WebSearch
    # and other IDE tools match Cursor desktop behavior. Set False for minimal "project+user" only.
    "cursor_web_search": True,
    # Optional override: list of setting source ids, e.g. ["project","user","all"]. None uses cursor_web_search.
    "cursor_setting_sources": None,
    "copilot_model": "gpt-5",  # Model for Copilot SDK sessions
    "opencode_model": DEFAULT_OPENCODE_MODEL,
    "opencode_provider": DEFAULT_OPENCODE_PROVIDER,
    "opencode_auto_start": True,
    "opencode_base_url": "http://127.0.0.1:4096",
    "opencode_npx_package": "opencode-ai@1.18.31",
    "ollama_auto_start": True,
    "ollama_base_url": "http://127.0.0.1:11434",
    "output_dir": None,  # None means use ~/.reverse-api/runs
    "output_language": "python",  # "python", "javascript", "typescript", "go", "java", "csharp", "php", "ruby", "c", or "powershell"
    "real_time_sync": True,  # Enable real-time file sync during engineering
    "sdk": "claude",  # "claude", "opencode", "copilot", or "cursor"
}

UNPINNED_LEGACY_PACKAGES = {
    "opencode_npx_package": "opencode-ai@latest",
    "agent_browser_npx_package": "agent-browser@0",
}


class ConfigManager:
    """Handles user settings and persistence."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.config = DEFAULT_CONFIG.copy()
        self.load()

    def load(self) -> None:
        """Load configuration from disk."""
        if self.config_path.exists():
            try:
                with open(self.config_path, encoding="utf-8-sig") as f:
                    user_config = json.load(f)

                    # Backward compatibility: migrate old config keys
                    # Migrate "model" -> "claude_code_model"
                    if "model" in user_config and "claude_code_model" not in user_config:
                        user_config["claude_code_model"] = user_config["model"]

                    # Reset removed agent providers to default
                    if user_config.get("agent_provider") in ("browser-use", "stagehand"):
                        user_config["agent_provider"] = "auto"

                    # save() persists every default, so configs written before the pins
                    # would keep the old floating specifiers forever
                    for key, unpinned in UNPINNED_LEGACY_PACKAGES.items():
                        if user_config.get(key) == unpinned:
                            del user_config[key]

                    # Only keep valid keys
                    valid_config = {k: v for k, v in user_config.items() if k in self.config}
                    self.config.update(valid_config)
            except (json.JSONDecodeError, UnicodeError, OSError):
                # Fallback to defaults if file is corrupted
                pass

    def save(self) -> None:
        """Save configuration to disk."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=4)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value and save."""
        self.config[key] = value
        self.save()

    def update(self, settings: dict[str, Any]) -> None:
        """Update multiple settings and save."""
        self.config.update(settings)
        self.save()
