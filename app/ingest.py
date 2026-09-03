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

Open story threads so far (reuse a thread_id if this episode continues
or answers that thread; only create a new id for a genuinely new one):
{known_threads}

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
  ],
  "episode": {{
    "title": "episode title or empty string",
    "synopsis": "two sentences of what happens",
    "cliffhanger_type": "reveal|betrayal|arrival|threat|confession|none",
    "romance_rung": 0,
    "anchor_day": -1,
    "delta_days": 0,
    "time_cue": ""
  }},
  "plot_points": [
    {{"thread_id": "lowercase_slug_for_the_thread",
      "point_type": "setup or reveal",
      "description": "what is planted or revealed",
      "scene_number": 3}}
  ],
  "dialogue": [
    {{"speaker": "character_id", "line_text": "the exact line",
      "scene_number": 1}}
  ]
}}

Rules:
- source_text must be copied verbatim from the episode text.
- Record physical traits, wardrobe, location, age, and relationships.
- Use age 0 if not stated. Use scene_number 0 if unknown.
- Normalise values to single lowercase words where possible
  (green, not "a deep green"). Never add modifiers.
- romance_rung: 0 = strangers, 1 = aware, 2 = tension, 3 = first touch,
  4 = kiss, 5 = together, 6 = committed. Judge from THIS episode only.
- plot_points: a "setup" plants a question; a "reveal" answers one.
  Match against the open threads listed above before inventing a new id.
- dialogue: record every spoken line with its speaker.

Time. You are a witness, not a mathematician. Never add days across
episodes. Record only what THIS episode's text states:
- time_cue: the exact time phrase, copied verbatim ("three weeks
  later", "meanwhile", "flashback to week one"). Empty if none.
- anchor_day: if the cue names an absolute point in the story
  ("week one", "that first Monday", "day 40"), give the day number,
  counting the story's first day as day 1. Week N starts at day
  (N-1)*7+1, so "week one" is 1 and "week three" is 15. Use -1 if the
  cue is not absolute.
- delta_days: if the cue is relative to the previous episode ("three
  weeks later" = 21, "the following week" = 7, "two days pass" = 2,
  "meanwhile" = 0), give that number of days. Use 0 if there is no
  relative cue.
If a cue is absolute, set anchor_day and leave delta_days at 0.
"""


def _known_characters(ch, project_id):
    """Existing characters, so ids stay stable across episodes."""
    rows = ch.query(
        "SELECT character_id, name FROM characters "
        "WHERE project_id = {p:String}",
        parameters={"p": project_id},
    ).result_rows
    if not rows:
        return "(none yet — this is the first episode)"
    return "\n".join(f"- {cid}: {name}" for cid, name in rows)


def _known_threads(ch, project_id):
    """Existing plot threads, so setups and reveals link up."""
    rows = ch.query(
        "SELECT thread_id, any(description) AS d, min(episode_number) AS e "
        "FROM plot_points WHERE project_id = {p:String} "
        "GROUP BY thread_id ORDER BY e",
        parameters={"p": project_id},
    ).result_rows
    if not rows:
        return "(none yet — this is the first episode)"
    return "\n".join(f"- {tid} (from ep {ep}): {desc}"
                     for tid, desc, ep in rows)


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
            known_threads=_known_threads(ch, project_id),
            episode_number=episode_number,
            text=text,
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json"),
    )
    data = json.loads(response.text)

    # --- characters (only genuinely new ones) ---
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

    # --- attributes, with provenance and static/dynamic typing ---
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

    # --- episode record: raw time cues only, no arithmetic ---
    ep = data.get("episode", {})
    dialogue = data.get("dialogue", [])
    word_count = sum(len(d.get("line_text", "").split()) for d in dialogue)
    ch.insert(
        "episodes",
        [[project_id, episode_number, ep.get("title", ""),
          ep.get("synopsis", ""), ep.get("cliffhanger_type", "none"),
          ep.get("romance_rung", 0), 1, word_count,
          int(ep.get("anchor_day", -1)), int(ep.get("delta_days", 0)),
          ep.get("time_cue", "")]],
        column_names=["project_id", "episode_number", "title", "synopsis",
                      "cliffhanger_type", "romance_rung", "story_week",
                      "word_count", "anchor_day", "delta_days", "time_cue"],
    )

    # --- plot points (drives setup/reveal ordering check) ---
    plot_rows = [
        [project_id, p["thread_id"], p["point_type"], p["description"],
         episode_number, p.get("scene_number", 0)]
        for p in data.get("plot_points", [])
    ]
    if plot_rows:
        ch.insert("plot_points", plot_rows,
                  column_names=["project_id", "thread_id", "point_type",
                                "description", "episode_number",
                                "scene_number"])

    # --- dialogue lines (drives repetition and word-budget checks) ---
    dlg_rows = [
        [project_id, episode_number, d.get("scene_number", 0), i,
         d.get("speaker", ""), d.get("line_text", ""),
         len(d.get("line_text", "").split())]
        for i, d in enumerate(dialogue, start=1)
    ]
    if dlg_rows:
        ch.insert("dialogue_lines", dlg_rows,
                  column_names=["project_id", "episode_number",
                                "scene_number", "line_number", "speaker",
                                "line_text", "word_count"])

    return {
        "episode": episode_number,
        "new_characters": len(new_chars),
        "facts_recorded": len(attr_rows),
        "plot_points": len(plot_rows),
        "dialogue_lines": len(dlg_rows),
        "time_cue": ep.get("time_cue", ""),
        "anchor_day": ep.get("anchor_day", -1),
        "delta_days": ep.get("delta_days", 0),
    }