"""Helpers for calling the shared MCP server."""
from mcp import ClientSession


async def call_tool(session: ClientSession, name: str, arguments: dict) -> dict:
    result = await session.call_tool(name, arguments)
    if result.is_error:
        raise RuntimeError(f"MCP tool {name} failed: {result.content}")
    if not isinstance(result.structured_content, dict):
        raise ValueError(f"MCP tool {name} returned no structured object")
    return result.structured_content
