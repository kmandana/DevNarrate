"""Git operations for DevNarrate."""

import subprocess
from typing import Optional

import tiktoken

# MCP response token limit is 25,000 - we'll use 20,000 to be safe
MAX_RESPONSE_TOKENS = 20000


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken (cl100k_base encoding).

    Args:
        text: Text to count tokens for

    Returns:
        Number of tokens
    """
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        # Fallback to rough estimate: ~4 chars per token
        return len(text) // 4


def get_diff(repo_path: str, staged_only: bool = True) -> str:
    """Get git diff output.

    Args:
        repo_path: Path to the git repository
        staged_only: If True, only get staged changes (--staged), else all changes (HEAD)

    Returns:
        Raw git diff output

    Raises:
        subprocess.CalledProcessError: If git command fails
    """
    if staged_only:
        cmd = ['git', 'diff', '--staged']
    else:
        cmd = ['git', 'diff', 'HEAD']

    result = subprocess.run(
        cmd,
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout


def get_file_stats(repo_path: str, staged_only: bool = True) -> dict:
    """Get statistics about changed files.

    Args:
        repo_path: Path to the git repository
        staged_only: If True, only get staged changes

    Returns:
        Dict with file changes
    """
    # Get list of changed files with status
    status_cmd = ['git', 'status', '--porcelain']

    status_result = subprocess.run(
        status_cmd,
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True
    )

    # Parse file status
    # Format: XY filepath (X=staged, Y=unstaged, space=no change)
    files = []
    for line in status_result.stdout.strip().split('\n'):
        if not line:
            continue

        staged_status = line[0]
        unstaged_status = line[1]
        filepath = line[3:]

        # If staged_only, skip untracked files and files with no staged changes
        if staged_only and staged_status in (' ', '?'):
            continue

        # Use staged status if staged_only, otherwise prioritize staged over unstaged
        status_char = staged_status if staged_only else (staged_status if staged_status != ' ' else unstaged_status)

        file_status = 'modified'
        if status_char == 'A':
            file_status = 'added'
        elif status_char == 'D':
            file_status = 'deleted'
        elif status_char == 'M':
            file_status = 'modified'
        elif status_char == 'R':
            file_status = 'renamed'
        elif status_char == '?':
            file_status = 'untracked'

        files.append({
            'path': filepath,
            'status': file_status
        })

    return {'files': files}


def paginate_diff(diff_text: str, cursor: Optional[str], max_tokens: int = MAX_RESPONSE_TOKENS) -> dict:
    """Paginate diff output by token count (MCP limit: 25k tokens).

    This ensures responses stay under the MCP token limit while preserving
    line boundaries for readability. Reusable for PR diffs as well.

    Args:
        diff_text: Full diff text
        cursor: Current cursor position (line number as string)
        max_tokens: Maximum tokens per chunk (default: 20,000 to stay under 25k limit)

    Returns:
        Dict with diff chunk, token counts, and nextCursor
    """
    if not diff_text:
        return {
            'diff_chunk': '',
            'next_cursor': None,
            'chunk_info': {
                'start_line': 0,
                'end_line': 0,
                'total_lines': 0,
                'chunk_tokens': 0,
                'total_tokens': 0
            }
        }

    lines = diff_text.split('\n')
    total_lines = len(lines)
    total_tokens = count_tokens(diff_text)

    # Parse cursor (line number) or start from 0
    start_line = 0
    if cursor:
        try:
            start_line = int(cursor)
        except ValueError:
            start_line = 0

    # Build chunk line by line, staying under token limit
    chunk_lines = []
    chunk_text = ""
    end_line = start_line

    for i in range(start_line, total_lines):
        line = lines[i]
        test_chunk = chunk_text + line + '\n'
        test_tokens = count_tokens(test_chunk)

        if test_tokens > max_tokens and chunk_lines:
            # Would exceed limit, stop here
            break

        chunk_lines.append(line)
        chunk_text = test_chunk
        end_line = i + 1

    # Determine next cursor
    next_cursor = None
    if end_line < total_lines:
        next_cursor = str(end_line)

    chunk_tokens = count_tokens(chunk_text)

    return {
        'diff_chunk': '\n'.join(chunk_lines),
        'next_cursor': next_cursor,
        'chunk_info': {
            'start_line': start_line,
            'end_line': end_line,
            'total_lines': total_lines,
            'chunk_tokens': chunk_tokens,
            'total_tokens': total_tokens,
            'chunk_percentage': round((chunk_tokens / total_tokens * 100) if total_tokens > 0 else 100, 1)
        }
    }


def execute_commit(repo_path: str, message: str) -> str:
    """Execute git commit with the given message.

    Args:
        repo_path: Path to the git repository
        message: Commit message

    Returns:
        Success message with commit hash

    Raises:
        subprocess.CalledProcessError: If git commit fails
    """
    # Execute commit
    result = subprocess.run(
        ['git', 'commit', '-m', message],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True
    )

    # Get the commit hash
    hash_result = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True
    )

    commit_hash = hash_result.stdout.strip()[:7]

    return f"Successfully committed as {commit_hash}\n{result.stdout}"
