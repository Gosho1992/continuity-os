-- ================================================================
-- ContinuityOS — QC Checks
-- Har check ek query hai. Har query saboot ke sath finding deti hai.
-- ================================================================

-- name: character_consistency
-- Ek khaasiyat mukhtalif jaghon par mukhtalif likhi gayi
SELECT
    character_id,
    attribute_name,
    groupArray(attribute_value) AS conflicting_values,
    groupArray(episode_number)  AS episodes,
    uniqExact(attribute_value)  AS variant_count
FROM character_attributes
WHERE project_id = {project_id:String}
GROUP BY character_id, attribute_name
HAVING variant_count > 1;

-- name: plot_consistency
-- Reveal apne setup se pehle aa gaya
SELECT
    s.thread_id,
    s.description AS setup,
    s.episode_number AS setup_ep,
    r.description AS reveal,
    r.episode_number AS reveal_ep
FROM plot_points AS s
INNER JOIN plot_points AS r ON s.thread_id = r.thread_id
WHERE s.project_id = {project_id:String}
  AND s.point_type = 'setup'
  AND r.point_type = 'reveal'
  AND r.episode_number <= s.episode_number;

-- name: timeline_consistency
-- Baad ka episode pehle ke hafte mein chala gaya
SELECT
    episode_number,
    story_week,
    lagInFrame(story_week) OVER (ORDER BY episode_number) AS prev_week
FROM episodes
WHERE project_id = {project_id:String}
QUALIFY story_week < prev_week;

-- name: emotional_consistency
-- Bara emotional jump jis ki koi wajah nahi likhi
SELECT
    character_id,
    axis,
    episode_number,
    value,
    lagInFrame(value) OVER (
        PARTITION BY character_id, axis ORDER BY episode_number
    ) AS prev_value,
    cause
FROM emotional_states
WHERE project_id = {project_id:String}
QUALIFY abs(value - prev_value) >= 3 AND (cause = '' OR cause IS NULL);

-- name: pacing_cliffhanger
-- Ek hi cliffhanger type lagatar dohraya gaya
SELECT
    episode_number,
    cliffhanger_type,
    lagInFrame(cliffhanger_type) OVER (ORDER BY episode_number) AS prev_type
FROM episodes
WHERE project_id = {project_id:String}
QUALIFY cliffhanger_type = prev_type;

-- name: pacing_romance
-- Romance ladder ka rung chhoot gaya ya peechhe chala gaya
SELECT
    episode_number,
    romance_rung,
    lagInFrame(romance_rung) OVER (ORDER BY episode_number) AS prev_rung
FROM episodes
WHERE project_id = {project_id:String}
QUALIFY romance_rung < prev_rung OR romance_rung - prev_rung > 1;

-- name: dialogue_repetition
-- Ek hi line baar baar istemal hui
SELECT
    line_text,
    count() AS times_used,
    groupArray(episode_number) AS episodes
FROM dialogue_lines
WHERE project_id = {project_id:String}
  AND length(line_text) > 20
GROUP BY line_text
HAVING times_used > 1;

-- name: dialogue_word_budget
-- Episode apni word limit se bahar chala gaya
SELECT
    episode_number,
    sum(word_count) AS total_words
FROM dialogue_lines
WHERE project_id = {project_id:String}
GROUP BY episode_number
HAVING total_words > {word_ceiling:UInt32};

-- name: scene_repetition
-- Ek hi location aur mood ka combination hadd se zyada
SELECT
    location,
    camera_mood,
    count() AS scene_count
FROM scenes
WHERE project_id = {project_id:String}
GROUP BY location, camera_mood
HAVING scene_count > {scene_ceiling:UInt16};