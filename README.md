# DevNarrate
The AI that narrates your code changes, from commits to deployments.

## Setup with Claude Code

1. Install dependencies:
```bash
uv sync
```

2. Add MCP server:
```bash
claude mcp add DevNarrate -- uv --directory /path/to/DevNarrate run python -m devnarrate.server
```

3. Verify:
```bash
claude mcp list
```

## Usage

Ask Claude: "Generate a commit message for my staged changes"
