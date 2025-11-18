# DevNarrate
[![PyPI](https://img.shields.io/pypi/v/devnarrate?label=PyPI&color=3775A9)](https://pypi.org/project/devnarrate/)
[![Package Status](https://img.shields.io/pypi/status/devnarrate)](https://pypi.org/project/devnarrate/)

MCP server that narrates your code changes, from commits to deployments.

## Features

- **Smart Commit Messages**: Generate conventional commit messages from staged changes with full user control
- **PR Descriptions**: Create detailed pull request descriptions with customizable templates
- **Multi-Platform**: Supports GitHub and GitLab
- **Token-Aware**: Handles large diffs with automatic pagination
- **Template System**: Use custom PR templates or built-in defaults
- **Safety First**: Only works with staged changes to prevent accidental commits

## Installation (Source / Development)

### 1. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Clone and set up

```bash
git clone https://github.com/krishnamandanapu/DevNarrate.git
cd DevNarrate
uv sync
```

### 3. Register the MCP server

The server must be launched with the Python interpreter from your uv-managed virtual environment (typically `/path/to/DevNarrate/.venv/bin/python` on macOS/Linux or `.venv\\Scripts\\python.exe` on Windows).

```bash
# capture the interpreter path once
VENV_PY=$(pwd)/.venv/bin/python

# Claude Code (global scope)
claude mcp add --scope user DevNarrate -- "$VENV_PY" -m devnarrate.server

# Claude Code (project scope)
claude mcp add DevNarrate -- "$VENV_PY" -m devnarrate.server
```

Cursor (`~/.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "DevNarrate": {
      "command": "/path/to/DevNarrate/.venv/bin/python",
      "args": ["-m", "devnarrate.server"]
    }
  }
}
```

For pip-based installation steps, head to https://pypi.org/project/devnarrate/.

## Usage

### Commit Messages

DevNarrate only works with **staged changes** to keep you in control.

```bash
git add <file1> <file2>
# or stage everything tracked:
git add -u
```

Then ask Claude:

```
Generate a commit message for my changes
```

Claude inspects the staged diff, proposes a conventional commit message, and asks for approval before running `git commit`.

### PR Descriptions

1. Ask Claude: "Create a PR to main from my current branch"
2. Claude analyzes the diff and offers template options (custom templates live in `.devnarrate/pr-templates/`)
3. Review the generated description and approve to let Claude create the PR via `gh` or `glab`

### PR Templates (Optional)

```bash
mkdir -p .devnarrate/pr-templates
```

Example (`.devnarrate/pr-templates/feature.md`):

```markdown
## Summary
[What does this PR do?]

## Changes
-
-

## Testing
[How to test]

## Related Issues
[Links]
```

If no template is found, DevNarrate falls back to its default format.

### Platform Support

- **Commits:** Works anywhere git runs
- **PRs:** Requires platform CLIs
  - GitHub: Install [gh](https://cli.github.com/) and run `gh auth login`
  - GitLab: Install [glab](https://gitlab.com/gitlab-org/cli) and run `glab auth login`

## Development

- Format/lint through uv-managed tooling
- Build artifacts with `uv run pyproject-build`
- Use `bump-my-version` (see `RELEASING.md`) for tagged releases

## License

MIT

