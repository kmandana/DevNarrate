#!/usr/bin/env python3
"""
DevNarrate MCP Server

An MCP server that helps developers with:
- Writing commit messages
- Generating PR descriptions
- Posting CI/CD results to Slack
- Sharing development updates to Slack
"""

from mcp.server.fastmcp import FastMCP

# Create MCP server instance
mcp = FastMCP("devnarrate")


if __name__ == "__main__":
    mcp.run()
