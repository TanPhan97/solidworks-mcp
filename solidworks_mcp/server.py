"""
SolidWorks MCP Server
---------------------
Thin MCP layer: every tool is declared once in tools_ext.TOOL_TABLE and
implemented as a method of automation.SolidWorksAutomation.

Version: 4.4.0
Original author: Samsaam Ali Baig (v3/v4, MIT). Extended by Tan Phan.
"""

import json
import logging
import traceback
from pathlib import Path
from typing import Dict

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, ImageContent

from .automation import SolidWorksAutomation
from .config import get_config
from .tools_ext import ext_tools, has_tool, dispatch

__version__ = "4.4.0"

config = get_config()
LOG_FILE = Path(__file__).parent / config.log_file
logging.basicConfig(
    level=config.get_log_level_int(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],   # never stdout: it carries MCP
)
logger = logging.getLogger("SolidWorksMCP")

sw_automation = SolidWorksAutomation()
server = Server("solidworks-mcp-server")


def format_result(r: Dict) -> str:
    lines = [f"[{'SUCCESS' if r.get('success') else 'ERROR'}] {r.get('message', '')}"]
    if not r.get("success"):
        lines.append(f"Error Code: {r.get('error_code')} ({r.get('error_name')})")
    if r.get("data"):
        lines.append("Details: " + json.dumps(r["data"], indent=2, default=str))
    return "\n".join(lines)


@server.list_tools()
async def list_tools():
    return ext_tools()


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent]:
    try:
        logger.info(f"Tool: {name}, Args: {arguments}")
        if not has_tool(name):
            return [TextContent(type="text", text=f"[ERROR] Unknown tool: {name}")]
        result = dispatch(sw_automation, name, arguments or {})
        logger.info(f"Result: success={result.get('success')}")
        image_b64 = result["data"].pop("_image_png_b64", None) if isinstance(result.get("data"), dict) else None
        content = [TextContent(type="text", text=format_result(result))]
        if image_b64:
            content.append(ImageContent(type="image", data=image_b64, mimeType="image/png"))
        return content
    except Exception as e:
        logger.error(f"Tool error: {e}\n{traceback.format_exc()}")
        return [TextContent(type="text", text=f"[ERROR] {e}")]


async def main():
    logger.info(f"Starting SolidWorks MCP Server v{__version__} ({len(ext_tools())} tools)")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run():
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    run()
