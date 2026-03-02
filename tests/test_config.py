"""Tests for devnarrate.config — configuration loading and merging."""

import json
import os
import subprocess
import textwrap

import pytest

from devnarrate.config import DEFAULTS, _deep_merge, load_config


# ──────────────────────────────────
# Tests for _deep_merge
# ──────────────────────────────────


class TestDeepMerge:
    """Unit tests for recursive dict merging."""

    def test_empty_override(self):
        base = {"a": 1, "b": {"c": 2}}
        assert _deep_merge(base, {}) == base

    def test_empty_base(self):
        override = {"a": 1}
        assert _deep_merge({}, override) == {"a": 1}

    def test_flat_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        assert _deep_merge(base, override) == {"a": 1, "b": 99}

    def test_nested_merge(self):
        base = {"commit": {"types": ["feat"], "max_subject_length": 50}}
        override = {"commit": {"max_subject_length": 72}}
        result = _deep_merge(base, override)
        assert result["commit"]["types"] == ["feat"]
        assert result["commit"]["max_subject_length"] == 72

    def test_new_keys_added(self):
        base = {"a": 1}
        override = {"b": 2}
        assert _deep_merge(base, override) == {"a": 1, "b": 2}

    def test_nested_new_key(self):
        base = {"commit": {"types": ["feat"]}}
        override = {"commit": {"custom_key": True}}
        result = _deep_merge(base, override)
        assert result["commit"]["types"] == ["feat"]
        assert result["commit"]["custom_key"] is True

    def test_does_not_mutate_base(self):
        base = {"a": {"b": 1}}
        override = {"a": {"b": 99}}
        _deep_merge(base, override)
        assert base["a"]["b"] == 1


# ──────────────────────────────────
# Tests for load_config
# ──────────────────────────────────


class TestLoadConfig:
    """Tests for loading .devnarrate/config.toml."""

    def test_returns_defaults_when_no_repo_path(self):
        cfg = load_config(None)
        assert cfg["commit"]["types"] == DEFAULTS["commit"]["types"]
        assert cfg["secrets"]["enabled"] is True

    def test_returns_defaults_when_no_config_file(self, tmp_path):
        """Repo exists but no .devnarrate/config.toml → defaults."""
        cfg = load_config(str(tmp_path))
        assert cfg == DEFAULTS

    def test_loads_partial_config(self, tmp_path):
        """Config with only [commit] section still has defaults for others."""
        config_dir = tmp_path / ".devnarrate"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [commit]
            max_subject_length = 72
        """))

        cfg = load_config(str(tmp_path))
        assert cfg["commit"]["max_subject_length"] == 72
        # Other commit defaults preserved
        assert cfg["commit"]["types"] == DEFAULTS["commit"]["types"]
        assert cfg["commit"]["max_body_line_length"] == 72
        # Other sections default
        assert cfg["secrets"]["enabled"] is True
        assert cfg["pr"]["default_base_branch"] == "main"

    def test_overrides_commit_types(self, tmp_path):
        config_dir = tmp_path / ".devnarrate"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [commit]
            types = ["feat", "fix", "hotfix", "release"]
        """))

        cfg = load_config(str(tmp_path))
        assert cfg["commit"]["types"] == ["feat", "fix", "hotfix", "release"]

    def test_overrides_secrets_config(self, tmp_path):
        config_dir = tmp_path / ".devnarrate"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [secrets]
            enabled = false
            max_findings = 5
        """))

        cfg = load_config(str(tmp_path))
        assert cfg["secrets"]["enabled"] is False
        assert cfg["secrets"]["max_findings"] == 5

    def test_custom_secret_patterns(self, tmp_path):
        config_dir = tmp_path / ".devnarrate"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [[secrets.custom_patterns]]
            name = "Internal API Key"
            pattern = "MYCO-[A-Za-z0-9]{32}"

            [[secrets.custom_patterns]]
            name = "Service Token"
            pattern = "svc_[a-z0-9]{40}"
        """))

        cfg = load_config(str(tmp_path))
        assert len(cfg["secrets"]["custom_patterns"]) == 2
        assert cfg["secrets"]["custom_patterns"][0]["name"] == "Internal API Key"
        assert cfg["secrets"]["custom_patterns"][1]["pattern"] == "svc_[a-z0-9]{40}"

    def test_overrides_pr_config(self, tmp_path):
        config_dir = tmp_path / ".devnarrate"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [pr]
            default_base_branch = "develop"
            draft_by_default = true
            template = "feature.md"
        """))

        cfg = load_config(str(tmp_path))
        assert cfg["pr"]["default_base_branch"] == "develop"
        assert cfg["pr"]["draft_by_default"] is True
        assert cfg["pr"]["template"] == "feature.md"

    def test_overrides_review_config(self, tmp_path):
        config_dir = tmp_path / ".devnarrate"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [review]
            large_change_threshold = 100
        """))

        cfg = load_config(str(tmp_path))
        assert cfg["review"]["large_change_threshold"] == 100

    def test_bad_toml_returns_defaults(self, tmp_path):
        """Invalid TOML → silently return defaults."""
        config_dir = tmp_path / ".devnarrate"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text("this is [[ not valid toml ===")

        cfg = load_config(str(tmp_path))
        assert cfg == DEFAULTS

    def test_full_config(self, tmp_path):
        """A complete config file overrides everything."""
        config_dir = tmp_path / ".devnarrate"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [commit]
            types = ["feat", "fix"]
            max_subject_length = 60
            max_body_line_length = 80
            require_scope = true

            [secrets]
            enabled = true
            max_findings = 10

            [[secrets.custom_patterns]]
            name = "Corp Token"
            pattern = "CORP-[0-9a-f]{16}"

            [pr]
            default_base_branch = "develop"
            draft_by_default = true
            template = "bugfix.md"

            [review]
            large_change_threshold = 25
        """))

        cfg = load_config(str(tmp_path))
        assert cfg["commit"]["types"] == ["feat", "fix"]
        assert cfg["commit"]["max_subject_length"] == 60
        assert cfg["commit"]["max_body_line_length"] == 80
        assert cfg["commit"]["require_scope"] is True
        assert cfg["secrets"]["max_findings"] == 10
        assert len(cfg["secrets"]["custom_patterns"]) == 1
        assert cfg["pr"]["default_base_branch"] == "develop"
        assert cfg["pr"]["draft_by_default"] is True
        assert cfg["pr"]["template"] == "bugfix.md"
        assert cfg["review"]["large_change_threshold"] == 25


# ──────────────────────────────────
# Integration: config affects MCP tools
# ──────────────────────────────────


class TestConfigIntegration:
    """Verify that config values flow into MCP tool responses."""

    @pytest.fixture
    def configured_git_repo(self, tmp_git_repo):
        """A git repo with a .devnarrate/config.toml."""
        config_dir = tmp_git_repo / ".devnarrate"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [commit]
            types = ["feat", "fix", "hotfix"]
            max_subject_length = 60
            require_scope = true

            [secrets]
            max_findings = 3

            [review]
            large_change_threshold = 25
        """))
        # Stage a file for testing
        f = tmp_git_repo / "app.py"
        f.write_text("x = 1\n")
        subprocess.run(
            ["git", "add", "app.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        return tmp_git_repo

    @pytest.mark.asyncio
    async def test_commit_context_uses_config_types(self, configured_git_repo):
        """get_commit_context uses commit types from config."""
        from mcp.shared.memory import (
            create_connected_server_and_client_session as create_session,
        )
        from mcp.types import ListRootsResult, Root
        from devnarrate.server import mcp as devnarrate_mcp

        repo = str(configured_git_repo)

        async def list_roots(context):
            return ListRootsResult(
                roots=[Root(uri=f"file://{repo}", name="test-repo")]
            )

        async with create_session(devnarrate_mcp, list_roots_callback=list_roots) as client:
            result = await client.call_tool("get_commit_context", {})
            data = json.loads(result.content[0].text)
            guide = data["commit_format_guide"]
            assert guide["types"] == ["feat", "fix", "hotfix"]
            assert "60" in guide["subject_line"]
            assert guide["require_scope"] is True

    @pytest.mark.asyncio
    async def test_review_uses_config_threshold(self, configured_git_repo):
        """review_changes includes large_change_threshold from config."""
        from mcp.shared.memory import (
            create_connected_server_and_client_session as create_session,
        )
        from mcp.types import ListRootsResult, Root
        from devnarrate.server import mcp as devnarrate_mcp

        repo = str(configured_git_repo)

        # Modify a tracked file so working scope has changes
        readme = configured_git_repo / "README.md"
        readme.write_text("# Updated\n")

        async def list_roots(context):
            return ListRootsResult(
                roots=[Root(uri=f"file://{repo}", name="test-repo")]
            )

        async with create_session(devnarrate_mcp, list_roots_callback=list_roots) as client:
            result = await client.call_tool(
                "review_changes", {"goal": "test threshold"}
            )
            data = json.loads(result.content[0].text)
            assert data["large_change_threshold"] == 25

    @pytest.mark.asyncio
    async def test_secrets_disabled_via_config(self, tmp_git_repo):
        """When secrets.enabled=false, secret scan is skipped."""
        from mcp.shared.memory import (
            create_connected_server_and_client_session as create_session,
        )
        from mcp.types import ListRootsResult, Root
        from devnarrate.server import mcp as devnarrate_mcp

        config_dir = tmp_git_repo / ".devnarrate"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text("[secrets]\nenabled = false\n")

        # Stage a file with a "secret"
        f = tmp_git_repo / "config.py"
        f.write_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
        subprocess.run(
            ["git", "add", "config.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )

        repo = str(tmp_git_repo)

        async def list_roots(context):
            return ListRootsResult(
                roots=[Root(uri=f"file://{repo}", name="test-repo")]
            )

        async with create_session(devnarrate_mcp, list_roots_callback=list_roots) as client:
            result = await client.call_tool("get_commit_context", {})
            data = json.loads(result.content[0].text)
            assert data["secret_scan"]["status"] == "clean"
            assert "disabled" in data["secret_scan"]["message"].lower()


# ──────────────────────────────────
# Tests for custom secret patterns
# ──────────────────────────────────


class TestCustomSecretPatterns:
    """Verify custom patterns from config detect secrets."""

    def test_custom_pattern_matches(self):
        from devnarrate.secret_scanner import scan_diff

        diff = (
            "diff --git a/app.py b/app.py\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+TOKEN = \"MYCO-abcdefghijklmnopqrstuvwxyz123456\"\n"
            "+x = 1\n"
        )

        result = scan_diff(
            diff,
            custom_patterns=[
                {"name": "Internal API Key", "pattern": r"MYCO-[A-Za-z0-9]{32}"}
            ],
        )
        # Should find the custom pattern (may also find keyword match)
        custom_findings = [f for f in result["findings"] if f["type"] == "Internal API Key"]
        assert len(custom_findings) >= 1
        assert custom_findings[0]["file"] == "app.py"

    def test_custom_pattern_invalid_regex_skipped(self):
        from devnarrate.secret_scanner import scan_diff

        diff = (
            "diff --git a/app.py b/app.py\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -0,0 +1 @@\n"
            "+x = 1\n"
        )

        # Invalid regex should not crash
        result = scan_diff(
            diff,
            custom_patterns=[
                {"name": "Bad", "pattern": "[invalid("}
            ],
        )
        assert result["status"] == "clean"

    def test_max_findings_override(self):
        from devnarrate.secret_scanner import scan_diff

        # Create diff with multiple secrets
        lines = []
        for i in range(5):
            lines.append(f'+password_{i} = "supersecret{i}longvalue"')

        diff = (
            "diff --git a/secrets.py b/secrets.py\n"
            "--- a/secrets.py\n"
            "+++ b/secrets.py\n"
            f"@@ -0,0 +1,{len(lines)} @@\n"
            + "\n".join(lines) + "\n"
        )

        result = scan_diff(diff, max_findings=2)
        if result["total_findings"] > 2:
            assert len(result["findings"]) == 2
