"""Configuration loading for DevNarrate.

Loads project-specific settings from .devnarrate/config.toml.
Falls back to sensible defaults when no config file exists.
"""

import os
import tomllib
from typing import Any, Optional


# ── Default configuration ──────────────────────────────────────────
# Every key here can be overridden by .devnarrate/config.toml

DEFAULTS: dict[str, Any] = {
    "commit": {
        "types": ["feat", "fix", "docs", "style", "refactor", "test", "chore"],
        "max_subject_length": 50,
        "max_body_line_length": 72,
        "require_scope": False,
    },
    "secrets": {
        "enabled": True,
        "max_findings": 20,
        "custom_patterns": [],
        # Example custom_patterns entry:
        # { "name": "Internal API Key", "pattern": "MYCO-[A-Za-z0-9]{32}" }
    },
    "pr": {
        "default_base_branch": "main",
        "draft_by_default": False,
        "template": "",  # relative path within .devnarrate/pr-templates/
    },
    "review": {
        "large_change_threshold": 50,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict.

    - Dict values are merged recursively.
    - All other values in override replace the base value.
    - Keys in base that are absent from override are preserved.
    """
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(repo_path: Optional[str] = None) -> dict[str, Any]:
    """Load configuration from .devnarrate/config.toml in the given repo.

    Args:
        repo_path: Path to the git repository root. If None, returns defaults.

    Returns:
        Merged configuration dict (defaults + user overrides).
    """
    if repo_path is None:
        return DEFAULTS.copy()

    config_path = os.path.join(repo_path, ".devnarrate", "config.toml")

    if not os.path.isfile(config_path):
        return DEFAULTS.copy()

    try:
        with open(config_path, "rb") as f:
            user_config = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        # Bad config file — fall back to defaults silently
        return DEFAULTS.copy()

    return _deep_merge(DEFAULTS, user_config)
