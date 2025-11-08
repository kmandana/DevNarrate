"""Git operations for DevNarrate."""

import subprocess
from typing import Optional

import tiktoken

# MCP response token limit is 25,000 - we'll use 20,000 to be safe
MAX_RESPONSE_TOKENS = 20000

# Default PR template
DEFAULT_PR_TEMPLATE = """## Summary
[Brief description of what this PR does and why]

## Changes
-
-

## Testing
[How to test these changes]

## Related Issues
[Links to related issues, if any]
"""


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


def get_diff(repo_path: str) -> str:
    """Get git diff output for staged changes only.

    Args:
        repo_path: Path to the git repository

    Returns:
        Raw git diff output for staged changes

    Raises:
        subprocess.CalledProcessError: If git command fails
    """
    result = subprocess.run(
        ['git', 'diff', '--staged'],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout


def get_file_stats(repo_path: str) -> dict:
    """Get statistics about staged files only.

    Args:
        repo_path: Path to the git repository

    Returns:
        Dict with staged file changes
    """
    # Get list of changed files with status
    status_result = subprocess.run(
        ['git', 'status', '--porcelain'],
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

        # First 2 chars are status codes (XY), rest is filepath
        staged_status = line[0]
        filepath = line[2:].strip()  # Skip status codes and strip whitespace

        # Skip files with no staged changes (untracked or not staged)
        if staged_status in (' ', '?'):
            continue

        file_status = 'modified'
        if staged_status == 'A':
            file_status = 'added'
        elif staged_status == 'D':
            file_status = 'deleted'
        elif staged_status == 'M':
            file_status = 'modified'
        elif staged_status == 'R':
            file_status = 'renamed'

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


def get_current_branch(repo_path: str) -> str:
    """Get the current git branch name.

    Args:
        repo_path: Path to the git repository

    Returns:
        Current branch name

    Raises:
        subprocess.CalledProcessError: If git command fails
    """
    result = subprocess.run(
        ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout.strip()


def get_branch_diff(repo_path: str, base_branch: str, head_branch: Optional[str] = None) -> str:
    """Get diff between two branches.

    Args:
        repo_path: Path to the git repository
        base_branch: Base branch (e.g., "main", "dev")
        head_branch: Head branch (defaults to current branch)

    Returns:
        Raw git diff output

    Raises:
        subprocess.CalledProcessError: If git command fails
    """
    if head_branch is None:
        head_branch = get_current_branch(repo_path)

    # Use three-dot diff to compare from common ancestor
    result = subprocess.run(
        ['git', 'diff', f'{base_branch}...{head_branch}'],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout


def get_branch_commits(repo_path: str, base_branch: str, head_branch: Optional[str] = None) -> list[dict]:
    """Get list of commits in head branch not in base branch.

    Args:
        repo_path: Path to the git repository
        base_branch: Base branch (e.g., "main", "dev")
        head_branch: Head branch (defaults to current branch)

    Returns:
        List of commit dicts with 'hash' and 'message'

    Raises:
        subprocess.CalledProcessError: If git command fails
    """
    if head_branch is None:
        head_branch = get_current_branch(repo_path)

    # Get commits in head but not in base
    result = subprocess.run(
        ['git', 'log', f'{base_branch}..{head_branch}', '--oneline'],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True
    )

    commits = []
    for line in result.stdout.strip().split('\n'):
        if line:
            parts = line.split(' ', 1)
            commits.append({
                'hash': parts[0],
                'message': parts[1] if len(parts) > 1 else ''
            })

    return commits


def get_branch_file_stats(repo_path: str, base_branch: str, head_branch: Optional[str] = None) -> dict:
    """Get file statistics for changes between branches.

    Args:
        repo_path: Path to the git repository
        base_branch: Base branch (e.g., "main", "dev")
        head_branch: Head branch (defaults to current branch)

    Returns:
        Dict with file changes

    Raises:
        subprocess.CalledProcessError: If git command fails
    """
    if head_branch is None:
        head_branch = get_current_branch(repo_path)

    # Get list of changed files with status
    result = subprocess.run(
        ['git', 'diff', '--name-status', f'{base_branch}...{head_branch}'],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True
    )

    files = []
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue

        parts = line.split('\t', 1)
        if len(parts) < 2:
            continue

        status_char = parts[0]
        filepath = parts[1]

        file_status = 'modified'
        if status_char == 'A':
            file_status = 'added'
        elif status_char == 'D':
            file_status = 'deleted'
        elif status_char == 'M':
            file_status = 'modified'
        elif status_char.startswith('R'):
            file_status = 'renamed'

        files.append({
            'path': filepath,
            'status': file_status
        })

    return {'files': files}


def detect_git_platform(repo_path: str) -> str:
    """Detect git platform from remote URL.

    Args:
        repo_path: Path to the git repository

    Returns:
        Platform name: 'github', 'gitlab', 'bitbucket', or 'unknown'

    Raises:
        subprocess.CalledProcessError: If git command fails
    """
    try:
        result = subprocess.run(
            ['git', 'remote', 'get-url', 'origin'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        remote_url = result.stdout.strip().lower()

        if 'github.com' in remote_url:
            return 'github'
        elif 'gitlab.com' in remote_url or 'gitlab' in remote_url:
            return 'gitlab'
        elif 'bitbucket.org' in remote_url:
            return 'bitbucket'
        else:
            return 'unknown'
    except subprocess.CalledProcessError:
        return 'unknown'


def execute_pr_creation(
    repo_path: str,
    title: str,
    body: str,
    base_branch: str,
    head_branch: Optional[str] = None,
    draft: bool = False
) -> str:
    """Create a pull request using platform CLI.

    Args:
        repo_path: Path to the git repository
        title: PR title
        body: PR description
        base_branch: Base branch (e.g., "main", "dev")
        head_branch: Head branch (defaults to current branch)
        draft: Create as draft PR

    Returns:
        Success message with PR URL

    Raises:
        subprocess.CalledProcessError: If command fails
        ValueError: If platform not supported or CLI not available
    """
    if head_branch is None:
        head_branch = get_current_branch(repo_path)

    platform = detect_git_platform(repo_path)

    if platform == 'github':
        # Use GitHub CLI
        cmd = ['gh', 'pr', 'create', '--base', base_branch, '--head', head_branch, '--title', title, '--body', body]
        if draft:
            cmd.append('--draft')

    elif platform == 'gitlab':
        # Use GitLab CLI
        cmd = ['glab', 'mr', 'create', '--target-branch', base_branch, '--source-branch', head_branch, '--title', title, '--description', body]
        if draft:
            cmd.append('--draft')

    else:
        raise ValueError(f"Platform '{platform}' not supported or CLI not configured. Supported: github (gh), gitlab (glab)")

    result = subprocess.run(
        cmd,
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True
    )

    return result.stdout
