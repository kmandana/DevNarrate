"""Tests for the change_analyzer module."""

from devnarrate.change_analyzer import (
    ChangedFile,
    ContextClue,
    analyze_changes,
    extract_context_clues,
    parse_diff_stats,
)

# --- Sample diffs for testing ---

DIFF_NEW_FILE = """\
diff --git a/hello.py b/hello.py
new file mode 100644
index 0000000..e69de29
--- /dev/null
+++ b/hello.py
@@ -0,0 +1,5 @@
+\"\"\"Hello module.\"\"\"
+
+
+def greet(name):
+    return f"Hello, {name}!"
"""

DIFF_MODIFIED_FILE = """\
diff --git a/app.py b/app.py
index abc1234..def5678 100644
--- a/app.py
+++ b/app.py
@@ -1,3 +1,5 @@
 import os
+import sys
+# Added for path resolution

 def main():
"""

DIFF_DELETED_FILE = """\
diff --git a/old.py b/old.py
deleted file mode 100644
index abc1234..0000000
--- a/old.py
+++ /dev/null
@@ -1,3 +0,0 @@
-def legacy():
-    pass
-
"""

DIFF_MULTI_FILE = """\
diff --git a/auth/login.py b/auth/login.py
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/auth/login.py
@@ -0,0 +1,6 @@
+\"\"\"JWT authentication handler.\"\"\"
+
+# Implements RFC 7519 JWT standard
+def validate_token(token):
+    \"\"\"Validate and decode a JWT token.\"\"\"
+    pass
diff --git a/config.py b/config.py
index abc1234..def5678 100644
--- a/config.py
+++ b/config.py
@@ -1 +1,4 @@
 DB_HOST = "localhost"
+# Auth configuration
+JWT_SECRET = "changeme"
+JWT_EXPIRY = 3600
"""

DIFF_WITH_JS_COMMENTS = """\
diff --git a/src/utils.js b/src/utils.js
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/src/utils.js
@@ -0,0 +1,10 @@
+/**
+ * Utility functions for data processing.
+ * Handles date formatting and validation.
+ */
+
+// Format date to ISO string
+function formatDate(date) {
+  return date.toISOString();
+}
+
"""

DIFF_WITH_PYTHON_DOCSTRING = """\
diff --git a/reconcile.py b/reconcile.py
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/reconcile.py
@@ -0,0 +1,12 @@
+\"\"\"
+Reconciliation pipeline for payment processing.
+Compares bank statements with internal ledger.
+\"\"\"
+
+# Fuzzy matching for bank entries
+def match_entries(bank, ledger):
+    \"\"\"Match bank entries with ledger records using fuzzy logic.\"\"\"
+    pass
+
+# Exact match fallback
+def exact_match(a, b):
+    return a == b
"""

DIFF_NO_COMMENTS = """\
diff --git a/plain.py b/plain.py
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/plain.py
@@ -0,0 +1,3 @@
+x = 1
+y = 2
+z = x + y
"""


class TestParseDiffStats:
    """Tests for parse_diff_stats."""

    def test_new_file(self):
        result = parse_diff_stats(DIFF_NEW_FILE)
        assert len(result) == 1
        assert result[0].path == "hello.py"
        assert result[0].status == "added"
        assert result[0].lines_added == 5
        assert result[0].lines_removed == 0

    def test_modified_file(self):
        result = parse_diff_stats(DIFF_MODIFIED_FILE)
        assert len(result) == 1
        assert result[0].path == "app.py"
        assert result[0].status == "modified"
        assert result[0].lines_added == 2
        assert result[0].lines_removed == 0

    def test_deleted_file(self):
        result = parse_diff_stats(DIFF_DELETED_FILE)
        assert len(result) == 1
        assert result[0].path == "old.py"
        assert result[0].status == "deleted"
        assert result[0].lines_added == 0
        assert result[0].lines_removed == 3

    def test_multi_file(self):
        result = parse_diff_stats(DIFF_MULTI_FILE)
        assert len(result) == 2
        paths = [f.path for f in result]
        assert "auth/login.py" in paths
        assert "config.py" in paths

    def test_empty_diff(self):
        result = parse_diff_stats("")
        assert result == []

    def test_whitespace_only_diff(self):
        result = parse_diff_stats("   \n\n  ")
        assert result == []


class TestExtractContextClues:
    """Tests for extract_context_clues."""

    def test_python_comments(self):
        result = extract_context_clues(DIFF_MODIFIED_FILE)
        assert len(result) == 1
        assert result[0].file == "app.py"
        assert "Added for path resolution" in result[0].comments

    def test_js_comments_and_jsdoc(self):
        result = extract_context_clues(DIFF_WITH_JS_COMMENTS)
        assert len(result) == 1
        clue = result[0]
        assert clue.file == "src/utils.js"
        # Should find the // comment
        assert any("Format date to ISO string" in c for c in clue.comments)
        # Should find the JSDoc block
        assert any("Utility functions" in d for d in clue.docstrings)

    def test_python_docstrings(self):
        result = extract_context_clues(DIFF_WITH_PYTHON_DOCSTRING)
        assert len(result) == 1
        clue = result[0]
        assert clue.file == "reconcile.py"
        # Should find the module docstring
        assert any("Reconciliation pipeline" in d for d in clue.docstrings)
        # Should find inline comments
        assert any("Fuzzy matching" in c for c in clue.comments)

    def test_no_comments_returns_empty(self):
        result = extract_context_clues(DIFF_NO_COMMENTS)
        assert result == []

    def test_deleted_file_skipped(self):
        result = extract_context_clues(DIFF_DELETED_FILE)
        assert result == []

    def test_empty_diff(self):
        result = extract_context_clues("")
        assert result == []

    def test_multi_file_clues(self):
        result = extract_context_clues(DIFF_MULTI_FILE)
        files_with_clues = [c.file for c in result]
        # Both files have comments/docstrings
        assert "auth/login.py" in files_with_clues
        assert "config.py" in files_with_clues

    def test_filters_noise_comments(self):
        """Pragma, noqa, type: ignore, and short comments should be filtered."""
        diff = """\
diff --git a/noise.py b/noise.py
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/noise.py
@@ -0,0 +1,5 @@
+x = 1  # noqa
+y = 2  # type: ignore
+z = 3  # pragma: allowlist secret
+# ok
+# This is a meaningful comment about the algorithm
"""
        result = extract_context_clues(diff)
        assert len(result) == 1
        # Only the meaningful comment should survive
        assert len(result[0].comments) == 1
        assert "meaningful comment" in result[0].comments[0]


class TestAnalyzeChanges:
    """Tests for the analyze_changes orchestrator."""

    def test_full_pipeline(self):
        result = analyze_changes(DIFF_MULTI_FILE, [])
        assert 'summary' in result
        assert 'changes' in result
        assert 'context_clues' in result

        # Summary should have correct counts
        assert result['summary']['total_files'] == 2
        assert result['summary']['files_added'] == 1
        assert result['summary']['files_modified'] == 1

    def test_empty_diff(self):
        result = analyze_changes("", [])
        assert result['summary']['total_files'] == 0
        assert result['changes'] == []
        assert result['context_clues'] == []

    def test_includes_untracked_files(self):
        """Untracked files from file_stats should be included in summary."""
        file_stats = [
            {'path': 'new_file.py', 'status': 'added'},
            {'path': 'another.py', 'status': 'added'},
        ]
        result = analyze_changes("", file_stats)
        assert result['summary']['total_files'] == 2
        assert result['summary']['files_added'] == 2
        assert len(result['changes']) == 2

    def test_untracked_not_double_counted(self):
        """Files in both diff and file_stats shouldn't be counted twice."""
        file_stats = [
            {'path': 'auth/login.py', 'status': 'added'},  # also in diff
            {'path': 'extra.py', 'status': 'added'},        # only in file_stats
        ]
        result = analyze_changes(DIFF_MULTI_FILE, file_stats)
        # 2 from diff + 1 extra from file_stats = 3
        assert result['summary']['total_files'] == 3

    def test_output_is_serializable(self):
        """Output should be JSON-serializable (no dataclass objects)."""
        import json
        result = analyze_changes(DIFF_MULTI_FILE, [])
        # Should not raise
        json.dumps(result)
