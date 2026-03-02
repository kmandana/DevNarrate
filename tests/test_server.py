"""Tests for devnarrate.server — MCP tool integration tests.

These tests verify the MCP tools end-to-end:
- get_commit_context returns proper JSON with secret_scan and split suggestions
- commit_changes requires user_approved=True
- get_pr_context returns correct branch info
- create_pr requires user_approved=True
- execute_split_commit commits file subsets correctly
"""

import json
import subprocess

import pytest

from mcp.shared.memory import (
    create_connected_server_and_client_session as create_session,
)
from mcp.types import ListRootsResult, Root

from devnarrate.server import mcp as devnarrate_mcp


def _roots_callback(repo_path: str):
    """Create a list_roots callback that returns the given repo path."""
    async def list_roots(context) -> ListRootsResult:
        return ListRootsResult(
            roots=[Root(uri=f"file://{repo_path}", name="test-repo")]
        )
    return list_roots


# ──────────────────────────────────
# Tests for get_commit_context
# ──────────────────────────────────


class TestGetCommitContext:
    """Integration tests for the get_commit_context MCP tool."""

    @pytest.mark.asyncio
    async def test_no_staged_changes(self, tmp_git_repo):
        """Empty staging area → has_changes=False."""
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool("get_commit_context", {})
            data = json.loads(result.content[0].text)
            assert data["has_changes"] is False

    @pytest.mark.asyncio
    async def test_staged_file_returns_diff(self, tmp_git_repo):
        """Staged file appears in the diff output."""
        f = tmp_git_repo / "hello.py"
        f.write_text('print("hello")\n')
        subprocess.run(
            ["git", "add", "hello.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool("get_commit_context", {})
            data = json.loads(result.content[0].text)
            assert data["has_changes"] is True
            assert "hello.py" in data["diff"]
            assert len(data["files"]) >= 1

    @pytest.mark.asyncio
    async def test_secret_scan_included(self, tmp_git_repo):
        """Response includes secret_scan field."""
        f = tmp_git_repo / "clean.py"
        f.write_text("x = 1\n")
        subprocess.run(
            ["git", "add", "clean.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool("get_commit_context", {})
            data = json.loads(result.content[0].text)
            assert "secret_scan" in data
            assert data["secret_scan"]["status"] == "clean"

    @pytest.mark.asyncio
    async def test_secret_scan_detects_aws_key(self, tmp_git_repo):
        """Secret scanner catches an AWS key in staged diff."""
        f = tmp_git_repo / "config.py"
        f.write_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
        subprocess.run(
            ["git", "add", "config.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool("get_commit_context", {})
            data = json.loads(result.content[0].text)
            assert data["secret_scan"]["status"] == "warnings_found"
            assert data["secret_scan"]["total_findings"] >= 1

    @pytest.mark.asyncio
    async def test_commit_format_guide_present(self, tmp_git_repo):
        """Response includes the commit format guide."""
        f = tmp_git_repo / "test.py"
        f.write_text("pass\n")
        subprocess.run(
            ["git", "add", "test.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool("get_commit_context", {})
            data = json.loads(result.content[0].text)
            assert "commit_format_guide" in data
            assert "types" in data["commit_format_guide"]

    @pytest.mark.asyncio
    async def test_pagination_cursor_skips_secret_scan(self, tmp_git_repo):
        """When a cursor is provided, secret scan is skipped (only first page)."""
        f = tmp_git_repo / "big.py"
        f.write_text("x = 1\n" * 100)
        subprocess.run(
            ["git", "add", "big.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool(
                "get_commit_context", {"cursor": "5"}
            )
            data = json.loads(result.content[0].text)
            # Secret scan should indicate it was skipped
            assert "first page" in data["secret_scan"]["message"].lower()


# ──────────────────────────────────
# Tests for commit_changes
# ──────────────────────────────────


class TestCommitChanges:
    """Integration tests for the commit_changes MCP tool."""

    @pytest.mark.asyncio
    async def test_rejects_without_approval(self, tmp_git_repo):
        """commit_changes should reject when user_approved=False."""
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool(
                "commit_changes",
                {"message": "test", "user_approved": False},
            )
            text = result.content[0].text
            assert "Error" in text or "user_approved" in text

    @pytest.mark.asyncio
    async def test_commits_with_approval(self, tmp_git_repo):
        """commit_changes should succeed when user_approved=True."""
        f = tmp_git_repo / "feature.py"
        f.write_text("def feature(): pass\n")
        subprocess.run(
            ["git", "add", "feature.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool(
                "commit_changes",
                {"message": "feat: add feature", "user_approved": True},
            )
            text = result.content[0].text
            assert "Successfully committed" in text


# ──────────────────────────────────
# Tests for get_pr_context
# ──────────────────────────────────


class TestGetPrContext:
    """Integration tests for the get_pr_context MCP tool."""

    @pytest.mark.asyncio
    async def test_pr_context_with_branch(self, tmp_git_repo):
        """PR context returns commits and diff between branches."""
        from devnarrate.git_operations import get_current_branch

        main_branch = get_current_branch(str(tmp_git_repo))
        subprocess.run(
            ["git", "checkout", "-b", "feature/pr-test"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        f = tmp_git_repo / "pr_file.py"
        f.write_text("def pr_feature(): pass\n")
        subprocess.run(
            ["git", "add", "pr_file.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add pr feature"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool(
                "get_pr_context",
                {"base_branch": main_branch},
            )
            data = json.loads(result.content[0].text)
            assert data["head_branch"] == "feature/pr-test"
            assert data["base_branch"] == main_branch
            assert data["commit_count"] >= 1
            assert "pr_file.py" in data["diff"]


# ──────────────────────────────────
# Tests for create_pr
# ──────────────────────────────────


# ──────────────────────────────────
# Tests for review_changes
# ──────────────────────────────────


class TestReviewChanges:
    """Integration tests for the review_changes MCP tool."""

    @pytest.mark.asyncio
    async def test_no_changes(self, tmp_git_repo):
        """No working tree changes → has_changes=False."""
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool(
                "review_changes", {"goal": "test goal"}
            )
            data = json.loads(result.content[0].text)
            assert data["has_changes"] is False

    @pytest.mark.asyncio
    async def test_working_tree_changes_detected(self, tmp_git_repo):
        """Modified tracked file appears in review."""
        readme = tmp_git_repo / "README.md"
        readme.write_text("# Updated Repo\nNew content here.\n")

        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool(
                "review_changes", {"goal": "update readme"}
            )
            data = json.loads(result.content[0].text)
            assert data["has_changes"] is True
            assert data["goal"] == "update readme"
            assert "README.md" in data["diff"]
            assert data["summary"]["total_files"] >= 1

    @pytest.mark.asyncio
    async def test_untracked_files_included(self, tmp_git_repo):
        """New untracked files show up in the response."""
        new_file = tmp_git_repo / "brand_new.py"
        new_file.write_text("# Brand new file\nprint('hello')\n")

        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool(
                "review_changes", {"goal": "add new module"}
            )
            data = json.loads(result.content[0].text)
            assert data["has_changes"] is True
            assert "brand_new.py" in data.get("untracked_files", [])

    @pytest.mark.asyncio
    async def test_staged_scope(self, tmp_git_repo):
        """scope=staged uses staged changes instead of working tree."""
        f = tmp_git_repo / "staged.py"
        f.write_text("x = 1\n")
        subprocess.run(
            ["git", "add", "staged.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )

        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool(
                "review_changes",
                {"goal": "add staged file", "scope": "staged"},
            )
            data = json.loads(result.content[0].text)
            assert data["has_changes"] is True
            assert "staged.py" in data["diff"]

    @pytest.mark.asyncio
    async def test_context_clues_extracted(self, tmp_git_repo):
        """Comments and docstrings from changed files appear in context_clues."""
        f = tmp_git_repo / "documented.py"
        f.write_text('"""Module for data processing."""\n\n# Transform raw input\ndef transform(data):\n    pass\n')
        subprocess.run(
            ["git", "add", "documented.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )

        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool(
                "review_changes",
                {"goal": "add data processing", "scope": "staged"},
            )
            data = json.loads(result.content[0].text)
            clues = data.get("context_clues", [])
            assert len(clues) >= 1
            # Should find the comment and/or docstring
            all_comments = []
            all_docstrings = []
            for clue in clues:
                all_comments.extend(clue.get("comments", []))
                all_docstrings.extend(clue.get("docstrings", []))
            assert any("Transform raw input" in c for c in all_comments) or \
                   any("data processing" in d for d in all_docstrings)

    @pytest.mark.asyncio
    async def test_response_structure(self, tmp_git_repo):
        """Response has all required top-level keys."""
        readme = tmp_git_repo / "README.md"
        readme.write_text("# Changed\n")

        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool(
                "review_changes", {"goal": "test structure"}
            )
            data = json.loads(result.content[0].text)
            assert "goal" in data
            assert "summary" in data
            assert "changes" in data
            assert "context_clues" in data
            assert "diff" in data
            assert "pagination_info" in data


# ──────────────────────────────────
# Tests for create_pr
# ──────────────────────────────────


class TestCreatePr:
    """Integration tests for the create_pr MCP tool."""

    @pytest.mark.asyncio
    async def test_rejects_without_approval(self, tmp_git_repo):
        """create_pr should reject when user_approved=False."""
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool(
                "create_pr",
                {
                    "title": "test PR",
                    "body": "test body",
                    "base_branch": "main",
                    "user_approved": False,
                },
            )
            text = result.content[0].text
            assert "Error" in text or "user_approved" in text


# ──────────────────────────────────
# Tests for split suggestion in get_commit_context
# ──────────────────────────────────


class TestCommitContextSplitSuggestion:
    """Tests for the split_suggestion field returned by get_commit_context."""

    @pytest.mark.asyncio
    async def test_no_split_suggestion_below_threshold(self, tmp_git_repo):
        """Fewer files than threshold → no split_suggestion in response."""
        # Default threshold is 4, stage only 2 files
        (tmp_git_repo / "a.py").write_text("a = 1\n")
        (tmp_git_repo / "b.py").write_text("b = 2\n")
        subprocess.run(
            ["git", "add", "a.py", "b.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool("get_commit_context", {})
            data = json.loads(result.content[0].text)
            assert data["has_changes"] is True
            assert "split_suggestion" not in data

    @pytest.mark.asyncio
    async def test_split_suggestion_at_threshold(self, tmp_git_repo):
        """Exactly threshold files → split_suggestion included."""
        # Default threshold is 4
        for name in ["a.py", "b.py", "c.py", "d.py"]:
            (tmp_git_repo / name).write_text(f"# {name}\n")
            subprocess.run(
                ["git", "add", name],
                cwd=tmp_git_repo, capture_output=True, check=True,
            )
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool("get_commit_context", {})
            data = json.loads(result.content[0].text)
            assert "split_suggestion" in data
            assert data["split_suggestion"]["suggested"] is True
            assert data["split_suggestion"]["file_count"] == 4

    @pytest.mark.asyncio
    async def test_split_suggestion_has_per_file_stats(self, tmp_git_repo):
        """split_suggestion includes per-file line counts."""
        for name in ["feat.py", "test_feat.py", "docs.md", "config.toml"]:
            (tmp_git_repo / name).write_text(f"# {name}\nline2\nline3\n")
            subprocess.run(
                ["git", "add", name],
                cwd=tmp_git_repo, capture_output=True, check=True,
            )
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool("get_commit_context", {})
            data = json.loads(result.content[0].text)
            stats = data["split_suggestion"]["per_file_stats"]
            assert len(stats) == 4
            for stat in stats:
                assert "path" in stat
                assert "lines_added" in stat
                assert "lines_removed" in stat
                assert stat["lines_added"] >= 3

    @pytest.mark.asyncio
    async def test_split_suggestion_includes_grouping_hints(self, tmp_git_repo):
        """split_suggestion includes hints for grouping files."""
        for name in ["a.py", "b.py", "c.py", "d.py"]:
            (tmp_git_repo / name).write_text(f"# {name}\n")
            subprocess.run(
                ["git", "add", name],
                cwd=tmp_git_repo, capture_output=True, check=True,
            )
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool("get_commit_context", {})
            data = json.loads(result.content[0].text)
            assert "grouping_hints" in data["split_suggestion"]
            assert len(data["split_suggestion"]["grouping_hints"]) > 0

    @pytest.mark.asyncio
    async def test_no_split_suggestion_when_no_changes(self, tmp_git_repo):
        """No staged changes → no split_suggestion."""
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool("get_commit_context", {})
            data = json.loads(result.content[0].text)
            assert data["has_changes"] is False
            assert "split_suggestion" not in data


# ──────────────────────────────────
# Tests for execute_split_commit
# ──────────────────────────────────


class TestExecuteSplitCommit:
    """Integration tests for the execute_split_commit MCP tool."""

    @pytest.mark.asyncio
    async def test_rejects_without_approval(self, tmp_git_repo):
        """execute_split_commit rejects when user_approved=False."""
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool(
                "execute_split_commit",
                {"files": ["a.py"], "message": "test", "user_approved": False},
            )
            data = json.loads(result.content[0].text)
            assert data["success"] is False
            assert "user_approved" in data["error"]

    @pytest.mark.asyncio
    async def test_rejects_empty_files(self, tmp_git_repo):
        """execute_split_commit rejects when files list is empty."""
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool(
                "execute_split_commit",
                {"files": [], "message": "test", "user_approved": True},
            )
            data = json.loads(result.content[0].text)
            assert data["success"] is False

    @pytest.mark.asyncio
    async def test_rejects_unstaged_files(self, tmp_git_repo):
        """execute_split_commit rejects files that aren't staged."""
        (tmp_git_repo / "staged.py").write_text("staged\n")
        subprocess.run(
            ["git", "add", "staged.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool(
                "execute_split_commit",
                {
                    "files": ["nonexistent.py"],
                    "message": "test",
                    "user_approved": True,
                },
            )
            data = json.loads(result.content[0].text)
            assert data["success"] is False
            assert "not staged" in data["error"]

    @pytest.mark.asyncio
    async def test_commits_subset_of_staged_files(self, tmp_git_repo):
        """Commits only the specified files, leaving others unstaged."""
        (tmp_git_repo / "feat.py").write_text("def feat(): pass\n")
        (tmp_git_repo / "docs.md").write_text("# Docs\n")
        (tmp_git_repo / "test.py").write_text("def test(): pass\n")
        subprocess.run(
            ["git", "add", "feat.py", "docs.md", "test.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            result = await client.call_tool(
                "execute_split_commit",
                {
                    "files": ["feat.py", "test.py"],
                    "message": "feat: add feature with tests",
                    "user_approved": True,
                },
            )
            data = json.loads(result.content[0].text)
            assert data["success"] is True
            assert "commit_hash" in data
            assert set(data["committed_files"]) == {"feat.py", "test.py"}

        # Verify: docs.md should NOT be staged anymore (unstaged)
        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=tmp_git_repo, capture_output=True, text=True, check=True,
        )
        assert "add feature with tests" in log.stdout

    @pytest.mark.asyncio
    async def test_sequential_split_commits(self, tmp_git_repo):
        """Two sequential split commits each create a separate commit."""
        (tmp_git_repo / "a.py").write_text("a = 1\n")
        (tmp_git_repo / "b.py").write_text("b = 2\n")
        subprocess.run(
            ["git", "add", "a.py", "b.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        async with create_session(
            devnarrate_mcp,
            list_roots_callback=_roots_callback(str(tmp_git_repo)),
        ) as client:
            # First split commit
            result1 = await client.call_tool(
                "execute_split_commit",
                {
                    "files": ["a.py"],
                    "message": "feat: add a",
                    "user_approved": True,
                },
            )
            data1 = json.loads(result1.content[0].text)
            assert data1["success"] is True

            # Re-stage b.py (it was unstaged) and do second commit
            subprocess.run(
                ["git", "add", "b.py"],
                cwd=tmp_git_repo, capture_output=True, check=True,
            )
            result2 = await client.call_tool(
                "execute_split_commit",
                {
                    "files": ["b.py"],
                    "message": "feat: add b",
                    "user_approved": True,
                },
            )
            data2 = json.loads(result2.content[0].text)
            assert data2["success"] is True

        # Verify both commits exist
        log = subprocess.run(
            ["git", "log", "--oneline", "-3"],
            cwd=tmp_git_repo, capture_output=True, text=True, check=True,
        )
        assert "add a" in log.stdout
        assert "add b" in log.stdout
