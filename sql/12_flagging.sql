-- ============================================================================
-- PHASE 2 — 12. 너프 / 버프 후보 자동 플래깅
-- 이 쿼리가 답하는 질문:
--   "각 패치·포지션에서 (a) 강력하면서 너무 자주 픽되는 챔프(너프 후보)와
--    (b) 강력한데도 사장된 챔프(버프 후보)는 누구인가?"
--
-- 정의 (해당 patch · role 기준):
--   pop_quartile = NTILE(4) OVER (... ORDER BY pick_count)
--
--   NERF (강력 + 인기 = OP):
--     pick_count   >= 30   (인기 신호이므로 표본도 자연히 큼)
--     win_rate     >= 52%
--     pop_quartile = 4
--
--   BUFF_HIDDEN_STRONG (강력 + 사장):
--     "사장됐으니 표본이 적은 것" 자체가 정의의 본질.  컷을 30으로 두면 찾고 싶은
--     대상을 자기모순으로 제거한다.  또한 NTILE quartile=1 만 쓰면 pick_count 가
--     거의 다 1~4 라 어떤 표본 컷도 통과할 수 없다(데이터로 검증됨, 메모 §6).
--
--     해결: "인기 톱 25% 가 아님" (pop_quartile != 4) 로 비주류를 정의하고,
--     작은 표본의 노이즈는 Wilson 95% 신뢰구간 하한으로 막는다.
--
--     pick_count   >= 15                       (노이즈 컷)
--     pop_quartile != 4                        (인기 톱25% 제외 = 비주류)
--     wilson_lower(win_rate, n) >= 0.50        (표본 작아도 통계적으로 강함 보장)
--
--   LOW_N : 위 두 라벨 어느 쪽도 만족 못하고 pick_count < 15
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
        NTILE(4) OVER (PARTITION BY b.patch, b.role ORDER BY b.pick_count) AS pop_quartile,
        -- Wilson 95% lower bound for binomial proportion (win_rate)
        ( ( 1.0*b.wins/b.pick_count + 1.96*1.96/(2.0*b.pick_count)
          - 1.96 * SQRT( (1.0*b.wins/b.pick_count)*(1 - 1.0*b.wins/b.pick_count)/b.pick_count
                         + 1.96*1.96/(4.0*b.pick_count*b.pick_count) )
          )
          / (1 + 1.96*1.96/b.pick_count)
        ) AS wilson_low
    FROM base b
    JOIN totals t USING (patch)
)
SELECT
    patch, role, champion_name,
    pick_count, pick_rate_pct,
    ROUND(win_rate * 100, 2)   AS win_rate_pct,
    ROUND(wilson_low * 100, 2) AS wilson_low_pct,
    pop_quartile,
    CASE
        WHEN pick_count >= 30 AND win_rate >= 0.52 AND pop_quartile  = 4 THEN 'NERF'
        WHEN pick_count >= 15 AND wilson_low >= 0.50 AND pop_quartile != 4 THEN 'BUFF_HIDDEN_STRONG'
        WHEN pick_count <  15                                             THEN 'LOW_N'
        ELSE ''
    END AS flag
FROM scored
ORDER BY patch, role,
         CASE
             WHEN pick_count >= 30 AND win_rate >= 0.52 AND pop_quartile  = 4 THEN 0
             WHEN pick_count >= 15 AND wilson_low >= 0.50 AND pop_quartile != 4 THEN 1
             WHEN pick_count <  15                                             THEN 3
             ELSE 2
         END,
         win_rate DESC;


-- [2] 패치 × role 별 NERF / BUFF 후보 수 (요약)
WITH base AS (
    SELECT
        patch, role, champion_name,
        COUNT(*) AS pick_count,
        SUM(win) AS wins,
        1.0 * SUM(win) / COUNT(*) AS win_rate,
        NTILE(4) OVER (PARTITION BY patch, role ORDER BY COUNT(*)) AS pop_quartile
    FROM v_cohort
    GROUP BY patch, role, champion_name
),
scored AS (
    SELECT *,
        ( ( win_rate + 1.96*1.96/(2.0*pick_count)
          - 1.96 * SQRT( win_rate*(1-win_rate)/pick_count
                         + 1.96*1.96/(4.0*pick_count*pick_count) )
          ) / (1 + 1.96*1.96/pick_count)
        ) AS wilson_low
    FROM base
)
SELECT
    patch, role,
    SUM(CASE WHEN pick_count >= 30 AND win_rate >= 0.52 AND pop_quartile  = 4
             THEN 1 ELSE 0 END) AS nerf_n,
    SUM(CASE WHEN pick_count >= 15 AND wilson_low >= 0.50 AND pop_quartile != 4
             THEN 1 ELSE 0 END) AS buff_n
FROM scored
GROUP BY patch, role
ORDER BY patch, role;
