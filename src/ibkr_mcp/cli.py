"""
CLI entry point for IBKR MCP Server.
"""

import argparse
import asyncio
import sys
from typing import Optional

from loguru import logger

from .config import ServerConfig, IBKRConfig, MCPConfig
from .server import IBKRMCPServer


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    logger.remove()

    level = "DEBUG" if verbose else "INFO"
    format_str = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    logger.add(sys.stderr, format=format_str, level=level, colorize=True)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="IBKR MCP Server - Interactive Brokers integration for AI assistants",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ibkr-mcp                          # Start with default settings (stdio transport)
  ibkr-mcp --port 7496              # Connect to live trading
  ibkr-mcp --transport sse          # Use SSE transport
  ibkr-mcp --readonly               # Read-only mode (no trading)
  ibkr-mcp -v                       # Verbose logging

Environment Variables:
  IBKR_HOST          TWS/Gateway host (default: 127.0.0.1)
  IBKR_PORT          TWS/Gateway port (default: 7497)
  IBKR_CLIENT_ID     Client ID (default: 1)
  IBKR_READONLY      Read-only mode (default: false)
  MCP_TRANSPORT      Transport type: stdio, sse, streamable-http
        """,
    )

    # IBKR connection options
    ibkr_group = parser.add_argument_group("IBKR Connection")
    ibkr_group.add_argument(
        "--host",
        default="127.0.0.1",
        help="TWS/Gateway host (default: 127.0.0.1)",
    )
    ibkr_group.add_argument(
        "--port",
        type=int,
        default=7497,
        help="TWS/Gateway port (7497=paper, 7496=live)",
    )
    ibkr_group.add_argument(
        "--client-id",
        type=int,
        default=1,
        help="Client ID for IBKR connection",
    )
    ibkr_group.add_argument(
        "--readonly",
        action="store_true",
        help="Read-only mode (disable trading)",
    )
    ibkr_group.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Connection timeout in seconds",
    )

    # MCP server options
    mcp_group = parser.add_argument_group("MCP Server")
    mcp_group.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport type (default: stdio)",
    )
    mcp_group.add_argument(
        "--mcp-host",
        default="127.0.0.1",
        help="MCP server host (for non-stdio transports)",
    )
    mcp_group.add_argument(
        "--mcp-port",
        type=int,
        default=8080,
        help="MCP server port (for non-stdio transports)",
    )

    # General options
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="ibkr-mcp 1.0.0",
    )

    return parser.parse_args()


async def run_server(config: ServerConfig) -> None:
    """Run the MCP server."""
    server = IBKRMCPServer(config)

    try:
        logger.info("Starting IBKR MCP Server...")
        logger.info(f"IBKR: {config.ibkr.host}:{config.ibkr.port} (client_id={config.ibkr.client_id})")
        logger.info(f"Transport: {config.mcp.transport}")

        if config.ibkr.readonly:
            logger.warning("Running in READ-ONLY mode - trading disabled")

        await server.start()

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        await server.stop()


def main() -> None:
    """Main entry point."""
    args = parse_args()
    setup_logging(verbose=args.verbose)

    # Build configuration
    config = ServerConfig(
        ibkr=IBKRConfig(
            host=args.host,
            port=args.port,
            client_id=args.client_id,
            timeout=args.timeout,
            readonly=args.readonly,
        ),
        mcp=MCPConfig(
            host=args.mcp_host,
            port=args.mcp_port,
            transport=args.transport,
        ),
    )

    try:
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
