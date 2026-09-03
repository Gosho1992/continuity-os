"""Ingest — Gemini extracts per-episode evidence; SQL decides conflicts."""

import json
import os

from google import genai
from google.genai import types

from app.db.client import get_client

STATIC_ATTRIBUTES = {
    "eye_color", "hair_color", "height", "build", "birthmark",
    "scar", "birth_date", "hometown", "blood_relation",
}

EXTRACT_PROMPT = """You are a script supervisor reading ONE episode.

You have not read any other episode and must not assume anything about
them. Record only what THIS episode states. Never correct, complete, or
reconcile anything. If a detail seems wrong, record it exactly as
written — that is the point.

Known characters so far (reuse these ids for the same person; only
create a new id for someone genuinely new):
{known_characters}

Episode number: {episode_number}

Episode text:
---
{text}
---

Return ONLY valid JSON:

{{
  "characters": [
    {{"character_id": "lowercase_slug", "name": "Full Name",
      "role": "lead or supporting", "age": 0}}
  ],
  "attributes": [
    {{"character_id": "lowercase_slug",
      "attribute_name": "eye_color",
      "attribute_value": "green",
      "scene_number": 3,
      "source_text": "the exact sentence from the episode"}}
  ]
}}

Rules:
- source_text must be copied verbatim from the episode text.
- Record physical traits, wardrobe, location, age, and relationships.
- Use age 0 if not stated. Use scene_number 0 if unknown.
- Normalise values to single lowercase words where possible
  (green, not "a deep green"). Never add modifiers.
"""


def _known_characters(ch, project_id):
    """Return existing characters so ids stay stable across episodes."""
    rows = ch.query(
        "SELECT character_id, name FROM characters WHERE project_id = "
        "{p:String}",
        parameters={"p": project_id},
    ).result_rows
    if not rows:
        return "(none yet — this is the first episode)"
    return "\n".join(f"- {cid}: {name}" for cid, name in rows)


def ingest_episode(project_id: str, episode_number: int, text: str) -> dict:
    """Extract one episode's evidence and store it with provenance."""
    ch = get_client()
    client = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=EXTRACT_PROMPT.format(
            known_characters=_known_characters(ch, project_id),
            episode_number=episode_number,
            text=text,
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json"),
    )
    data = json.loads(response.text)

    existing = {r[0] for r in ch.query(
        "SELECT character_id FROM characters WHERE project_id = {p:String}",
        parameters={"p": project_id}).result_rows}

    new_chars = [
        [project_id, c["character_id"], c["name"], c["role"], c["age"], "", ""]
        for c in data.get("characters", [])
        if c["character_id"] not in existing
    ]
    if new_chars:
        ch.insert("characters", new_chars,
                  column_names=["project_id", "character_id", "name", "role",
                                "age", "identity_block", "backstory"])

    attr_rows = [
        [project_id, a["character_id"], a["attribute_name"],
         str(a["attribute_value"]), "ingest", episode_number,
         a.get("scene_number", 0),
         "static" if a["attribute_name"] in STATIC_ATTRIBUTES else "dynamic",
         a.get("source_text", "")]
        for a in data.get("attributes", [])
    ]
    if attr_rows:
        ch.insert("character_attributes", attr_rows,
                  column_names=["project_id", "character_id",
                                "attribute_name", "attribute_value",
                                "source_module", "episode_number",
                                "scene_number", "attribute_kind",
                                "source_text"])

    return {
        "episode": episode_number,
        "new_characters": len(new_chars),
        "facts_recorded": len(attr_rows),
    }