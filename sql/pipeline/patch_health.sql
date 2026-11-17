-- BI의 표본·출처 카드에 사용할 요약. 승패 원인이나 패치 인과효과를 뜻하지 않는다.
SELECT patch, count(DISTINCT game_id) AS games, count(*) AS participants,
       avg(duration_sec) / 60 AS mean_duration_minutes,
       avg(gpm) AS mean_gpm, avg(dpm_champ) AS mean_dpm,
       sum(CASE WHEN solo_tier = 'UNKNOWN' THEN 1 ELSE 0 END) AS unknown_tier_rows,
       sum(CASE WHEN kill_participation IS NULL THEN 1 ELSE 0 END) AS null_kp_rows
FROM participants GROUP BY patch ORDER BY patch
