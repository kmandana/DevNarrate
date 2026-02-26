"""Secret scanning for staged diffs using detect-secrets.

Scans added lines in git diffs for potential secrets (API keys, passwords,
tokens, private keys, etc.) using Yelp's detect-secrets library.
"""

import os
import re
import tempfile
from typing import Optional

from detect_secrets.core.scan import scan_file
from detect_secrets.settings import transient_settings

# Maximum number of findings to return (avoid flooding the MCP response)
MAX_FINDINGS = 20

# detect-secrets plugin configuration
# We enable provider-specific detectors + KeywordDetector (catches password="admin123")
# + entropy detectors for unknown token formats
SCANNER_CONFIG = {
    "plugins_used": [
        # Provider-specific detectors (high confidence, ~0% false positive)
        {"name": "AWSKeyDetector"},
        {"name": "GitHubTokenDetector"},
        {"name": "GitLabTokenDetector"},
        {"name": "StripeDetector"},
        {"name": "SlackDetector"},
        {"name": "SendGridDetector"},
        {"name": "NpmDetector"},
        {"name": "PypiTokenDetector"},
        {"name": "TwilioKeyDetector"},
        {"name": "MailchimpDetector"},
        {"name": "OpenAIDetector"},
        {"name": "PrivateKeyDetector"},
        {"name": "BasicAuthDetector"},
        {"name": "JwtTokenDetector"},
        {"name": "ArtifactoryDetector"},
        {"name": "AzureStorageKeyDetector"},
        {"name": "CloudantDetector"},
        {"name": "DiscordBotTokenDetector"},
        {"name": "IbmCloudIamDetector"},
        {"name": "IbmCosHmacDetector"},
        {"name": "SquareOAuthDetector"},
        {"name": "TelegramBotTokenDetector"},
        # Keyword-based detector (catches password="admin123", secret="changeme", etc.)
        {"name": "KeywordDetector"},
        # Entropy-based detectors (catches unknown high-entropy tokens)
        {"name": "Base64HighEntropyString", "limit": 4.5},
        {"name": "HexHighEntropyString", "limit": 3.0},
    ],
    # Filters that reduce false positives while scanning diff-extracted lines
    # We OMIT: is_invalid_file, is_non_text_file, is_lock_file, is_swagger_file
    # because we're scanning temp files, not the original repo files
    "filters_used": [
        {"path": "detect_secrets.filters.allowlist.is_line_allowlisted"},
        {"path": "detect_secrets.filters.heuristic.is_indirect_reference"},
        {"path": "detect_secrets.filters.heuristic.is_prefixed_with_dollar_sign"},
        {"path": "detect_secrets.filters.heuristic.is_templated_secret"},
        {"path": "detect_secrets.filters.heuristic.is_potential_uuid"},
        {"path": "detect_secrets.filters.heuristic.is_not_alphanumeric_string"},
        {"path": "detect_secrets.filters.heuristic.is_likely_id_string"},
        {"path": "detect_secrets.filters.heuristic.is_sequential_string"},
    ],
}


def _parse_diff_added_lines(diff_text: str) -> dict[str, list[tuple[int, str]]]:
    """Parse a unified diff and extract only added lines per file.

    Args:
        diff_text: Raw `git diff --staged` output

    Returns:
        Dict mapping file paths to lists of (line_number, line_content) tuples.
        Line numbers are from the new file (target side of the diff).
    """
    files: dict[str, list[tuple[int, str]]] = {}
    current_file: Optional[str] = None
    current_line = 0

    for line in diff_text.split('\n'):
        if line.startswith('+++ b/'):
            current_file = line[6:]
            if current_file not in files:
                files[current_file] = []
        elif line.startswith('+++ /dev/null'):
            # File being deleted — skip
            current_file = None
        elif line.startswith('@@'):
            # Parse hunk header: @@ -old,count +new,count @@
            m = re.search(r'\+(\d+)', line)
            if m:
                current_line = int(m.group(1))
        elif line.startswith('+') and not line.startswith('+++'):
            # Added line
            if current_file is not None:
                files[current_file].append((current_line, line[1:]))  # strip leading +
                current_line += 1
        elif line.startswith('-') or line.startswith('---'):
            # Removed line or diff header — don't increment line counter
            pass
        else:
            # Context line — increment line counter
            if current_file is not None:
                current_line += 1

    return files


def _redact_value(value: str, show_chars: int = 4) -> str:
    """Redact a secret value, showing only the first few characters.

    Args:
        value: The secret value to redact
        show_chars: Number of characters to show

    Returns:
        Redacted string like "AKIA...XXXX"
    """
    if not value or len(value) <= show_chars:
        return "****"
    return value[:show_chars] + "...XXXX"


def scan_diff(diff_text: str) -> dict:
    """Scan added lines in a staged diff for potential secrets.

    Uses detect-secrets with 27 detectors including:
    - Provider-specific: AWS, GitHub, GitLab, Stripe, Slack, SendGrid, NPM, PyPI, etc.
    - Keyword-based: catches password="admin123", secret="changeme", etc.
    - Entropy-based: catches unknown high-entropy tokens

    Only scans added lines (+) — secrets in removed lines are already in git history
    and are not our concern for the current commit.

    Args:
        diff_text: Raw `git diff --staged` output

    Returns:
        Dict with:
        - status: "clean" or "warnings_found"
        - findings: list of detected secrets (capped at MAX_FINDINGS)
        - total_findings: total count before capping
        - message: human-readable summary
    """
    if not diff_text or not diff_text.strip():
        return {
            "status": "clean",
            "findings": [],
            "total_findings": 0,
            "message": "No changes to scan.",
        }

    # Parse diff to extract added lines per file
    parsed_files = _parse_diff_added_lines(diff_text)

    if not parsed_files:
        return {
            "status": "clean",
            "findings": [],
            "total_findings": 0,
            "message": "No added lines to scan.",
        }

    all_findings = []
    # Track (file, line) to deduplicate when multiple detectors match the same line
    seen_locations: set[tuple[str, int]] = set()

    with transient_settings(SCANNER_CONFIG):
        for filepath, lines in parsed_files.items():
            if not lines:
                continue

            # Build line number mapping: temp_file_line -> real_file_line
            line_map: dict[int, int] = {}
            content_lines: list[str] = []
            for i, (real_line_no, line_content) in enumerate(lines):
                content_lines.append(line_content)
                line_map[i + 1] = real_line_no  # detect-secrets uses 1-indexed lines

            # Write added lines to a temp file for scanning
            # Use the original file extension so detect-secrets applies correct parsing
            _, ext = os.path.splitext(filepath)
            tmp_fd, tmppath = tempfile.mkstemp(suffix=ext or '.txt', prefix='devnarrate_')

            try:
                with os.fdopen(tmp_fd, 'w') as f:
                    f.write('\n'.join(content_lines) + '\n')

                for secret in scan_file(tmppath):
                    real_line = line_map.get(secret.line_number, secret.line_number)
                    location_key = (filepath, real_line)

                    # Deduplicate: if we already have a finding for this file+line,
                    # skip it (multiple detectors can flag the same secret)
                    if location_key in seen_locations:
                        continue
                    seen_locations.add(location_key)

                    all_findings.append({
                        "file": filepath,
                        "line": real_line,
                        "type": secret.type,
                        "match_preview": _redact_value(
                            secret.secret_value if secret.secret_value else ""
                        ),
                    })
            finally:
                # Clean up temp file
                try:
                    os.unlink(tmppath)
                except OSError:
                    pass

    total = len(all_findings)
    capped = all_findings[:MAX_FINDINGS]

    if total == 0:
        return {
            "status": "clean",
            "findings": [],
            "total_findings": 0,
            "message": "No secrets detected in staged changes.",
        }

    message = f"{total} potential secret{'s' if total > 1 else ''} detected in staged changes. Review before committing."
    if total > MAX_FINDINGS:
        message += f" (showing first {MAX_FINDINGS} of {total})"

    return {
        "status": "warnings_found",
        "findings": capped,
        "total_findings": total,
        "message": message,
    }
