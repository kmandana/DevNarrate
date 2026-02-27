"""Change analyzer for DevNarrate.

Extracts structured metadata from diffs to help the host LLM
present code changes in a narrative format. The LLM reads the raw
diff directly for code understanding — this module provides
supplementary data: per-file stats and context clues (comments,
docstrings) that help the LLM infer goals for unmatched changes.
"""

import re
from dataclasses import dataclass, field, asdict

from unidiff import PatchSet


@dataclass
class ChangedFile:
    """Per-file change statistics."""
    path: str
    status: str  # added, modified, deleted, renamed
    lines_added: int = 0
    lines_removed: int = 0


@dataclass
class ContextClue:
    """Comments and docstrings extracted from added lines in a file."""
    file: str
    comments: list[str] = field(default_factory=list)
    docstrings: list[str] = field(default_factory=list)


# Regex patterns for single-line comments across common languages
# Matches: # comment, // comment, -- comment (SQL/Lua/Haskell)
_COMMENT_PATTERN = re.compile(r'^\s*(?:#|//|--)\s*(.+)')

# Regex for Python/JS docstring boundaries
_PY_DOCSTRING_OPEN = re.compile(r'^\s*(?:"""|\'\'\')\s*(.*)')
_PY_DOCSTRING_CLOSE = re.compile(r'(.*?)(?:"""|\'\'\')')
_JS_DOCSTRING_OPEN = re.compile(r'^\s*/\*\*\s*(.*)')
_JS_DOCSTRING_CLOSE = re.compile(r'(.*?)\*/')


def parse_diff_stats(diff_text: str) -> list[ChangedFile]:
    """Parse a unified diff into per-file change statistics.

    Args:
        diff_text: Raw unified diff text (from git diff).

    Returns:
        List of ChangedFile with path, status, and line counts.
    """
    if not diff_text or not diff_text.strip():
        return []

    try:
        patch = PatchSet(diff_text)
    except Exception:
        return []

    results = []
    for patched_file in patch:
        # Determine status
        if patched_file.is_added_file:
            status = 'added'
        elif patched_file.is_removed_file:
            status = 'deleted'
        elif patched_file.is_rename:
            status = 'renamed'
        else:
            status = 'modified'

        results.append(ChangedFile(
            path=patched_file.path,
            status=status,
            lines_added=patched_file.added,
            lines_removed=patched_file.removed,
        ))

    return results


def extract_context_clues(diff_text: str) -> list[ContextClue]:
    """Extract comments and docstrings from added lines in a diff.

    Only processes ADDED lines (lines starting with +) to capture
    context clues from new code. This gives the host LLM material
    to infer goals for changes that don't match a stated goal.

    Args:
        diff_text: Raw unified diff text.

    Returns:
        List of ContextClue per file with extracted comments and docstrings.
    """
    if not diff_text or not diff_text.strip():
        return []

    try:
        patch = PatchSet(diff_text)
    except Exception:
        return []

    results = []

    for patched_file in patch:
        if patched_file.is_removed_file:
            continue

        comments = []
        docstrings = []

        # Collect all added lines
        added_lines = []
        for hunk in patched_file:
            for line in hunk:
                if line.is_added:
                    added_lines.append(line.value.rstrip('\n'))

        # Extract single-line comments
        for line_text in added_lines:
            match = _COMMENT_PATTERN.match(line_text)
            if match:
                comment = match.group(1).strip()
                # Filter out noise: very short comments, shebangs, pragma
                if (len(comment) > 3
                        and not comment.startswith('!')
                        and 'pragma' not in comment.lower()
                        and 'noqa' not in comment.lower()
                        and 'type: ignore' not in comment.lower()):
                    comments.append(comment)

        # Extract docstrings (Python triple-quote and JS /** */ style)
        _extract_docstrings(added_lines, docstrings)

        if comments or docstrings:
            results.append(ContextClue(
                file=patched_file.path,
                comments=comments,
                docstrings=docstrings,
            ))

    return results


def _extract_docstrings(lines: list[str], docstrings: list[str]) -> None:
    """Extract docstrings from a list of source lines.

    Handles Python triple-quote strings and JS/TS /** */ blocks.
    Modifies the docstrings list in place.

    Args:
        lines: Source code lines to scan.
        docstrings: List to append extracted docstring text to.
    """
    i = 0
    while i < len(lines):
        line = lines[i]

        # Check for Python triple-quote docstring
        py_match = _PY_DOCSTRING_OPEN.match(line)
        if py_match:
            # Check if it's a single-line docstring (opens and closes on same line)
            # Count triple-quote occurrences
            triple_double = line.count('"""')
            triple_single = line.count("'''")
            if triple_double >= 2 or triple_single >= 2:
                # Single-line docstring: """text""" or '''text'''
                # Extract text between the quotes
                inner = line.strip()
                for quote in ('"""', "'''"):
                    if inner.startswith(quote) and inner.endswith(quote) and len(inner) > 6:
                        text = inner[3:-3].strip()
                        if text and len(text) > 3:
                            docstrings.append(text)
                        break
                i += 1
                continue

            # Multi-line docstring
            doc_lines = [py_match.group(1)]
            i += 1
            while i < len(lines):
                close_match = _PY_DOCSTRING_CLOSE.match(lines[i])
                if close_match:
                    doc_lines.append(close_match.group(1))
                    break
                doc_lines.append(lines[i].strip())
                i += 1
            text = ' '.join(part.strip() for part in doc_lines if part.strip())
            if text and len(text) > 3:
                docstrings.append(text)
            i += 1
            continue

        # Check for JS/TS /** */ docstring
        js_match = _JS_DOCSTRING_OPEN.match(line)
        if js_match:
            doc_lines = [js_match.group(1)]
            i += 1
            while i < len(lines):
                close_match = _JS_DOCSTRING_CLOSE.match(lines[i])
                if close_match:
                    doc_lines.append(close_match.group(1).strip().lstrip('* '))
                    break
                # Strip leading * from JSDoc lines
                stripped = lines[i].strip().lstrip('* ')
                if stripped:
                    doc_lines.append(stripped)
                i += 1
            text = ' '.join(part.strip() for part in doc_lines if part.strip())
            if text and len(text) > 3:
                docstrings.append(text)
            i += 1
            continue

        i += 1


def analyze_changes(diff_text: str, file_stats: list[dict]) -> dict:
    """Analyze changes and produce structured metadata for the host LLM.

    This is the top-level orchestrator. It parses the diff for per-file
    stats and extracts context clues (comments/docstrings) that help
    the LLM infer goals for unmatched changes.

    The raw diff is NOT included in the output — the caller (server.py)
    adds it to the response separately, possibly with pagination.

    Args:
        diff_text: Raw unified diff text.
        file_stats: File stats from git_operations (list of {path, status} dicts).

    Returns:
        Dict with summary and context_clues, ready for JSON serialization.
    """
    # Parse diff for per-file line counts
    diff_stats = parse_diff_stats(diff_text)

    # Build summary
    total_added = sum(f.lines_added for f in diff_stats)
    total_removed = sum(f.lines_removed for f in diff_stats)

    files_by_status = {}
    for f in diff_stats:
        files_by_status[f.status] = files_by_status.get(f.status, 0) + 1

    # Include untracked files from file_stats that aren't in the diff
    diff_paths = {f.path for f in diff_stats}
    untracked = [f for f in file_stats if f['path'] not in diff_paths]
    if untracked:
        files_by_status['added'] = files_by_status.get('added', 0) + len(untracked)

    summary = {
        'total_files': len(diff_stats) + len(untracked),
        'files_added': files_by_status.get('added', 0),
        'files_modified': files_by_status.get('modified', 0),
        'files_deleted': files_by_status.get('deleted', 0),
        'files_renamed': files_by_status.get('renamed', 0),
        'total_lines_added': total_added,
        'total_lines_removed': total_removed,
    }

    # Per-file stats with line counts
    changes = [asdict(f) for f in diff_stats]
    # Add untracked files (no line counts available from diff)
    for f in untracked:
        changes.append({
            'path': f['path'],
            'status': 'added',
            'lines_added': 0,
            'lines_removed': 0,
        })

    # Extract context clues
    context_clues = [asdict(c) for c in extract_context_clues(diff_text)]

    return {
        'summary': summary,
        'changes': changes,
        'context_clues': context_clues,
    }
