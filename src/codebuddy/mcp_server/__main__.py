from loguru import logger

from codebuddy.config import Settings
from codebuddy.mcp_server.server import main
from codebuddy.observability.logs import log_start, setup_logging

# stdout carries the MCP protocol: logs go to stderr and logs/ only.
log_start("mcp", "the codebuddy-tools MCP server", setup_logging(Settings(), app="mcp"))
try:
    main()
finally:
    logger.info("MCP server stopped")
    logger.complete()
