"""MCP server exposing CodeBuddy's tools over stdio.

    uv run python -m codebuddy.mcp_server

Tools: analyze_python (read), suggest_cases (read), trace_python (execute, sandboxed).
The tutor asks the learner before it calls trace_python (see agent/nodes.py).
"""

from __future__ import annotations

import sys

from mcp.server.mcpserver import MCPServer

from codebuddy.tools import functions

mcp = MCPServer("codebuddy-tools")


@mcp.tool()
async def analyze_python(code: str) -> dict:
    """Find common beginner bug patterns in Python code. Static analysis only."""
    return await functions.analyze_python(code)


@mcp.tool()
async def suggest_cases(code: str) -> dict:
    """Suggest small concrete inputs to try by hand for each function in the code."""
    return await functions.suggest_cases(code)


@mcp.tool()
async def trace_python(code: str) -> dict:
    """Run beginner Python in a sandbox and return output, errors, and a variable trace."""
    return await functions.trace_python(code)


BANNER = (
    "codebuddy-tools MCP server on stdio. It waits for an MCP client; the API starts its own "
    "copy, so you do not need to run this. Ctrl+C to stop."
)


def main() -> None:
    if sys.stdin.isatty():
        print(BANNER, file=sys.stderr, flush=True)  # stdout carries the protocol
    mcp.run(transport="stdio")
