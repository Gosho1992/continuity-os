"""ContinuityOS QC checks. SQL decides; the model only explains."""

from app.db.client import get_client

# Only static attributes can contradict. Wardrobe and location change
# by design — a character changing clothes is not a continuity error.
STATIC_CONTRADICTION = """
SELECT
    character_id,
    attribute_name,
    groupArray(attribute_value) AS values,
    groupArray(episode_number)  AS episodes,
    groupArray(scene_number)    AS scenes,
    groupArray(source_text)     AS evidence,
    uniqExact(attribute_value)  AS variant_count
FROM character_attributes
WHERE project_id = {project_id:String}
  AND attribute_kind = 'static'
GROUP BY character_id, attribute_name
HAVING variant_count > 1
ORDER BY variant_count DESC, character_id
"""


def run_character_consistency(project_id):
    """Return every static character attribute that contradicts itself.

    Dynamic attributes (wardrobe, location, mood) are excluded: they are
    expected to change. Each finding carries the episode, scene, and the
    verbatim line that produced it.
    """
    client = get_client()
    result = client.query(
        STATIC_CONTRADICTION,
        parameters={"project_id": project_id},
    )

    findings = []
    for row in result.result_rows:
        character_id, attribute, values, episodes, scenes, evidence, n = row
        findings.append({
            "character_id": character_id,
            "attribute": attribute,
            "severity": "severe" if n > 2 else "moderate",
            "conflict": [
                {
                    "value": v,
                    "episode": e,
                    "scene": s,
                    "quote": q,
                }
                for v, e, s, q in zip(values, episodes, scenes, evidence)
            ],
        })
    return findings


if __name__ == "__main__":
    import json
    import sys
    project = sys.argv[1] if len(sys.argv) > 1 else "demo"
    print(json.dumps(run_character_consistency(project), indent=2))