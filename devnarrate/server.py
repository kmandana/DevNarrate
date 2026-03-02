#!/usr/bin/env python3
"""
DevNarrate MCP Server

An MCP server that helps developers with:
- Writing commit messages
- Splitting staged changes into logical commits
- Generating PR descriptions
- Posting CI/CD results to Slack
- Sharing development updates to Slack
"""

import json
import subprocess
from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import change_analyzer
from . import config as config_module
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
        repo_path: Path to git repository (optional, defaults to the AI assistant's working directory)

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

        # Load project config
        cfg = config_module.load_config(repo_path)
        commit_cfg = cfg["commit"]
        secrets_cfg = cfg["secrets"]

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
        if has_changes and cursor is None and secrets_cfg.get("enabled", True):
            secret_scan = secret_scanner.scan_diff(
                diff_output,
                max_findings=secrets_cfg.get("max_findings"),
                custom_patterns=secrets_cfg.get("custom_patterns"),
            )
        else:
            reason = 'No changes to scan.'
            if has_changes and cursor is not None:
                reason = 'Secret scan performed on first page only.'
            elif has_changes and not secrets_cfg.get("enabled", True):
                reason = 'Secret scanning disabled in .devnarrate/config.toml.'
            secret_scan = {
                'status': 'clean',
                'findings': [],
                'total_findings': 0,
                'message': reason,
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
                'subject_line': f'Max {commit_cfg["max_subject_length"]} characters',
                'body_line_length': f'Max {commit_cfg["max_body_line_length"]} characters per line',
                'format': 'type(scope): description\\n\\nBody paragraphs...\\n\\nFooter',
                'types': commit_cfg["types"],
                'require_scope': commit_cfg.get("require_scope", False),
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
        repo_path: Path to git repository (optional, defaults to the AI assistant's working directory)

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
        repo_path: Path to git repository (optional, defaults to the AI assistant's working directory)

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

        # Load project config
        cfg = config_module.load_config(repo_path)
        pr_cfg = cfg["pr"]

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

        # Build template instructions with config-aware defaults
        template_instructions = {
            'templates_directory': '.devnarrate/pr-templates/',
            'default_template_available': True,
            'steps': [
                '1. Check if .devnarrate/pr-templates/ exists',
                '2. If yes, list templates and ask user which to use',
                '3. Read chosen template or use DEFAULT_PR_TEMPLATE',
                '4. Fill template with analysis of commits and diff'
            ],
        }
        if pr_cfg.get("template"):
            template_instructions['preferred_template'] = pr_cfg["template"]

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
            'template_instructions': template_instructions,
            'draft_by_default': pr_cfg.get("draft_by_default", False),
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
        repo_path: Path to git repository (optional, defaults to the AI assistant's working directory)

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

        # Load project config
        cfg = config_module.load_config(repo_path)
        review_cfg = cfg["review"]

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
            'large_change_threshold': review_cfg.get("large_change_threshold", 50),
        }

        if untracked:
            result['untracked_files'] = untracked

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({'error': str(e)})


@mcp.tool()
async def get_split_context(
    cursor: Optional[str] = None,
    max_diff_tokens: int = 20000,
    repo_path: Optional[str] = None
) -> str:
    """REQUIRED FIRST STEP: Analyze staged changes at per-file granularity for splitting into logical commits.

    WHEN TO CALL: When the user has staged many changes and wants to split them
    into multiple smaller, logical commits instead of one big commit.

    This tool returns per-file diffs so you can suggest groupings. Each file's
    diff is separate, making it easy to see what belongs together.

    IMPORTANT: This tool ONLY works with STAGED changes. The user must stage
    their changes first (git add).

    CRITICAL: If there are fewer than 2 staged files, splitting is not useful.
    Tell the user: "Only N file(s) staged — nothing to split. Use get_commit_context
    for a single commit instead."

    HOW TO PRESENT THE RESPONSE — follow these steps:

    1. REVIEW the per-file diffs to understand what each file does.

    2. SUGGEST GROUPS: Organize files into logical commit groups based on:
       - Related functionality (e.g., feature code + its tests)
       - Type of change (e.g., refactoring vs new feature vs docs)
       - Directory structure (e.g., frontend vs backend)
       - Dependencies (files that must be committed together to avoid breakage)
       Present each group with:
       - A suggested conventional commit message
       - The list of files in the group
       - A brief rationale for the grouping

    3. ASK FOR APPROVAL: Show the split plan and ask:
       "Should I commit these N groups in this order? You can adjust the
       grouping or messages before I proceed."

    4. EXECUTE: After approval, call execute_split_commit for each group
       in order. Wait for each to succeed before proceeding to the next.

    Args:
        cursor: Pagination cursor for large diffs (optional)
        max_diff_tokens: Maximum tokens per response (default: 20000)
        repo_path: Path to git repository (optional, defaults to MCP roots)

    Returns:
        JSON string with:
        - has_changes: boolean
        - file_count: number of staged files
        - files: list of per-file diffs with path, status, lines_added, lines_removed, diff
        - secret_scan: results of secret detection on the full staged diff
        - commit_format_guide: formatting rules for commit messages
    """
    try:
        if repo_path is None:
            context = mcp.get_context()
            roots_result = await context.session.list_roots()
            if roots_result.roots:
                repo_path = roots_result.roots[0].uri.path
            else:
                return json.dumps({'error': 'No repository path provided and no roots available'})

        cfg = config_module.load_config(repo_path)
        commit_cfg = cfg["commit"]
        secrets_cfg = cfg["secrets"]

        # Get per-file diffs for all staged files
        per_file = git_operations.get_per_file_diffs(repo_path)

        has_changes = len(per_file) > 0

        # Scan the full staged diff for secrets (only on first page)
        if has_changes and cursor is None and secrets_cfg.get("enabled", True):
            full_diff = git_operations.get_diff(repo_path)
            secret_scan = secret_scanner.scan_diff(
                full_diff,
                max_findings=secrets_cfg.get("max_findings"),
                custom_patterns=secrets_cfg.get("custom_patterns"),
            )
        else:
            reason = 'No changes to scan.'
            if has_changes and cursor is not None:
                reason = 'Secret scan performed on first page only.'
            elif has_changes and not secrets_cfg.get("enabled", True):
                reason = 'Secret scanning disabled in .devnarrate/config.toml.'
            secret_scan = {
                'status': 'clean',
                'findings': [],
                'total_findings': 0,
                'message': reason,
            }

        # Paginate per-file diffs: concatenate all file diffs and paginate
        # But also provide structured per-file metadata
        all_diffs = '\n'.join(f['diff'] for f in per_file if f['diff'])
        paginated = git_operations.paginate_diff(all_diffs, cursor, max_diff_tokens)

        # Build file metadata (without the full diff text to save tokens)
        file_metadata = []
        for f in per_file:
            file_metadata.append({
                'path': f['path'],
                'status': f['status'],
                'lines_added': f['lines_added'],
                'lines_removed': f['lines_removed'],
            })

        result = {
            'repository': repo_path,
            'has_changes': has_changes,
            'file_count': len(per_file),
            'files': file_metadata,
            'secret_scan': secret_scan,
            'diff': paginated['diff_chunk'],
            'next_cursor': paginated['next_cursor'],
            'pagination_info': paginated['chunk_info'],
            'commit_format_guide': {
                'subject_line': f'Max {commit_cfg["max_subject_length"]} characters',
                'body_line_length': f'Max {commit_cfg["max_body_line_length"]} characters per line',
                'format': 'type(scope): description\\n\\nBody paragraphs...\\n\\nFooter',
                'types': commit_cfg["types"],
                'require_scope': commit_cfg.get("require_scope", False),
                'important': 'DO NOT include AI signatures, attribution, or "Generated with" footers in the commit message'
            },
            'split_instructions': {
                'workflow': [
                    '1. Review per-file diffs to understand each change',
                    '2. Group files by logical purpose (feature, fix, docs, etc.)',
                    '3. Present the split plan with commit messages to the user',
                    '4. After approval, call execute_split_commit for each group in order',
                ],
                'grouping_hints': [
                    'Keep related code and its tests together',
                    'Separate refactoring from feature changes',
                    'Documentation changes can be their own commit',
                    'Config/dependency changes can be their own commit',
                    'Files that must work together should be in the same commit',
                ],
            },
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({'error': str(e)})


@mcp.tool()
async def execute_split_commit(
    files: list[str],
    message: str,
    user_approved: bool,
    repo_path: Optional[str] = None
) -> str:
    """Execute one commit in a split-commit workflow, committing only the specified files.

    CRITICAL WORKFLOW — YOU MUST FOLLOW THESE STEPS:
    1. Call get_split_context first to analyze all staged changes
    2. Present the full split plan (all groups with messages) to the user
    3. Get user approval for the ENTIRE plan before executing ANY commits
    4. Call this tool once per group, IN ORDER, with user_approved=True
    5. Wait for each call to succeed before proceeding to the next group

    This tool:
    - Unstages ALL currently staged files
    - Stages ONLY the files listed in the 'files' parameter
    - Commits with the given message
    - After the commit, the remaining files are left unstaged

    NOTE: This operates at file granularity. If you need hunk-level splitting
    (different parts of the same file in different commits), the user should
    use interactive staging (git add -p) manually.

    Args:
        files: List of file paths to include in this commit
        message: Commit message (should follow conventional commit format)
        user_approved: REQUIRED — Must be True. Confirms user approved the split plan.
        repo_path: Path to git repository (optional, defaults to MCP roots)

    Returns:
        JSON string with:
        - success: boolean
        - commit_hash: short hash of the new commit
        - committed_files: list of files included
        - remaining_staged: number of files still staged (0 after split commit)
        - message: status message
    """
    if not user_approved:
        return json.dumps({
            'success': False,
            'error': 'user_approved must be True. Show the split plan to the user and get their approval first.',
        })

    if not files:
        return json.dumps({
            'success': False,
            'error': 'files list must not be empty. Specify which files to include in this commit.',
        })

    try:
        if repo_path is None:
            context = mcp.get_context()
            roots_result = await context.session.list_roots()
            if roots_result.roots:
                repo_path = roots_result.roots[0].uri.path
            else:
                return json.dumps({'error': 'No repository path provided and no roots available'})

        # Get current staged files to know what to restore after
        current_staged = git_operations.get_file_stats(repo_path)
        staged_paths = [f['path'] for f in current_staged['files']]

        # Validate that requested files are actually staged
        missing = [f for f in files if f not in staged_paths]
        if missing:
            return json.dumps({
                'success': False,
                'error': f'These files are not staged: {missing}. Stage them first or check the file paths.',
            })

        # Files to unstage = all staged files NOT in this commit
        files_to_unstage = [f for f in staged_paths if f not in files]

        # Unstage everything except our target files
        if files_to_unstage:
            git_operations.unstage_files(repo_path, files_to_unstage)

        # Commit the remaining staged files (our target files)
        try:
            commit_result = git_operations.execute_commit(repo_path, message)
        except Exception as commit_err:
            # Re-stage the files we unstaged to restore original state
            if files_to_unstage:
                git_operations.stage_files(repo_path, files_to_unstage)
            return json.dumps({
                'success': False,
                'error': f'Commit failed: {commit_err}. Original staging restored.',
            })

        # Extract commit hash from result
        commit_hash = commit_result.split()[3] if 'Successfully' in commit_result else 'unknown'

        return json.dumps({
            'success': True,
            'commit_hash': commit_hash,
            'committed_files': files,
            'remaining_unstaged': len(files_to_unstage),
            'message': commit_result,
        }, indent=2)

    except Exception as e:
        return json.dumps({'success': False, 'error': str(e)})


if __name__ == "__main__":
    mcp.run()
