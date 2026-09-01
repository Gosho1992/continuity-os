"""ContinuityOS QC agent — ClickHouse decides; Gemini only explains."""

import os

from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_toolset import (
    McpToolset,
    StdioConnectionParams,
)
from mcp import StdioServerParameters

from app.checks import run_character_consistency


def check_character_consistency(project_id: str) -> dict:
    """Run the deterministic character continuity check.

    This is the authoritative check. It always runs the same SQL.

    Args:
        project_id: The project to check.

    Returns:
        A dict with the findings from the continuity database.
    """
    findings = run_character_consistency(project_id)
    return {"status": "success", "findings": findings}


clickhouse_mcp = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="mcp-clickhouse",
            args=[],
            env={
                "CLICKHOUSE_HOST": os.environ["CLICKHOUSE_HOST"],
                "CLICKHOUSE_PORT": os.environ.get("CLICKHOUSE_PORT", "8443"),
                "CLICKHOUSE_USER": os.environ.get("CLICKHOUSE_USER", "default"),
                "CLICKHOUSE_PASSWORD": os.environ["CLICKHOUSE_PASSWORD"],
                "CLICKHOUSE_SECURE": "true",
            },
        ),
        timeout=60,
    ),
)


root_agent = Agent(
    name="continuity_qc_agent",
    model="gemini-2.5-flash",
    description="Continuity QC for AI-generated vertical drama series.",
    instruction=(
        "You are a continuity supervisor for a vertical drama series.\n"
        "\n"
        "You do NOT judge continuity yourself. The database does.\n"
        "To decide whether continuity is broken, you must call\n"
        "check_character_consistency. That check is authoritative.\n"
        "Never invent a finding it did not return.\n"
        "Never omit a finding it did return.\n"
        "If it returns nothing, say the check passed.\n"
        "\n"
        "You may use the ClickHouse MCP tools to look up supporting\n"
        "detail — scene text, character records, episode context —\n"
        "once a finding exists. Use them to explain and to suggest a\n"
        "fix, never to decide whether a violation occurred."
    ),
    tools=[check_character_consistency, clickhouse_mcp],
)