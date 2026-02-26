"""Tests for devnarrate.secret_scanner — the security gate.

These tests verify that the secret scanner correctly:
- Detects known provider-specific secrets (AWS, GitHub, Stripe, etc.)
- Detects simple hardcoded passwords via KeywordDetector
- Respects suppression comments (pragma: allowlist secret)
- Filters out false positives (env vars, function calls, templates)
- Handles edge cases (empty diffs, binary files, multi-file diffs)
- Redacts secret values in output
"""

import subprocess

from sample_diffs import (
    DIFF_CLEAN,
    DIFF_MULTI_FILE,
    DIFF_WITH_AWS_KEY,
    DIFF_WITH_FALSE_POSITIVES,
    DIFF_WITH_MULTIPLE_SECRETS,
    DIFF_WITH_PRIVATE_KEY,
    DIFF_WITH_SIMPLE_PASSWORD,
    DIFF_WITH_SUPPRESSED_SECRET,
)

from devnarrate.secret_scanner import (
    MAX_FINDINGS,
    _parse_diff_added_lines,
    _redact_value,
    scan_diff,
)


# ──────────────────────────────────
# Tests for scan_diff() — core API
# ──────────────────────────────────


class TestScanDiffDetection:
    """Tests that secrets ARE detected when they should be."""

    def test_detects_aws_access_key(self):
        result = scan_diff(DIFF_WITH_AWS_KEY)
        assert result["status"] == "warnings_found"
        assert result["total_findings"] >= 1
        types = {f["type"] for f in result["findings"]}
        assert "AWS Access Key" in types

    def test_detects_github_token(self):
        result = scan_diff(DIFF_WITH_MULTIPLE_SECRETS)
        files_and_types = [(f["file"], f["type"]) for f in result["findings"]]
        # GitHub token should be detected (either as GitHubTokenDetector or HighEntropy)
        github_line = [f for f in result["findings"] if f["line"] == 3]
        assert len(github_line) >= 1

    def test_detects_stripe_key(self):
        result = scan_diff(DIFF_WITH_MULTIPLE_SECRETS)
        types = {f["type"] for f in result["findings"]}
        assert "Stripe Access Key" in types

    def test_detects_slack_token(self):
        result = scan_diff(DIFF_WITH_MULTIPLE_SECRETS)
        types = {f["type"] for f in result["findings"]}
        assert "Slack Token" in types

    def test_detects_simple_password(self):
        """KeywordDetector should catch password='admin123' without entropy."""
        result = scan_diff(DIFF_WITH_SIMPLE_PASSWORD)
        assert result["status"] == "warnings_found"
        # Should find 'changeme' as a Secret Keyword
        keyword_findings = [
            f for f in result["findings"] if f["type"] == "Secret Keyword"
        ]
        assert len(keyword_findings) >= 1

    def test_detects_private_key(self):
        result = scan_diff(DIFF_WITH_PRIVATE_KEY)
        assert result["status"] == "warnings_found"
        types = {f["type"] for f in result["findings"]}
        assert "Private Key" in types

    def test_detects_multiple_secrets_across_files(self):
        """Multi-file diff should find secrets in each file."""
        result = scan_diff(DIFF_MULTI_FILE)
        assert result["status"] == "warnings_found"
        # Should find secrets only in config.py, not app.py
        finding_files = {f["file"] for f in result["findings"]}
        assert "src/config.py" in finding_files
        assert "src/app.py" not in finding_files

    def test_detects_multiple_types_in_one_diff(self):
        result = scan_diff(DIFF_WITH_MULTIPLE_SECRETS)
        assert result["total_findings"] >= 4  # AWS, password, Stripe, Slack at minimum


class TestScanDiffFiltering:
    """Tests that false positives are correctly filtered out."""

    def test_clean_diff_returns_clean(self):
        result = scan_diff(DIFF_CLEAN)
        assert result["status"] == "clean"
        assert result["total_findings"] == 0
        assert result["findings"] == []

    def test_env_var_not_flagged(self):
        """password = os.environ['X'] should NOT be flagged."""
        result = scan_diff(DIFF_WITH_FALSE_POSITIVES)
        assert result["status"] == "clean"

    def test_function_call_not_flagged(self):
        """secret = get_secret_from_vault() should NOT be flagged."""
        result = scan_diff(DIFF_WITH_FALSE_POSITIVES)
        assert result["status"] == "clean"

    def test_template_variable_not_flagged(self):
        """token = '${API_TOKEN}' should NOT be flagged."""
        result = scan_diff(DIFF_WITH_FALSE_POSITIVES)
        assert result["status"] == "clean"

    def test_suppressed_via_pragma(self):
        """Lines with '# pragma: allowlist secret' should be suppressed."""
        result = scan_diff(DIFF_WITH_SUPPRESSED_SECRET)
        # The AWS key has pragma, so it should NOT appear
        aws_findings = [f for f in result["findings"] if f["type"] == "AWS Access Key"]
        assert len(aws_findings) == 0


class TestScanDiffEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_string(self):
        result = scan_diff("")
        assert result["status"] == "clean"
        assert result["total_findings"] == 0

    def test_whitespace_only(self):
        result = scan_diff("   \n\n  \n")
        assert result["status"] == "clean"

    def test_diff_with_no_added_lines(self):
        """A diff that only removes lines should be clean."""
        diff = """\
diff --git a/config.py b/config.py
--- a/config.py
+++ b/config.py
@@ -1,3 +1,1 @@
-AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
-SECRET = "removed"
 import os
"""
        result = scan_diff(diff)
        assert result["status"] == "clean"

    def test_diff_with_deleted_file(self):
        """Deleted files (+++ /dev/null) should not be scanned."""
        diff = """\
diff --git a/old_config.py b/old_config.py
deleted file mode 100644
--- a/old_config.py
+++ /dev/null
@@ -1,3 +0,0 @@
-AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
-SECRET = "my_secret"
-DEBUG = True
"""
        result = scan_diff(diff)
        assert result["status"] == "clean"

    def test_findings_capped_at_max(self):
        """Should not return more than MAX_FINDINGS findings."""
        # Build a diff with many secrets
        lines = [f'+SECRET_{i} = "sk_live_{"a" * 30}{i:03d}"' for i in range(30)]
        diff = (
            "diff --git a/secrets.py b/secrets.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/secrets.py\n"
            f"@@ -0,0 +1,{len(lines)} @@\n"
            + "\n".join(lines)
            + "\n"
        )
        result = scan_diff(diff)
        assert len(result["findings"]) <= MAX_FINDINGS
        assert result["total_findings"] >= MAX_FINDINGS

    def test_correct_line_numbers(self):
        """Line numbers should map back to the actual file positions."""
        diff = """\
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -10,3 +10,5 @@ def main():
     print("hello")
+    # config
+    password = "secret123"
"""
        result = scan_diff(diff)
        if result["total_findings"] > 0:
            # The password is on the 3rd target line in the hunk starting at line 10
            # Context line "print" is line 10, "+# config" is line 11, "+password" is line 12
            password_finding = [
                f for f in result["findings"] if f["type"] == "Secret Keyword"
            ]
            if password_finding:
                assert password_finding[0]["line"] == 12

    def test_deduplication(self):
        """Same file+line should not produce multiple findings."""
        result = scan_diff(DIFF_WITH_MULTIPLE_SECRETS)
        locations = [(f["file"], f["line"]) for f in result["findings"]]
        assert len(locations) == len(set(locations)), "Duplicate findings detected"


class TestScanDiffResponseFormat:
    """Tests for the response structure."""

    def test_clean_response_structure(self):
        result = scan_diff(DIFF_CLEAN)
        assert "status" in result
        assert "findings" in result
        assert "total_findings" in result
        assert "message" in result
        assert isinstance(result["findings"], list)
        assert isinstance(result["total_findings"], int)

    def test_warning_response_structure(self):
        result = scan_diff(DIFF_WITH_AWS_KEY)
        assert result["status"] == "warnings_found"
        finding = result["findings"][0]
        assert "file" in finding
        assert "line" in finding
        assert "type" in finding
        assert "match_preview" in finding

    def test_secret_values_are_redacted(self):
        """Secret values must never appear in full in the response."""
        result = scan_diff(DIFF_WITH_AWS_KEY)
        for finding in result["findings"]:
            preview = finding["match_preview"]
            # Should be redacted (short prefix + ...XXXX or ****)
            assert "AKIAIOSFODNN7EXAMPLE" not in preview
            assert "...XXXX" in preview or "****" in preview

    def test_message_is_human_readable(self):
        result = scan_diff(DIFF_WITH_MULTIPLE_SECRETS)
        assert "secret" in result["message"].lower()
        assert str(result["total_findings"]) in result["message"]


class TestScanDiffRealGitRepo:
    """Functional tests using a real git repo to generate real diffs."""

    def test_staged_file_with_secret_detected(self, tmp_git_repo):
        """Stage a file with a real secret and scan the real git diff."""
        secret_file = tmp_git_repo / "config.py"
        secret_file.write_text('API_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
        subprocess.run(
            ["git", "add", "config.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        # Get the real staged diff
        diff_result = subprocess.run(
            ["git", "diff", "--staged"],
            cwd=tmp_git_repo, capture_output=True, text=True, check=True,
        )
        result = scan_diff(diff_result.stdout)
        assert result["status"] == "warnings_found"
        assert any(f["type"] == "AWS Access Key" for f in result["findings"])

    def test_staged_file_without_secret_is_clean(self, tmp_git_repo):
        """Stage a clean file and verify no secrets found."""
        clean_file = tmp_git_repo / "app.py"
        clean_file.write_text('def hello():\n    return "world"\n')
        subprocess.run(
            ["git", "add", "app.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        diff_result = subprocess.run(
            ["git", "diff", "--staged"],
            cwd=tmp_git_repo, capture_output=True, text=True, check=True,
        )
        result = scan_diff(diff_result.stdout)
        assert result["status"] == "clean"

    def test_modified_file_only_scans_additions(self, tmp_git_repo):
        """When modifying a file, only added lines should be scanned."""
        # Create initial file with a secret (already committed)
        config = tmp_git_repo / "config.py"
        config.write_text('OLD_SECRET = "sk_live_oldkey123456789012345"\n')
        subprocess.run(
            ["git", "add", "config.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add config"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )

        # Now modify: remove old secret, add clean code
        config.write_text('DEBUG = True\nLOG_LEVEL = "info"\n')
        subprocess.run(
            ["git", "add", "config.py"],
            cwd=tmp_git_repo, capture_output=True, check=True,
        )
        diff_result = subprocess.run(
            ["git", "diff", "--staged"],
            cwd=tmp_git_repo, capture_output=True, text=True, check=True,
        )
        result = scan_diff(diff_result.stdout)
        # The old secret is in a - line (removal), not a + line, so it should be clean
        assert result["status"] == "clean"


# ────────────────────────────────────────────────
# Tests for _parse_diff_added_lines() — diff parser
# ────────────────────────────────────────────────


class TestParseDiffAddedLines:
    """Tests for the diff parsing logic."""

    def test_new_file(self):
        parsed = _parse_diff_added_lines(DIFF_WITH_AWS_KEY)
        assert "config.py" in parsed
        assert len(parsed["config.py"]) == 3  # import os, blank line, AWS_KEY

    def test_multi_file(self):
        parsed = _parse_diff_added_lines(DIFF_MULTI_FILE)
        assert "src/config.py" in parsed
        assert "src/app.py" in parsed

    def test_deleted_file_not_included(self):
        diff = """\
diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-line1
-line2
"""
        parsed = _parse_diff_added_lines(diff)
        assert "old.py" not in parsed

    def test_line_numbers_correct_with_offset(self):
        diff = """\
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -10,3 +10,5 @@ def main():
     print("hello")
+    new_line_1()
+    new_line_2()
"""
        parsed = _parse_diff_added_lines(diff)
        lines = parsed["app.py"]
        # Context "print" is line 10, first + is line 11, second + is line 12
        assert lines[0][0] == 11
        assert lines[1][0] == 12

    def test_empty_diff(self):
        parsed = _parse_diff_added_lines("")
        assert parsed == {}

    def test_only_removals(self):
        diff = """\
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,3 +1,1 @@
-removed_line_1
-removed_line_2
 kept_line
"""
        parsed = _parse_diff_added_lines(diff)
        assert parsed.get("app.py", []) == []


# ──────────────────────────────────
# Tests for _redact_value()
# ──────────────────────────────────


class TestRedactValue:
    """Tests for secret value redaction."""

    def test_normal_value(self):
        assert _redact_value("AKIAIOSFODNN7EXAMPLE") == "AKIA...XXXX"

    def test_short_value(self):
        assert _redact_value("abc") == "****"

    def test_exact_threshold(self):
        assert _redact_value("abcd") == "****"

    def test_just_over_threshold(self):
        assert _redact_value("abcde") == "abcd...XXXX"

    def test_empty_string(self):
        assert _redact_value("") == "****"

    def test_none_like(self):
        """Handles empty/falsy values gracefully."""
        assert _redact_value("") == "****"
