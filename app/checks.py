"""ContinuityOS QC checks. SQL decides; the model only explains."""

from app.db.client import get_client


# --- Check 1: static attribute contradiction (GROUP BY + uniqExact) -----
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
    """Static character attributes that contradict themselves.

    Dynamic attributes (wardrobe, location, mood) are excluded: they are
    expected to change. Each finding carries the episode, scene, and the
    verbatim line that produced it.
    """
    result = get_client().query(
        STATIC_CONTRADICTION, parameters={"project_id": project_id})

    findings = []
    for cid, attr, values, eps, scenes, quotes, n in result.result_rows:
        findings.append({
            "check": "character_consistency",
            "character_id": cid,
            "attribute": attr,
            "severity": "severe" if n > 2 else "moderate",
            "conflict": [
                {"value": v, "episode": e, "scene": s, "quote": q}
                for v, e, s, q in zip(values, eps, scenes, quotes)
            ],
        })
    return findings


# --- Check 2: timeline regression (segments + window functions) --------
# The model records raw cues only. The database resolves the timeline:
# every absolute anchor starts a new segment, and within a segment the
# day is the anchor plus the running sum of relative deltas.
TIMELINE_REGRESSION = """
WITH segmented AS (
    SELECT
        episode_number,
        anchor_day,
        delta_days,
        time_cue,
        sum(anchor_day >= 0) OVER (ORDER BY episode_number) AS seg_id
    FROM episodes
    WHERE project_id = {project_id:String}
),
resolved AS (
    SELECT
        episode_number,
        time_cue,
        max(anchor_day) OVER (PARTITION BY seg_id) AS seg_anchor,
        sum(delta_days) OVER (
            PARTITION BY seg_id ORDER BY episode_number
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS cum_delta
    FROM segmented
),
days AS (
    SELECT
        episode_number,
        time_cue,
        if(seg_anchor >= 0, seg_anchor, 1) + cum_delta AS story_day
    FROM resolved
)
SELECT
    episode_number,
    story_day,
    time_cue,
    lagInFrame(episode_number) OVER (ORDER BY episode_number) AS prev_ep,
    lagInFrame(story_day)      OVER (ORDER BY episode_number) AS prev_day
FROM days
QUALIFY prev_ep > 0 AND story_day < prev_day
ORDER BY episode_number
"""


def run_timeline_consistency(project_id):
    """Episodes where resolved story time moves backwards.

    The model never computes a date. It records only the cue it saw
    ("three weeks later", "flashback to week one"). The database turns
    those cues into a timeline and decides whether time regressed.
    """
    result = get_client().query(
        TIMELINE_REGRESSION, parameters={"project_id": project_id})

    return [{
        "check": "timeline_consistency",
        "severity": "severe",
        "episode": ep,
        "detail": (f"Episode {ep} resolves to story day {day}, but "
                   f"episode {prev_ep} was already at day {prev_day}. "
                   f"Story time moves backwards."),
        "conflict": [
            {"episode": prev_ep, "story_day": prev_day},
            {"episode": ep, "story_day": day, "quote": cue},
        ],
    } for ep, day, cue, prev_ep, prev_day in result.result_rows]


# --- Check 3: unresolved plot threads (countIf + HAVING) ---------------
# A question the season plants and never answers. Each episode reports
# only what it planted or answered; no episode knows what the rest of
# the season does with a thread. The database decides what was left
# hanging.
DANGLING_THREADS = """
SELECT
    thread_id,
    min(episode_number)                  AS planted_episode,
    max(episode_number)                  AS last_touched,
    countIf(point_type = 'setup')        AS setups,
    argMin(description, episode_number)  AS planted_text
FROM plot_points
WHERE project_id = {project_id:String}
GROUP BY thread_id
HAVING countIf(point_type = 'reveal') = 0
ORDER BY planted_episode
"""


def run_plot_consistency(project_id):
    """Story threads that are planted but never paid off."""
    result = get_client().query(
        DANGLING_THREADS, parameters={"project_id": project_id})

    return [{
        "check": "plot_consistency",
        "severity": "severe",
        "thread_id": thread,
        "detail": (f"Thread planted in episode {planted} is never paid "
                   f"off. It is raised {setups} time(s), last touched in "
                   f"episode {last}, and no episode reveals the answer."),
        "conflict": [
            {"role": "setup", "episode": planted, "quote": text},
        ],
    } for thread, planted, last, setups, text in result.result_rows]


# --- Check 4: repeated dialogue (GROUP BY + count) ----------------------
DIALOGUE_REPETITION = """
SELECT
    line_text,
    count()                    AS times_used,
    groupArray(episode_number) AS episodes,
    groupArray(speaker)        AS speakers
FROM dialogue_lines
WHERE project_id = {project_id:String}
  AND length(line_text) > 15
GROUP BY line_text
HAVING times_used > 1
ORDER BY times_used DESC
"""


def run_dialogue_repetition(project_id):
    """Lines reused across the season."""
    result = get_client().query(
        DIALOGUE_REPETITION, parameters={"project_id": project_id})

    return [{
        "check": "dialogue_repetition",
        "severity": "severe" if n > 2 else "moderate",
        "line": line,
        "times_used": n,
        "conflict": [
            {"episode": e, "speaker": sp, "quote": line}
            for e, sp in zip(eps, speakers)
        ],
    } for line, n, eps, speakers in result.result_rows]


# --- Runner -------------------------------------------------------------
CHECKS = {
    "character_consistency": run_character_consistency,
    "timeline_consistency": run_timeline_consistency,
    "plot_consistency": run_plot_consistency,
    "dialogue_repetition": run_dialogue_repetition,
}


def run_all_checks(project_id):
    """Run every deterministic check and return all findings."""
    findings = []
    for fn in CHECKS.values():
        findings.extend(fn(project_id))
    return findings


if __name__ == "__main__":
    import json
    import sys
    project = sys.argv[1] if len(sys.argv) > 1 else "demo1"
    print(json.dumps(run_all_checks(project), indent=2))