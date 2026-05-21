-- ============================================================================
-- PHASE 1 검증 쿼리 — 적재 후 원본 대비 합리성을 확인한다.
-- 실행: sqlite3 data/processed/lol.db < sql/00_validate.sql
-- 또는 src/run_validate.py 로 라벨과 함께 표 형태로 출력.
-- ============================================================================

-- [1] 패치별 game / row / 챔피언 / 평균 인원 수
SELECT
    p.patch,
    COUNT(DISTINCT p.game_id)         AS games,
    COUNT(*)                          AS rows,
    COUNT(DISTINCT p.champion_name)   AS champions,
    ROUND(1.0 * COUNT(*) /
          COUNT(DISTINCT p.game_id), 2) AS rows_per_game
FROM participants p
GROUP BY p.patch
ORDER BY p.patch;

-- [2] 패치 × 포지션 분포 (역할별로 거의 동일해야 정상)
SELECT
    patch, role, COUNT(*) AS n,
    ROUND(100.0 * COUNT(*) /
          SUM(COUNT(*)) OVER (PARTITION BY patch), 2) AS pct
FROM participants
GROUP BY patch, role
ORDER BY patch, role;

-- [3] 패치 × 게임당 인원 분포 (정상이면 10명이 압도적; 5/10명 외에는 데이터 누락 의심)
SELECT
    patch, players_per_game, COUNT(*) AS n_games
FROM (
    SELECT patch, game_id, COUNT(*) AS players_per_game
    FROM participants
    GROUP BY patch, game_id
)
GROUP BY patch, players_per_game
ORDER BY patch, players_per_game;

-- [4] 패치별 평균 게임 시간 / 평균 KDA / 평균 GPM (sanity check)
SELECT
    p.patch,
    ROUND(AVG(m.duration_sec) / 60.0, 2)    AS avg_min,
    ROUND(AVG(p.kda),    3)                 AS avg_kda,
    ROUND(AVG(p.gpm),    1)                 AS avg_gpm,
    ROUND(AVG(p.dpm_champ), 1)              AS avg_dpm
FROM participants p
JOIN matches m USING (patch, game_id)
GROUP BY p.patch
ORDER BY p.patch;

-- [5] solo_tier 분포 (UNKNOWN 비율 — P151이 더 클 것)
SELECT
    patch, solo_tier, COUNT(*) AS n,
    ROUND(100.0 * COUNT(*) /
          SUM(COUNT(*)) OVER (PARTITION BY patch), 2) AS pct
FROM participants
GROUP BY patch, solo_tier
ORDER BY patch, n DESC;

-- [6] (patch, game_id, participant_id) 중복 체크 (있으면 0이 아닌 행이 반환됨)
SELECT patch, game_id, participant_id, COUNT(*) AS dup
FROM participants
GROUP BY patch, game_id, participant_id
HAVING COUNT(*) > 1
LIMIT 20;

-- [7] kill_participation 비정상 값 (1보다 큰 값 = 팀킬 합산에 문제)
SELECT
    patch,
    SUM(CASE WHEN kill_participation > 1.001 THEN 1 ELSE 0 END) AS kp_over_1,
    SUM(CASE WHEN kill_participation IS NULL  THEN 1 ELSE 0 END) AS kp_null,
    COUNT(*)                                                     AS total
FROM participants
GROUP BY patch
ORDER BY patch;
