"""ContinuityOS QC agent — Gemini explains; ClickHouse decides."""

from google.adk.agents import Agent

from app.checks import run_character_consistency


def check_character_consistency(project_id: str) -> dict:
    """Find character attributes that contradict themselves across episodes.

    Args:
        project_id: The project to check.

    Returns:
        A dict with the findings from the continuity database.
    """
    findings = run_character_consistency(project_id)
    return {"status": "success", "findings": findings}


root_agent = Agent(
    name="continuity_qc_agent",
    model="gemini-2.5-flash",
    description="Continuity QC for AI-generated vertical drama series.",
    instruction=(
        "You are a continuity supervisor for a vertical drama series.\n"
        "You do NOT judge continuity yourself. The database does.\n"
        "Call the tool, then report exactly what it returned:\n"
        "which character, which attribute, which values, which episodes.\n"
        "Never invent a finding the tool did not return.\n"
        "Never omit a finding the tool did return.\n"
        "If the tool returns nothing, say the check passed."
    ),
    tools=[check_character_consistency],
)