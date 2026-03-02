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
        # Allowed conventional-commit type prefixes.
        # The AI will only suggest these types when generating commit messages.
        # Example: ["feat", "fix", "hotfix", "release"]
        "types": ["feat", "fix", "docs", "style", "refactor", "test", "chore"],

        # Maximum character length for the commit subject line (first line).
        # Standard convention is 50; GitHub truncates subjects longer than 72.
        "max_subject_length": 50,

        # Maximum character length per line in the commit body.
        # Standard convention is 72 for readability in terminals and git log.
        "max_body_line_length": 72,

        # When true, the AI will use type(scope): format instead of type: format.
        # e.g. "feat(auth): add login" instead of "feat: add login".
        "require_scope": False,

        # When the number of staged files meets or exceeds this threshold,
        # get_commit_context will suggest splitting into multiple commits.
        # Set to 0 to disable split suggestions entirely.
        "split_threshold": 4,
    },
    "secrets": {
        # Master switch for secret scanning. Set to false to skip scanning entirely.
        # The commit context response will indicate scanning was disabled.
        "enabled": True,

        # Maximum number of secret findings returned per scan.
        # Prevents flooding the MCP response when a diff has many issues.
        # Findings beyond this cap are still counted in total_findings.
        "max_findings": 20,

        # Additional regex patterns to scan for, beyond the 25+ built-in detectors.
        # Each entry needs "name" (display label) and "pattern" (regex string).
        # Custom patterns take priority: if they match a line already flagged by
        # a built-in detector, the custom name replaces the generic detector name.
        #
        # Example in config.toml:
        #   [[secrets.custom_patterns]]
        #   name = "Internal API Key"
        #   pattern = "MYCO-[A-Za-z0-9]{32}"
        "custom_patterns": [],
    },
    "pr": {
        # Branch to compare against when generating PR descriptions.
        # Used as the default base_branch hint in get_pr_context output.
        "default_base_branch": "main",

        # When true, create_pr will default to opening draft PRs.
        "draft_by_default": False,

        # Preferred template filename within .devnarrate/pr-templates/.
        # If set, the AI will use this template without asking.
        # Leave empty to let the AI list available templates and ask the user.
        "template": "",
    },
    "review": {
        # Number of added lines at which review_changes flags a file as a
        # "large change" deserving extra attention in the review summary.
        # Lower = stricter reviews, higher = quieter for repos with big diffs.
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
