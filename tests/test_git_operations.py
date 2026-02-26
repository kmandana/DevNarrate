"""Tests for devnarrate.git_operations — core git subprocess wrappers.

These tests verify that the git operations correctly:
- Get staged diffs and file stats from real git repos
- Paginate large diffs by token count
- Execute commits and report the hash
- Work with branches (current branch, branch diff, branch commits)
- Detect git platform from remote URLs
- Handle edge cases (empty repos, no staged changes, etc.)
"""

import subprocess

import pytest

from devnarrate.git_operations import (
    count_tokens,
    detect_git_platform,
    execute_commit,
    get_branch_commits,
    get_branch_diff,
    get_branch_file_stats,
    get_current_branch,
    get_diff,
    get_file_stats,
    paginate_diff,
)


# ──────────────────────────────────
# Tests for count_tokens()
# ──────────────────────────────────


class TestCountTokens:
    """Tests for the token counting utility."""

    def test_empty_string(self):
        assert count_tokens("") == 0

    def test_simple_text(self):
        tokens = count_tokens("Hello, world!")
        assert isinstance(tokens, int)
        assert tokens > 0

    def test_longer_text_has_more_tokens(self):
        short = count_tokens("hello")
        long = count_tokens("hello world this is a longer sentence with many more words")
        assert long > short

    def test_code_text(self):
        code = 'def hello():\n    return "world"\n'
        tokens = count_tokens(code)
        assert tokens > 0


# ──────────────────────────────────
# Tests for paginate_diff()
# ──────────────────────────────────


class TestPaginateDiff:
    """Tests for diff pagination logic."""

    def test_empty_diff(self):
        result = paginate_diff("", None)
        assert result["diff_chunk"] == ""
        assert result["next_cursor"] is None
        assert result["chunk_info"]["total_lines"] == 0

    def test_small_diff_fits_in_one_chunk(self):
        diff = "line1\nline2\nline3\n"
        result = paginate_diff(diff, None, max_tokens=1000)
        assert result["next_cursor"] is None
        assert "line1" in result["diff_chunk"]
        assert "line3" in result["diff_chunk"]

    def test_large_diff_paginates(self):
        # Create a diff large enough to exceed a small token limit
        lines = [f"+variable_{i} = 'value_{i}'" for i in range(200)]
        diff = "\n".join(lines)
        result = paginate_diff(diff, None, max_tokens=50)
        # Should NOT return all lines
        assert result["next_cursor"] is not None
        # Chunk should have some content
        assert len(result["diff_chunk"]) > 0

    def test_cursor_continues_from_offset(self):
        lines = [f"line_{i}" for i in range(100)]
        diff = "\n".join(lines)
        # First page
        page1 = paginate_diff(diff, None, max_tokens=50)
        assert page1["next_cursor"] is not None
        # Second page starts where first left off
        page2 = paginate_diff(diff, page1["next_cursor"], max_tokens=50)
        assert page2["chunk_info"]["start_line"] == int(page1["next_cursor"])

    def test_invalid_cursor_starts_from_zero(self):
        result = paginate_diff("line1\nline2", "invalid", max_tokens=1000)
        assert result["chunk_info"]["start_line"] == 0

    def test_chunk_info_has_required_fields(self):
        result = paginate_diff("some diff text", None)
        info = result["chunk_info"]
        assert "start_line" in info
        assert "end_line" in info
        assert "total_lines" in info
        assert "chunk_tokens" in info
        assert "total_tokens" in info

    def test_chunk_percentage_high_for_small_diff(self):
        result = paginate_diff("hello world", None, max_tokens=10000)
        # Entire diff fits in one chunk, so percentage should be >= 100
        assert result["chunk_info"]["chunk_percentage"] >= 100.0
        assert result["next_cursor"] is None


# ──────────────────────────────────
# Tests for get_diff() — real git
# ──────────────────────────────────


class TestGetDiff:
    """Tests using real temporary git repos."""

    def test_staged_changes_appear_in_diff(self, tmp_git_repo):
        """Staged file content appears in the diff output."""
        f = tmp_git_repo / "new_file.py"
        f.write_text('print("hello")\n')
        subprocess.run(
            ["git", "add", "new_file.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        diff = get_diff(str(tmp_git_repo))
        assert "new_file.py" in diff
        assert '+print("hello")' in diff

    def test_no_staged_changes_returns_empty(self, tmp_git_repo):
        """No staged changes → empty diff."""
        diff = get_diff(str(tmp_git_repo))
        assert diff.strip() == ""

    def test_unstaged_changes_not_in_diff(self, tmp_git_repo):
        """Unstaged (only modified, not added) changes don't appear."""
        f = tmp_git_repo / "README.md"
        f.write_text("# Modified but not staged\n")
        diff = get_diff(str(tmp_git_repo))
        assert diff.strip() == ""

    def test_only_additions_shown(self, tmp_git_repo):
        """Only the added lines (with +) should appear for new files."""
        f = tmp_git_repo / "code.py"
        f.write_text("x = 1\ny = 2\n")
        subprocess.run(
            ["git", "add", "code.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        diff = get_diff(str(tmp_git_repo))
        assert "+x = 1" in diff
        assert "+y = 2" in diff


# ──────────────────────────────────
# Tests for get_file_stats()
# ──────────────────────────────────


class TestGetFileStats:
    """Tests for staged file status parsing."""

    def test_new_file_is_added(self, tmp_git_repo):
        f = tmp_git_repo / "new.py"
        f.write_text("x = 1\n")
        subprocess.run(
            ["git", "add", "new.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        stats = get_file_stats(str(tmp_git_repo))
        paths = {f["path"] for f in stats["files"]}
        statuses = {f["path"]: f["status"] for f in stats["files"]}
        assert "new.py" in paths
        assert statuses["new.py"] == "added"

    def test_modified_file(self, tmp_git_repo):
        # README.md already exists from initial commit
        readme = tmp_git_repo / "README.md"
        readme.write_text("# Updated\n")
        subprocess.run(
            ["git", "add", "README.md"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        stats = get_file_stats(str(tmp_git_repo))
        statuses = {f["path"]: f["status"] for f in stats["files"]}
        assert statuses["README.md"] == "modified"

    def test_deleted_file(self, tmp_git_repo):
        subprocess.run(
            ["git", "rm", "README.md"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        stats = get_file_stats(str(tmp_git_repo))
        statuses = {f["path"]: f["status"] for f in stats["files"]}
        assert statuses["README.md"] == "deleted"

    def test_no_staged_changes_empty(self, tmp_git_repo):
        stats = get_file_stats(str(tmp_git_repo))
        assert stats["files"] == []

    def test_unstaged_file_not_listed(self, tmp_git_repo):
        f = tmp_git_repo / "unstaged.py"
        f.write_text("x = 1\n")
        # Don't git add
        stats = get_file_stats(str(tmp_git_repo))
        paths = {f["path"] for f in stats["files"]}
        assert "unstaged.py" not in paths


# ──────────────────────────────────
# Tests for execute_commit()
# ──────────────────────────────────


class TestExecuteCommit:
    """Tests for actual git commit execution."""

    def test_commit_succeeds(self, tmp_git_repo):
        f = tmp_git_repo / "feature.py"
        f.write_text("def feature(): pass\n")
        subprocess.run(
            ["git", "add", "feature.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        result = execute_commit(str(tmp_git_repo), "feat: add feature")
        assert "Successfully committed" in result
        # Should contain 7-char hash
        assert len(result.split()[3]) == 7

    def test_commit_message_preserved(self, tmp_git_repo):
        f = tmp_git_repo / "test.py"
        f.write_text("pass\n")
        subprocess.run(
            ["git", "add", "test.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        execute_commit(str(tmp_git_repo), "test: my custom message")
        # Verify the commit message in git log
        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=tmp_git_repo, capture_output=True, text=True, check=True,
        )
        assert "my custom message" in log.stdout

    def test_commit_fails_with_nothing_staged(self, tmp_git_repo):
        with pytest.raises(subprocess.CalledProcessError):
            execute_commit(str(tmp_git_repo), "empty commit")


# ──────────────────────────────────
# Tests for branch operations
# ──────────────────────────────────


class TestBranchOperations:
    """Tests for branch-related operations."""

    def test_get_current_branch(self, tmp_git_repo):
        # Default branch after git init
        branch = get_current_branch(str(tmp_git_repo))
        assert isinstance(branch, str)
        assert len(branch) > 0

    def test_get_current_branch_on_feature(self, tmp_git_repo):
        subprocess.run(
            ["git", "checkout", "-b", "feature/test"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        branch = get_current_branch(str(tmp_git_repo))
        assert branch == "feature/test"

    def test_branch_diff(self, tmp_git_repo):
        """Branch diff shows changes between main and feature branch."""
        main_branch = get_current_branch(str(tmp_git_repo))
        # Create feature branch with a new file
        subprocess.run(
            ["git", "checkout", "-b", "feature/new"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        f = tmp_git_repo / "feature.py"
        f.write_text("def new_feature(): pass\n")
        subprocess.run(
            ["git", "add", "feature.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add feature"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        diff = get_branch_diff(str(tmp_git_repo), main_branch, "feature/new")
        assert "feature.py" in diff
        assert "+def new_feature(): pass" in diff

    def test_branch_commits(self, tmp_git_repo):
        """Branch commits returns commits unique to the feature branch."""
        main_branch = get_current_branch(str(tmp_git_repo))
        subprocess.run(
            ["git", "checkout", "-b", "feature/commits"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        # Make two commits on feature branch
        for i in range(2):
            f = tmp_git_repo / f"file_{i}.py"
            f.write_text(f"# file {i}\n")
            subprocess.run(
                ["git", "add", f"file_{i}.py"],
                cwd=tmp_git_repo, capture_output=True, check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", f"commit {i}"],
                cwd=tmp_git_repo, capture_output=True, check=True,
            )
        commits = get_branch_commits(str(tmp_git_repo), main_branch, "feature/commits")
        assert len(commits) == 2
        messages = [c["message"] for c in commits]
        assert "commit 0" in messages
        assert "commit 1" in messages

    def test_branch_file_stats(self, tmp_git_repo):
        """Branch file stats shows files changed between branches."""
        main_branch = get_current_branch(str(tmp_git_repo))
        subprocess.run(
            ["git", "checkout", "-b", "feature/stats"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        f = tmp_git_repo / "stats.py"
        f.write_text("x = 1\n")
        subprocess.run(
            ["git", "add", "stats.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add stats"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        stats = get_branch_file_stats(str(tmp_git_repo), main_branch, "feature/stats")
        paths = {f["path"] for f in stats["files"]}
        assert "stats.py" in paths


# ──────────────────────────────────
# Tests for detect_git_platform()
# ──────────────────────────────────


class TestDetectGitPlatform:
    """Tests for git platform detection from remote URLs."""

    def test_github_ssh(self, tmp_git_repo):
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:user/repo.git"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        assert detect_git_platform(str(tmp_git_repo)) == "github"

    def test_github_https(self, tmp_git_repo):
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/user/repo.git"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        assert detect_git_platform(str(tmp_git_repo)) == "github"

    def test_gitlab_ssh(self, tmp_git_repo):
        subprocess.run(
            ["git", "remote", "add", "origin", "git@gitlab.com:user/repo.git"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        assert detect_git_platform(str(tmp_git_repo)) == "gitlab"

    def test_bitbucket(self, tmp_git_repo):
        subprocess.run(
            ["git", "remote", "add", "origin", "git@bitbucket.org:user/repo.git"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        assert detect_git_platform(str(tmp_git_repo)) == "bitbucket"

    def test_no_remote_returns_unknown(self, tmp_git_repo):
        assert detect_git_platform(str(tmp_git_repo)) == "unknown"

    def test_custom_remote_returns_unknown(self, tmp_git_repo):
        subprocess.run(
            ["git", "remote", "add", "origin", "https://git.mycompany.com/repo.git"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        assert detect_git_platform(str(tmp_git_repo)) == "unknown"
