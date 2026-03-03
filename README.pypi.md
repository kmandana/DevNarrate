# DevNarrate
[![GitHub Repo](https://img.shields.io/badge/GitHub-kmandana%2FDevNarrate-24292F?logo=github)](https://github.com/kmandana/DevNarrate)
[![Release](https://img.shields.io/github/v/release/kmandana/DevNarrate?label=Release)](https://github.com/kmandana/DevNarrate/releases)

MCP server for developer workflow automation — smart commits, secret scanning, PR descriptions, and more.

## Features

- **Change Review** — understand AI-generated code changes before committing with narrative summaries, goal alignment, and attention guides
- **Smart Commit Messages** with user approval
- **Secret Scanning** — detect API keys, tokens, passwords, and private keys before they reach your repo (25+ detectors via [detect-secrets](https://github.com/Yelp/detect-secrets))
- **PR Descriptions** driven by customizable templates
- **GitHub & GitLab** support for PR flows
- **Token-aware diff handling** with automatic pagination
- **Split Commits** — automatically suggests breaking large staged changes into focused, logical commits
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

Then ask your AI assistant:

```
Generate a commit message for my changes
```

DevNarrate summarizes the diff, proposes a conventional commit, and waits for approval before committing.

### Change Review

After an AI assistant makes changes, ask it to review them before committing. DevNarrate presents a layered summary: narrative overview, goal grouping (known, inferred, unrecognized), and an attention guide highlighting what needs human review.

### Secret Scanning

Secret scanning runs automatically when you ask for a commit message. DevNarrate scans staged diffs for API keys, tokens, passwords, and private keys. If secrets are found, you're warned before committing. Suppress false positives with an inline `# pragma: allowlist secret` comment.

### Split Commits

When you stage changes touching many files (4+ by default), DevNarrate suggests splitting them into focused commits grouped by logical concern. You approve each group before it's committed. Adjust the threshold via `split_threshold` in `.devnarrate/config.toml` (set to 0 to disable).

### PR Descriptions

1. Ask your AI assistant: "Create a PR to main from my current branch"
2. Choose a template if you have custom ones in `.devnarrate/pr-templates/`
3. Review the generated PR description and approve to let DevNarrate call `gh` or `glab`

### Configuration

DevNarrate ships a fully commented [`.devnarrate/config.toml`](https://github.com/kmandana/DevNarrate/blob/main/.devnarrate/config.toml) with all available settings and their defaults. Copy it into your repo and edit the values you care about — every option is documented inline.

### Platform Requirements

- **Commits:** only needs git
- **GitHub PRs:** install [gh](https://cli.github.com/) and run `gh auth login`
- **GitLab PRs:** install [glab](https://gitlab.com/gitlab-org/cli) and run `glab auth login`

## Links

- Source: https://github.com/krishnamandanapu/DevNarrate
- Issues: https://github.com/krishnamandanapu/DevNarrate/issues

