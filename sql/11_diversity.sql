-- ============================================================================
-- PHASE 2 — 11. 메타 다양성 (HHI · Gini · 유효 챔프 수)
-- 이 쿼리가 답하는 질문:
--   "각 포지션의 메타는 얼마나 다양한가(소수 챔프 쏠림 vs 고르게 분포)?
--    패치마다, 포지션마다 다양성이 어떻게 다른가?"
--
-- 메인 분석은 v_cohort 위에서. HHI = Σ share_i² (낮을수록 다양),
-- effective_champs = 1 / HHI (다양성을 '동등 분포 N개 챔프'로 환산),
-- Gini = 2 Σ(rk·share)/k − (k+1)/k (낮을수록 평등).
-- ============================================================================


-- [1] patch × role 다양성 지표
WITH cp AS (
    SELECT patch, role, champion_name, COUNT(*) AS n
    FROM v_cohort
    GROUP BY patch, role, champion_name
),
ranked AS (
    SELECT
        patch, role, champion_name, n,
        1.0 * n / SUM(n) OVER (PARTITION BY patch, role)        AS share,
        ROW_NUMBER() OVER (PARTITION BY patch, role ORDER BY n) AS rk,
        COUNT(*)     OVER (PARTITION BY patch, role)            AS k
    FROM cp
)
SELECT
    patch,
    role,
    MAX(k)                                                       AS unique_champs,
    ROUND(SUM(share * share), 5)                                 AS hhi,
    ROUND(1.0 / SUM(share * share), 1)                           AS effective_champs,
    ROUND(2.0 * SUM(rk * share) / MAX(k)
          - (MAX(k) + 1.0) / MAX(k), 4)                          AS gini
FROM ranked
GROUP BY patch, role
ORDER BY patch, role;
