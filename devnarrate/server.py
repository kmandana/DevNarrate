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
from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import git_operations

# Create MCP server instance
mcp = FastMCP("devnarrate")


@mcp.tool()
async def get_commit_context(
    include_unstaged: bool = False,
    cursor: Optional[str] = None,
    max_diff_tokens: int = 20000,
    repo_path: Optional[str] = None
) -> str:
    """REQUIRED FIRST STEP: Get git diff and file changes to analyze before writing a commit message.

    IMPORTANT: You MUST call this tool FIRST before generating any commit message.
    Never write a commit message without first seeing the actual git diff from this tool.

    Returns file changes and diff output with TOKEN-BASED pagination (MCP limit: 25k tokens).
    Large diffs are automatically paginated to stay under the token limit.

    After receiving the diff, analyze it and generate a commit message following:
    - 50/72 rule: 50 char subject line, 72 char body lines
    - Conventional commits format: type(scope): description
    - DO NOT include AI signatures, attribution, or "Generated with" footers

    Args:
        include_unstaged: Include unstaged changes (default: False, staged only)
        cursor: Pagination cursor for large diffs (optional, returned as next_cursor)
        max_diff_tokens: Maximum tokens per response (default: 20000, safe under 25k limit)
        repo_path: Path to git repository (optional, defaults to Claude's working directory)

    Returns:
        JSON string with files, stats, diff chunk, token counts, and pagination info
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

        staged_only = not include_unstaged

        # Get file stats
        stats = git_operations.get_file_stats(repo_path, staged_only=staged_only)

        # Get full diff
        diff_output = git_operations.get_diff(repo_path, staged_only=staged_only)

        # Paginate diff by token count
        paginated = git_operations.paginate_diff(diff_output, cursor, max_diff_tokens)

        result = {
            'repository': repo_path,
            'files': stats['files'],
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
async def commit_changes(message: str, repo_path: Optional[str] = None) -> str:
    """Execute git commit with a user-approved commit message.

    IMPORTANT: Only call this tool AFTER:
    1. You called get_commit_context to get the diff
    2. You generated a commit message based on the actual diff
    3. The user has explicitly approved the commit message

    Never call this tool without user approval of the commit message first.

    Args:
        message: User-approved commit message (should follow 50/72 rule)
        repo_path: Path to git repository (optional, defaults to Claude's working directory)

    Returns:
        Success message with commit hash or error
    """
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


if __name__ == "__main__":
    mcp.run()
