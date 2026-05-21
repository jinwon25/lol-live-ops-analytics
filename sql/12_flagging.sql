-- ============================================================================
-- PHASE 2 — 12. 너프 / 버프 후보 자동 플래깅
-- 이 쿼리가 답하는 질문:
--   "각 패치·포지션에서 (a) 강력하면서 너무 자주 픽되는 챔프(너프 후보)와
--    (b) 강력한데도 사장된 챔프(버프 후보)는 누구인가?"
--
-- 정의 (해당 patch · role 기준):
--   pick_count   >= 30          (그 미만은 LOW_N 으로 분리)
--   win_rate     >= 52%         (강력함의 신호)
--   pop_quartile = NTILE(4) OVER (... ORDER BY pick_count)
--     4 = 상위 25% 픽수 → NERF              (강력 + 인기)
--     1 = 하위 25% 픽수 → BUFF_HIDDEN_STRONG (강력 + 사장)
--
-- 메인 분석은 v_cohort 에서. 밴 데이터가 없으므로 픽·승률만 사용.
-- ============================================================================


-- [1] 챔프별 플래그
WITH base AS (
    SELECT
        patch, role, champion_name,
        COUNT(*) AS pick_count,
        SUM(win) AS wins
    FROM v_cohort
    GROUP BY patch, role, champion_name
),
totals AS (
    SELECT patch, SUM(pick_count) AS N FROM base GROUP BY patch
),
scored AS (
    SELECT
        b.patch, b.role, b.champion_name,
        b.pick_count,
        ROUND(100.0 * b.pick_count / t.N, 3) AS pick_rate_pct,
        1.0 * b.wins / b.pick_count          AS win_rate,
        NTILE(4) OVER (PARTITION BY b.patch, b.role ORDER BY b.pick_count) AS pop_quartile
    FROM base b
    JOIN totals t USING (patch)
)
SELECT
    patch, role, champion_name,
    pick_count, pick_rate_pct,
    ROUND(win_rate * 100, 2) AS win_rate_pct,
    pop_quartile,
    CASE
        WHEN pick_count < 30                         THEN 'LOW_N'
        WHEN win_rate >= 0.52 AND pop_quartile = 4   THEN 'NERF'
        WHEN win_rate >= 0.52 AND pop_quartile = 1   THEN 'BUFF_HIDDEN_STRONG'
        ELSE ''
    END AS flag
FROM scored
ORDER BY patch, role,
         CASE
             WHEN pick_count < 30                       THEN 3
             WHEN win_rate >= 0.52 AND pop_quartile = 4 THEN 0
             WHEN win_rate >= 0.52 AND pop_quartile = 1 THEN 1
             ELSE 2
         END,
         win_rate DESC;


-- [2] 패치 × role 별 NERF / BUFF 후보 수 (요약)
WITH x AS (
    SELECT
        patch, role, champion_name,
        COUNT(*) AS pick_count,
        1.0 * SUM(win) / COUNT(*) AS win_rate,
        NTILE(4) OVER (PARTITION BY patch, role ORDER BY COUNT(*)) AS pop_quartile
    FROM v_cohort
    GROUP BY patch, role, champion_name
)
SELECT
    patch, role,
    SUM(CASE WHEN pick_count >= 30 AND win_rate >= 0.52 AND pop_quartile = 4
             THEN 1 ELSE 0 END) AS nerf_n,
    SUM(CASE WHEN pick_count >= 30 AND win_rate >= 0.52 AND pop_quartile = 1
             THEN 1 ELSE 0 END) AS buff_n
FROM x
GROUP BY patch, role
ORDER BY patch, role;
