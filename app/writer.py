"""Writer agent — turns a premise into a season, then indexes it."""

import json
import os

from google import genai
from google.genai import types

from app.db.client import get_client

PROMPT = """You are a vertical drama showrunner.

Premise: {premise}
Episodes to plan: {episodes}

Return ONLY valid JSON, no markdown fences, in this exact shape:

{{
  "title": "series title",
  "genre": "one word",
  "characters": [
    {{
      "character_id": "lowercase_slug",
      "name": "Full Name",
      "role": "lead or supporting",
      "age": 28,
      "attributes": {{"eye_color": "brown", "hair_color": "black",
                      "height": "tall", "build": "slim"}},
      "backstory": "two sentences"
    }}
  ],
  "episodes": [
    {{
      "episode_number": 1,
      "title": "episode title",
      "synopsis": "three sentences",
      "cliffhanger_type": "reveal|betrayal|arrival|threat|confession",
      "romance_rung": 1,
      "story_week": 1
    }}
  ]
}}

Rules:
- Exactly 2 lead characters.
- romance_rung rises by at most 1 per episode.
- story_week never goes backwards.
- Never repeat a cliffhanger_type in consecutive episodes.

Attribute values must come ONLY from these lists:
- eye_color: brown, blue, green, hazel, grey
- hair_color: black, brown, blonde, red, auburn
- height: short, average, tall
- build: slim, athletic, heavy
Use the exact word. Never add a modifier like "dark" or "light".
"""


def generate_season(premise: str, episodes: int = 8) -> dict:
    """Generate a story bible and episode outline from a premise."""
    client = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=PROMPT.format(premise=premise, episodes=episodes),
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return json.loads(response.text)


def index_season(project_id: str, premise: str, season: dict) -> dict:
    """Write a generated season into ClickHouse."""
    ch = get_client()

    ch.insert(
        "projects",
        [[project_id, season["title"], premise, season["genre"],
          len(season["episodes"])]],
        column_names=["project_id", "title", "premise", "genre",
                      "total_episodes"],
    )

    char_rows, attr_rows = [], []
    for c in season["characters"]:
        char_rows.append([project_id, c["character_id"], c["name"],
                          c["role"], c["age"], "", c["backstory"]])
        for name, value in c["attributes"].items():
            attr_rows.append([project_id, c["character_id"], name,
                              str(value), "M03", 1, 1])

    ch.insert("characters", char_rows,
              column_names=["project_id", "character_id", "name", "role",
                            "age", "identity_block", "backstory"])
    ch.insert("character_attributes", attr_rows,
              column_names=["project_id", "character_id", "attribute_name",
                            "attribute_value", "source_module",
                            "episode_number", "scene_number"])

    ep_rows = [[project_id, e["episode_number"], e["title"], e["synopsis"],
                e["cliffhanger_type"], e["romance_rung"], e["story_week"], 0]
               for e in season["episodes"]]
    ch.insert("episodes", ep_rows,
              column_names=["project_id", "episode_number", "title",
                            "synopsis", "cliffhanger_type", "romance_rung",
                            "story_week", "word_count"])

    return {
        "project_id": project_id,
        "characters": len(char_rows),
        "attributes": len(attr_rows),
        "episodes": len(ep_rows),
    }


if __name__ == "__main__":
    p = "A woman discovers her new boss is the stranger she married in Vegas."
    season = generate_season(p, episodes=8)
    print("Generated:", season["title"])
    print(index_season("vegas", p, season))