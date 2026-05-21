-- ============================================================================
-- PHASE 2 — 10. 챔피언 × 포지션 통계
-- 이 쿼리가 답하는 질문:
--   "각 패치(15.1, 15.3)에서 챔프×포지션 조합이 얼마나 픽되고, 승률은 얼마이며,
--    KDA/GPM/시야 평균은 어떤가? 표본이 충분한 조합은 무엇인가?"
--
-- 메인 분석은 v_cohort(PLAT+EM+DIA)에서. pick_rate 분모는 코호트 패치 전체 픽 수.
-- pick_count < 30 이면 신뢰구간이 넓으므로 LOW_N 플래그를 따로 노출.
-- ============================================================================


-- [1] patch × champion × role 통계
WITH base AS (
    SELECT
        patch,
        champion_name,
        role,
        COUNT(*)           AS pick_count,
        SUM(win)           AS wins,
        AVG(kda)           AS avg_kda,
        AVG(gpm)           AS avg_gpm,
        AVG(vision_score)  AS avg_vision
    FROM v_cohort
    GROUP BY patch, champion_name, role
),
totals AS (
    SELECT patch, SUM(pick_count) AS N FROM base GROUP BY patch
)
SELECT
    b.patch,
    b.champion_name,
    b.role,
    b.pick_count,
    ROUND(100.0 * b.pick_count / t.N, 3)        AS pick_rate_pct,
    ROUND(100.0 * b.wins      / b.pick_count, 2) AS win_rate_pct,
    ROUND(b.avg_kda,    3)                       AS avg_kda,
    ROUND(b.avg_gpm,    1)                       AS avg_gpm,
    ROUND(b.avg_vision, 2)                       AS avg_vision,
    CASE WHEN b.pick_count < 30 THEN 'LOW_N' ELSE '' END AS sample_flag
FROM base b
JOIN totals t USING (patch)
ORDER BY b.patch, b.pick_count DESC;
