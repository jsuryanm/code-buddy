"""Calls tools either in-process or through the MCP server (spec 12.3)."""

from __future__ import annotations

import json
import logging
import sys
import warnings
from typing import Any, Protocol

from langchain_core._api import LangChainBetaWarning

from codebuddy.tools.functions import TOOLS

log = logging.getLogger("codebuddy.tools")


class ToolRunner(Protocol):
    async def call(self, name: str, **args: Any) -> dict: ...

    async def close(self) -> None: ...


class LocalToolRunner:
    async def call(self, name: str, **args: Any) -> dict:
        return await TOOLS[name](**args)

    async def close(self) -> None:
        return None


def _decode(result: Any) -> dict:
    """langchain.mcp tools return a list of text blocks holding a JSON string."""
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        result = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in result)
    return json.loads(result)


class MCPToolRunner:
    """Keeps one stdio MCP session open for the life of the app."""

    def __init__(self) -> None:
        self._cm: Any = None
        self._tools: dict[str, Any] = {}

    async def start(self) -> None:
        # langchain.mcp is beta and warns on import; the warning is expected here.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LangChainBetaWarning)
            from langchain.mcp import MCPAdapter

        adapter = MCPAdapter(
            {
                "mcpServers": {
                    "codebuddy": {
                        "command": sys.executable,
                        "args": ["-m", "codebuddy.mcp_server"],
                    }
                }
            }
        )
        # Holding the context open makes every tool call reuse one connection.
        await adapter.__aenter__()
        self._cm = adapter
        self._tools = {t.name: t for t in await adapter.list_tools()}

    async def call(self, name: str, **args: Any) -> dict:
        return _decode(await self._tools[name].ainvoke(args))

    async def close(self) -> None:
        if self._cm is not None:
            await self._cm.__aexit__(None, None, None)
            self._cm = None


async def start_tool_runner(use_mcp: bool) -> ToolRunner:
    """MCP when enabled and it starts; otherwise in-process, with a warning."""
    if use_mcp:
        runner = MCPToolRunner()
        try:
            await runner.start()
            return runner
        except Exception:
            log.warning("MCP server failed to start; calling tools in-process", exc_info=True)
    return LocalToolRunner()
