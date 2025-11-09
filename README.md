# DevNarrate
MCP server that narrates your code changes, from commits to deployments.

## Features

- **Smart Commit Messages**: Generate conventional commit messages from staged changes with full user control
- **PR Descriptions**: Create detailed pull request descriptions with customizable templates
- **Multi-Platform**: Supports GitHub and GitLab
- **Token-Aware**: Handles large diffs with automatic pagination
- **Template System**: Use custom PR templates or built-in defaults
- **Safety First**: Only works with staged changes to prevent accidental commits

## Installation

### Option 1: Install from PyPI (Recommended)

1. **Install the package:**
```bash
pip install devnarrate

# Or for pre-release versions:
pip install --pre devnarrate
```

2. **Configure with Claude Code:**
```bash
# Add MCP server globally (available in all projects)
claude mcp add --scope user DevNarrate -- python -m devnarrate.server

# Or add for current project only
claude mcp add DevNarrate -- python -m devnarrate.server

# Verify it's connected
claude mcp list
```

3. **Configure with Cursor:**

Edit `~/.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "DevNarrate": {
      "command": "python",
      "args": ["-m", "devnarrate.server"]
    }
  }
}
```

Then restart Cursor.

### Option 2: Install from Source (Development)

1. **Prerequisites:** Install [uv](https://docs.astral.sh/uv/getting-started/installation/):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. **Clone and setup:**
```bash
git clone <>
cd DevNarrate
uv sync
```

3. **Configure with Claude Code:**
```bash
# Add MCP server globally (available in all projects)
claude mcp add --scope user DevNarrate -- uv --directory /path/to/DevNarrate run python -m devnarrate.server

# Or add for current project only
claude mcp add DevNarrate -- uv --directory /path/to/DevNarrate run python -m devnarrate.server
```

4. **Configure with Cursor:**
```json
{
  "mcpServers": {
    "DevNarrate": {
      "command": "uv",
      "args": ["--directory", "/path/to/DevNarrate", "run", "python", "-m", "devnarrate.server"]
    }
  }
}
```

## Usage

### Commit Messages

**Important:** DevNarrate only works with **staged changes** to ensure you have full control over what gets committed. This prevents accidental commits of unintended files.

1. First, stage the files you want to commit:
```bash
git add <file1> <file2>
# or for all tracked files with changes:
git add -u
```

2. Ask Claude to generate the commit message:
```
Ask Claude: "Generate a commit message for my changes"
```

3. Claude will analyze your staged changes, show you the proposed commit message, and ask for approval before committing.

If you haven't staged any changes, Claude will prompt you to stage them first.

### PR Descriptions

1. Ask Claude: "Create a PR to main from my current branch"
2. Claude will analyze the diff and ask which template to use (if you have custom templates)
3. Claude generates the PR description and shows it to you
4. Review and approve, then Claude creates the PR

### PR Templates (Optional)
Create custom templates in `.devnarrate/pr-templates/`:

```bash
mkdir -p .devnarrate/pr-templates
```

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

If no templates exist, a default template will be used.

## Platform Support

**Commits:** Works everywhere (uses git)

**PRs:** Requires platform CLI:
- GitHub: Install [gh](https://cli.github.com/) and run `gh auth login`
- GitLab: Install [glab](https://gitlab.com/gitlab-org/cli) and run `glab auth login`