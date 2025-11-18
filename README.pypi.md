# DevNarrate
[![GitHub Repo](https://img.shields.io/badge/GitHub-kmandana%2FDevNarrate-24292F?logo=github)](https://github.com/kmandana/DevNarrate)
[![Release](https://img.shields.io/github/v/release/kmandana/DevNarrate?label=Release)](https://github.com/kmandana/DevNarrate/releases)

MCP server that narrates your code changes, from commits to deployments.

## Features

- **Smart Commit Messages** with user approval
- **PR Descriptions** driven by customizable templates
- **GitHub & GitLab** support for PR flows
- **Token-aware diff handling** with automatic pagination
- **Safety-first workflow** by requiring staged changes

## Installation (PyPI)

```bash
pip install devnarrate

# Install pre-release builds
pip install --pre devnarrate
```

### Register the MCP server

Use the Python interpreter from the environment where you ran `pip install` (e.g. `/path/to/venv/bin/python`). Capture it once and reuse:

```bash
PYTHON_BIN=$(python -c 'import sys; print(sys.executable)')

# Claude Code (global scope)
claude mcp add --scope user DevNarrate -- "$PYTHON_BIN" -m devnarrate.server

# Claude Code (project scope)
claude mcp add DevNarrate -- "$PYTHON_BIN" -m devnarrate.server
```

- Cursor (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "DevNarrate": {
      "command": "/path/to/venv/bin/python",
      "args": ["-m", "devnarrate.server"]
    }
  }
}
```

Restart Cursor after editing the config.

## Usage

### Commit Messages

DevNarrate works entirely off **staged changes**:

```bash
git add <file1> <file2>
# stage everything tracked:
git add -u
```

Then ask Claude (or Cursor):

```
Generate a commit message for my changes
```

DevNarrate summarizes the diff, proposes a conventional commit, and waits for approval before committing.

### PR Descriptions

1. Ask Claude: "Create a PR to main from my current branch"
2. Choose a template if you have custom ones in `.devnarrate/pr-templates/`
3. Review the generated PR description and approve to let DevNarrate call `gh` or `glab`

Example template (`.devnarrate/pr-templates/feature.md`):

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

If no custom template exists, DevNarrate uses a sensible default.

### Platform Requirements

- **Commits:** only needs git
- **GitHub PRs:** install [gh](https://cli.github.com/) and run `gh auth login`
- **GitLab PRs:** install [glab](https://gitlab.com/gitlab-org/cli) and run `glab auth login`

## Links

- Source: https://github.com/krishnamandanapu/DevNarrate
- Issues: https://github.com/krishnamandanapu/DevNarrate/issues

