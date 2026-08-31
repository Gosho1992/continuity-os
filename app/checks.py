"""ContinuityOS — QC checks. SQL decides; the model only explains."""

from app.db.client import get_client

CHARACTER_CONSISTENCY = """
SELECT
    character_id,
    attribute_name,
    groupArray(attribute_value) AS conflicting_values,
    groupArray(episode_number)  AS episodes,
    uniqExact(attribute_value)  AS variant_count
FROM character_attributes
WHERE project_id = {project_id:String}
GROUP BY character_id, attribute_name
HAVING variant_count > 1
"""


def run_character_consistency(project_id):
    """Return every character attribute that contradicts itself."""
    client = get_client()
    result = client.query(
        CHARACTER_CONSISTENCY,
        parameters={"project_id": project_id},
    )
    findings = []
    for row in result.result_rows:
        findings.append({
            "character_id": row[0],
            "attribute": row[1],
            "values": row[2],
            "episodes": row[3],
            "severity": "severe" if row[4] > 2 else "moderate",
        })
    return findings


if __name__ == "__main__":
    for f in run_character_consistency("demo"):
        print(f)