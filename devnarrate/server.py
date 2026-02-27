#!/usr/bin/env python3
"""
DevNarrate MCP Server

An MCP server that helps developers with:
- Writing commit messages
- Generating PR descriptions
- Posting CI/CD results to Slack
- Sharing development updates to Slack
"""

import json
import subprocess
from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import change_analyzer
from . import git_operations
from . import secret_scanner

# Create MCP server instance
mcp = FastMCP("devnarrate")


@mcp.tool()
async def get_commit_context(
    cursor: Optional[str] = None,
    max_diff_tokens: int = 20000,
    repo_path: Optional[str] = None
) -> str:
    """REQUIRED FIRST STEP: Get git diff and file changes to analyze before writing a commit message.

    IMPORTANT: You MUST call this tool FIRST before generating any commit message.
    Never write a commit message without first seeing the actual git diff from this tool.

    This tool ONLY shows STAGED changes. We intentionally do not support unstaged changes
    to ensure users have explicit control over what gets committed and prevent accidental commits.

    CRITICAL: If the diff is empty and there are no files:
    1. STOP immediately - do NOT proceed with generating a commit message
    2. Tell the user: "No staged changes found. Please stage the files you want to commit first using: git add <file1> <file2>"
    3. DO NOT attempt to stage files automatically
    4. Wait for the user to stage their changes

    Returns file changes and diff output with TOKEN-BASED pagination (MCP limit: 25k tokens).
    Large diffs are automatically paginated to stay under the token limit.

    ANALYZING THE RESPONSE - follow these steps in order:

    1. SECRET SCAN (automated): Check secret_scan.status FIRST.
       - If "warnings_found": STOP and warn the user about each finding.
         Show the file, line number, type, and redacted preview for each finding.
         Recommend removing the secret before committing.
         Do NOT proceed to generate a commit message until the user acknowledges
         or explicitly chooses to proceed despite the warnings.
       - If "clean": proceed to step 2.

    2. SECRET SCAN (your review): Even if the automated scan is clean, briefly review
       the diff yourself for anything the regex-based scanner might miss:
       - Hardcoded credentials or secrets in unusual formats
       - Internal URLs, IP addresses, or hostnames that shouldn't be committed
       - Sensitive configuration values (database hosts, internal endpoints)
       - Comments containing passwords or access instructions
       If you spot anything suspicious, warn the user before proceeding.

    3. COMMIT MESSAGE: After confirming no secrets (or user acknowledgment), generate
       a commit message following:
       - 50/72 rule: 50 char subject line, 72 char body lines
       - Conventional commits format: type(scope): description
       - DO NOT include AI signatures, attribution, or "Generated with" footers

    Args:
        cursor: Pagination cursor for large diffs (optional, returned as next_cursor)
        max_diff_tokens: Maximum tokens per response (default: 20000, safe under 25k limit)
        repo_path: Path to git repository (optional, defaults to Claude's working directory)

    Returns:
        JSON string with:
        - has_changes: boolean - True if there are any staged changes to commit
        - files: list of changed files with status
        - secret_scan: results of secret detection on added lines
        - diff: the diff chunk (paginated)
        - next_cursor: pagination cursor for next chunk (if any)
        - pagination_info: token counts and chunk info
        - commit_format_guide: formatting rules for commit messages
    """
    try:
        # Get working directory from MCP roots if repo_path not provided
        if repo_path is None:
            context = mcp.get_context()
            roots_result = await context.session.list_roots()
            if roots_result.roots:
                repo_path = roots_result.roots[0].uri.path
            else:
                return json.dumps({'error': 'No repository path provided and no roots available'})

        # Get file stats (staged changes only)
        stats = git_operations.get_file_stats(repo_path)

        # Get full diff (staged changes only)
        diff_output = git_operations.get_diff(repo_path)

        # Paginate diff by token count
        paginated = git_operations.paginate_diff(diff_output, cursor, max_diff_tokens)

        # Check if there are any changes - trust the diff as source of truth
        # If git diff --staged is empty, there's nothing to commit
        has_changes = bool(diff_output.strip())

        # Scan for secrets in added lines (only on first page, not paginated follow-ups)
        if has_changes and cursor is None:
            secret_scan = secret_scanner.scan_diff(diff_output)
        else:
            secret_scan = {
                'status': 'clean',
                'findings': [],
                'total_findings': 0,
                'message': 'No changes to scan.' if not has_changes else 'Secret scan performed on first page only.',
            }

        result = {
            'repository': repo_path,
            'has_changes': has_changes,
            'files': stats['files'],
            'secret_scan': secret_scan,
            'diff': paginated['diff_chunk'],
            'next_cursor': paginated['next_cursor'],
            'pagination_info': paginated['chunk_info'],
            'commit_format_guide': {
                'subject_line': 'Max 50 characters',
                'body_line_length': 'Max 72 characters per line',
                'format': 'type(scope): description\\n\\nBody paragraphs...\\n\\nFooter',
                'types': ['feat', 'fix', 'docs', 'style', 'refactor', 'test', 'chore'],
                'important': 'DO NOT include AI signatures, attribution, or "Generated with" footers in the commit message'
            }
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({'error': str(e)})


@mcp.tool()
async def commit_changes(
    message: str,
    user_approved: bool,
    repo_path: Optional[str] = None
) -> str:
    """Execute git commit with a user-approved commit message.

    CRITICAL WORKFLOW - YOU MUST FOLLOW THESE STEPS IN ORDER:
    1. Call get_commit_context to get the diff
    2. Generate a commit message based on the actual diff
    3. SHOW the generated commit message to the user in your response
    4. ASK the user: "Should I proceed with this commit?" and WAIT for their response
    5. ONLY call this tool AFTER the user explicitly approves (says "yes", "proceed", "commit it", etc.)
    6. Set user_approved=True when calling this tool

    DO NOT call this tool in the same response where you generate the commit message.
    The user MUST see the message and approve it first.

    Args:
        message: User-approved commit message (should follow 50/72 rule)
        user_approved: REQUIRED - Must be True. Confirms user has seen and approved the commit message.
        repo_path: Path to git repository (optional, defaults to Claude's working directory)

    Returns:
        Success message with commit hash or error
    """
    # Safety check
    if not user_approved:
        return "Error: user_approved must be True. Show the commit message to the user and get their approval first."
    try:
        # Get working directory from MCP roots if repo_path not provided
        if repo_path is None:
            context = mcp.get_context()
            roots_result = await context.session.list_roots()
            if roots_result.roots:
                repo_path = roots_result.roots[0].uri.path
            else:
                return "Error: No repository path provided and no roots available"

        result = git_operations.execute_commit(repo_path, message)
        return result
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def get_pr_context(
    base_branch: str,
    head_branch: Optional[str] = None,
    cursor: Optional[str] = None,
    max_diff_tokens: int = 12000,
    repo_path: Optional[str] = None
) -> str:
    """Get diff and commits between branches for PR description.

    IMPORTANT: After calling this tool, you should:
    1. Check if .devnarrate/pr-templates/ directory exists (use ls or Bash)
    2. If templates exist, list them and ask user which template to use
    3. Read the chosen template file (use Read tool)
    4. If no templates exist, use git_operations.DEFAULT_PR_TEMPLATE
    5. Analyze the diff and commits to fill the template

    Args:
        base_branch: Base branch to compare against (e.g., "main", "dev")
        head_branch: Head branch (defaults to current branch)
        cursor: Pagination cursor for large diffs (optional, returned as next_cursor)
        max_diff_tokens: Maximum tokens per diff chunk (default: 12000, leaves room for commits/files in 25k limit)
        repo_path: Path to git repository (optional, defaults to Claude's working directory)

    Returns:
        JSON string with commits, files, diff chunk, and pagination info
    """
    try:
        # Get working directory from MCP roots if repo_path not provided
        if repo_path is None:
            context = mcp.get_context()
            roots_result = await context.session.list_roots()
            if roots_result.roots:
                repo_path = roots_result.roots[0].uri.path
            else:
                return json.dumps({'error': 'No repository path provided and no roots available'})

        # Get current branch if head not specified
        if head_branch is None:
            head_branch = git_operations.get_current_branch(repo_path)

        # Get commits between branches
        commits = git_operations.get_branch_commits(repo_path, base_branch, head_branch)

        # Get file stats
        stats = git_operations.get_branch_file_stats(repo_path, base_branch, head_branch)

        # Get diff between branches
        diff_output = git_operations.get_branch_diff(repo_path, base_branch, head_branch)

        # Paginate diff by token count
        paginated = git_operations.paginate_diff(diff_output, cursor, max_diff_tokens)

        # Detect platform
        platform = git_operations.detect_git_platform(repo_path)

        result = {
            'repository': repo_path,
            'base_branch': base_branch,
            'head_branch': head_branch,
            'platform': platform,
            'commits': commits,
            'commit_count': len(commits),
            'files': stats['files'],
            'diff': paginated['diff_chunk'],
            'next_cursor': paginated['next_cursor'],
            'pagination_info': paginated['chunk_info'],
            'template_instructions': {
                'templates_directory': '.devnarrate/pr-templates/',
                'default_template_available': True,
                'steps': [
                    '1. Check if .devnarrate/pr-templates/ exists',
                    '2. If yes, list templates and ask user which to use',
                    '3. Read chosen template or use DEFAULT_PR_TEMPLATE',
                    '4. Fill template with analysis of commits and diff'
                ]
            }
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({'error': str(e)})


@mcp.tool()
async def create_pr(
    title: str,
    body: str,
    base_branch: str,
    user_approved: bool,
    head_branch: Optional[str] = None,
    draft: bool = False,
    repo_path: Optional[str] = None
) -> str:
    """Create a pull request on the detected platform (GitHub/GitLab).

    CRITICAL WORKFLOW - YOU MUST FOLLOW THESE STEPS IN ORDER:
    1. Call get_pr_context to analyze the changes
    2. Generate PR title and description based on the diff
    3. SHOW the generated PR title and body to the user in your response
    4. ASK the user: "Should I create this PR?" and WAIT for their response
    5. ONLY call this tool AFTER the user explicitly approves (says "yes", "proceed", "create it", etc.)
    6. Set user_approved=True when calling this tool

    DO NOT call this tool in the same response where you generate the PR description.
    The user MUST see the content and approve it first.

    Args:
        title: PR title (keep it concise, ~50 chars)
        body: PR description (formatted markdown)
        base_branch: Base branch (e.g., "main", "dev")
        user_approved: REQUIRED - Must be True. Confirms user has seen and approved the PR content.
        head_branch: Head branch (defaults to current branch)
        draft: Create as draft PR (default: False)
        repo_path: Path to git repository (optional, defaults to Claude's working directory)

    Returns:
        Success message with PR URL or error message
    """
    # Safety check
    if not user_approved:
        return "Error: user_approved must be True. Show the PR description to the user and get their approval first."
    try:
        # Get working directory from MCP roots if repo_path not provided
        if repo_path is None:
            context = mcp.get_context()
            roots_result = await context.session.list_roots()
            if roots_result.roots:
                repo_path = roots_result.roots[0].uri.path
            else:
                return "Error: No repository path provided and no roots available"

        result = git_operations.execute_pr_creation(
            repo_path=repo_path,
            title=title,
            body=body,
            base_branch=base_branch,
            head_branch=head_branch,
            draft=draft
        )
        return result

    except subprocess.CalledProcessError as e:
        return f"Error creating PR: {e.stderr if e.stderr else str(e)}\n\nMake sure the platform CLI is installed and configured (gh for GitHub, glab for GitLab)"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def review_changes(
    goal: str,
    scope: str = "working",
    repo_path: Optional[str] = None
) -> str:
    """Review code changes before staging/committing to understand what was done and why.

    WHEN TO CALL: After you (the AI assistant) have made code changes on behalf
    of the user and BEFORE staging or committing. This lets the user understand
    what you did at a conceptual level rather than reading raw diffs.

    REQUIRED: Before calling this tool, summarize what the user asked you to do.
    Pass this as the 'goal' parameter. Be specific — "add JWT authentication
    middleware" is better than "make changes".

    HOW TO PRESENT THE RESPONSE — follow this layered approach:

    1. NARRATIVE SUMMARY (always show first):
       Start with a plain-language summary of what changed.
       Example: "I made 5 changes across 3 files to add JWT authentication."
       Include the key stats: files added/modified/deleted, lines changed.

    2. GOAL ALIGNMENT (group changes by purpose):
       Look at each changed file and classify it into one of three tiers:
       - KNOWN: Changes that directly relate to the 'goal' you passed.
         You know these because you made them for the stated purpose.
       - INFERRED: Changes whose context_clues (comments, docstrings) suggest
         a clear purpose different from the stated goal. These may be from
         a different AI agent session. Describe the inferred purpose.
       - UNKNOWN: Changes with no clear connection to any goal AND no useful
         context clues. Flag these — the user should review them.

    3. PER-FILE BREAKDOWN:
       For each goal group, list the files with a short description of what
       changed. Read the diff to explain HOW the goal was achieved:
       - What functions/classes were added or modified?
       - What's the approach? (e.g., "Added middleware pattern using decorators")
       - Any notable implementation choices?

    4. ATTENTION GUIDE:
       Tell the user what needs their eyes vs what's routine:
       - NEW FILES: "I created auth/middleware.py — worth a quick review"
       - MODIFIED FILES: "Added 3 lines to config.py — routine import addition"
       - UNKNOWN CHANGES: "utils.py was modified but doesn't match the goal — please check"
       - LARGE CHANGES: Any file with 50+ lines added deserves a mention

    5. DETAIL ON DEMAND:
       End with: "Want me to walk through any specific file in detail?"

    IMPORTANT: You have the full diff in the response — READ IT to understand
    the actual code in any programming language. The context_clues are supplementary
    hints (comments/docstrings) to help you classify changes from other sessions
    that you didn't make yourself.

    Args:
        goal: What the user asked the AI to do. Summarize from your conversation.
              Be specific — this is used to classify changes into goal groups.
        scope: What to analyze:
               - "working" (default): All unstaged working tree changes (git diff)
                 plus untracked files. Use this before staging.
               - "staged": Only staged changes (git diff --staged). Use this
                 if the user has already staged specific files.
        repo_path: Path to git repository (optional, defaults to MCP roots).

    Returns:
        JSON string with:
        - goal: The stated goal (pass-through for your reference)
        - summary: File and line count statistics
        - changes: Per-file stats (path, status, lines_added, lines_removed)
        - context_clues: Comments and docstrings from added lines (per file)
        - diff: Raw diff text for you to read and understand the code
        - untracked_files: List of new files not yet tracked by git (working scope only)
        - pagination_info: Token counts and chunk info for the diff
    """
    try:
        # Get working directory from MCP roots if repo_path not provided
        if repo_path is None:
            context = mcp.get_context()
            roots_result = await context.session.list_roots()
            if roots_result.roots:
                repo_path = roots_result.roots[0].uri.path
            else:
                return json.dumps({'error': 'No repository path provided and no roots available'})

        # Get diff based on scope
        if scope == "staged":
            diff_output = git_operations.get_diff(repo_path)
            stats = git_operations.get_file_stats(repo_path)
            untracked = []
        else:
            diff_output = git_operations.get_working_diff(repo_path)
            stats = git_operations.get_working_file_stats(repo_path)
            untracked = git_operations.get_untracked_files(repo_path)

        has_changes = bool(diff_output.strip()) or bool(untracked)

        if not has_changes:
            return json.dumps({
                'goal': goal,
                'has_changes': False,
                'message': 'No changes found in the working tree.' if scope == 'working'
                           else 'No staged changes found.',
            }, indent=2)

        # Analyze the diff for structured metadata
        analysis = change_analyzer.analyze_changes(diff_output, stats.get('files', []))

        # Paginate the diff to stay under token limits
        paginated = git_operations.paginate_diff(diff_output, None)

        result = {
            'goal': goal,
            'has_changes': True,
            'summary': analysis['summary'],
            'changes': analysis['changes'],
            'context_clues': analysis['context_clues'],
            'diff': paginated['diff_chunk'],
            'next_cursor': paginated['next_cursor'],
            'pagination_info': paginated['chunk_info'],
        }

        if untracked:
            result['untracked_files'] = untracked

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({'error': str(e)})


if __name__ == "__main__":
    mcp.run()
