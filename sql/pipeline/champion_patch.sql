-- 과거 EUN 표본의 전체·공통 티어 비교. 역할별 참여 행을 픽 비중의 분모로 사용한다.
WITH cohorts AS (
    SELECT *, 'all' AS cohort FROM participants
    UNION ALL
    SELECT *, 'common_tiers' AS cohort FROM participants
    WHERE solo_tier IN ('PLATINUM', 'EMERALD', 'DIAMOND')
), counts AS (
    SELECT patch, cohort, role, champion_name, max(champion_ko) AS champion_ko,
           count(*) AS games, sum(win) AS wins
    FROM cohorts GROUP BY patch, cohort, role, champion_name
), rates AS (
    SELECT *, sum(games) OVER (PARTITION BY patch, cohort, role) AS role_participants,
           wins * 1.0 / games AS p, 1 + 3.8416 / games AS denominator
    FROM counts
)
SELECT patch, cohort, role, champion_name, champion_ko, games, wins, role_participants,
       games * 100.0 / role_participants AS pick_rate_pct,
       CASE WHEN games >= 30 THEN p * 100 END AS win_rate_pct,
       CASE WHEN games >= 30 THEN 100 * (p + 3.8416 / (2 * games)
           - 1.96 * sqrt(p * (1-p) / games + 3.8416 / (4 * games * games))) / denominator END AS wilson_low_pct,
       CASE WHEN games >= 30 THEN 100 * (p + 3.8416 / (2 * games)
           + 1.96 * sqrt(p * (1-p) / games + 3.8416 / (4 * games * games))) / denominator END AS wilson_high_pct
FROM rates
ORDER BY patch, cohort, role, games DESC, champion_name
