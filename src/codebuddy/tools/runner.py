"""Calls tools either in-process or through the MCP server (spec 12.3)."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import warnings
from collections.abc import Awaitable
from typing import Any, Protocol

from langchain_core._api import LangChainBetaWarning
from loguru import logger

from codebuddy.tools.functions import TOOLS

log = logging.getLogger("codebuddy.tools")
LOG_ENV = "CODEBUDDY_LOG_"


class ToolRunner(Protocol):
    async def call(self, name: str, **args: Any) -> dict: ...

    async def close(self) -> None: ...


async def logged_call(via: str, name: str, call: Awaitable[dict]) -> dict:
    """Run a tool call and log its name, route and duration (never its arguments or result)."""
    started = time.perf_counter()
    ok = False
    try:
        result = await call
        ok = True
        return result
    finally:
        ms = (time.perf_counter() - started) * 1e3
        logger.info("tool {} via={} {:.1f} ms ok={}", name, via, ms, ok)


class LocalToolRunner:
    async def call(self, name: str, **args: Any) -> dict:
        return await logged_call("inprocess", name, TOOLS[name](**args))

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
                        # The child gets only a safe default environment; pass the log
                        # settings so its logs follow the API's (e.g. CODEBUDDY_LOG_TO_FILE).
                        "env": {k: v for k, v in os.environ.items() if k.startswith(LOG_ENV)},
                    }
                }
            }
        )
        # Holding the context open makes every tool call reuse one connection.
        await adapter.__aenter__()
        self._cm = adapter
        self._tools = {t.name: t for t in await adapter.list_tools()}

    async def call(self, name: str, **args: Any) -> dict:
        return _decode(await logged_call("mcp", name, self._tools[name].ainvoke(args)))

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
        except Exception as exc:
            log.warning(
                "MCP server failed to start (%s); calling tools in-process", type(exc).__name__
            )
    return LocalToolRunner()
