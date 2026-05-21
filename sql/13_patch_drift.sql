-- ============================================================================
-- PHASE 2 — 13. 패치 15.1 → 15.3 드리프트
-- 이 쿼리가 답하는 질문:
--   "이번 패치 전환으로 떠오른 챔프 / 저문 챔프는 누구인가?
--    그 변화가 진짜 메타 변화인지 표본 노이즈인지, 신뢰구간으로 갈라낼 수 있는가?
--    그리고 티어 분포 통제(코호트)와 미통제(naïve)는 결과가 얼마나 다른가?"
--
-- 메인 = v_cohort(PLAT+EM+DIA). 대조 = participants 전체.
-- 모든 표는 n_15_1 / n_15_3 컬럼을 함께 노출해 표본 적은 챔프의 불확실성을 드러냄.
-- 픽률 변화 신뢰구간은 두 비율 차의 정규근사(95%) 사용.
-- ============================================================================


DROP VIEW IF EXISTS v_drift_cohort;
DROP VIEW IF EXISTS v_drift_naive;


-- 메인 view : 코호트 드리프트
CREATE VIEW v_drift_cohort AS
WITH totals AS (
    SELECT
        (SELECT COUNT(*) FROM v_cohort WHERE patch='15.1') AS N1,
        (SELECT COUNT(*) FROM v_cohort WHERE patch='15.3') AS N3
),
s1 AS (
    SELECT champion_name, COUNT(*) AS n1, SUM(win) AS w1
    FROM v_cohort WHERE patch='15.1' GROUP BY champion_name
),
s3 AS (
    SELECT champion_name, COUNT(*) AS n3, SUM(win) AS w3
    FROM v_cohort WHERE patch='15.3' GROUP BY champion_name
),
champs AS (
    SELECT champion_name FROM s1
    UNION
    SELECT champion_name FROM s3
),
joined AS (
    SELECT
        c.champion_name,
        COALESCE(s1.n1, 0) AS n_15_1,
        COALESCE(s3.n3, 0) AS n_15_3,
        COALESCE(s1.w1, 0) AS w_15_1,
        COALESCE(s3.w3, 0) AS w_15_3,
        t.N1, t.N3
    FROM champs c
    CROSS JOIN totals t
    LEFT JOIN s1 USING (champion_name)
    LEFT JOIN s3 USING (champion_name)
),
stats AS (
    SELECT
        *,
        1.0 * n_15_1 / N1                                     AS pr1,
        1.0 * n_15_3 / N3                                     AS pr3,
        CASE WHEN n_15_1=0 THEN NULL ELSE 1.0*w_15_1/n_15_1 END AS wr1,
        CASE WHEN n_15_3=0 THEN NULL ELSE 1.0*w_15_3/n_15_3 END AS wr3
    FROM joined
)
SELECT
    champion_name,
    n_15_1, n_15_3,
    ROUND(pr1*100, 3)              AS pickrate_15_1_pct,
    ROUND(pr3*100, 3)              AS pickrate_15_3_pct,
    ROUND((pr3 - pr1)*100, 3)      AS pickrate_diff_pp,
    ROUND(((pr3 - pr1) - 1.96 * SQRT(pr1*(1-pr1)/N1 + pr3*(1-pr3)/N3)) * 100, 3) AS pr_ci_low_pp,
    ROUND(((pr3 - pr1) + 1.96 * SQRT(pr1*(1-pr1)/N1 + pr3*(1-pr3)/N3)) * 100, 3) AS pr_ci_high_pp,
    CASE WHEN wr1 IS NULL THEN NULL ELSE ROUND(wr1*100, 2) END AS winrate_15_1_pct,
    CASE WHEN wr3 IS NULL THEN NULL ELSE ROUND(wr3*100, 2) END AS winrate_15_3_pct,
    CASE WHEN wr1 IS NULL OR wr3 IS NULL THEN NULL
         ELSE ROUND((wr3 - wr1)*100, 2) END                   AS winrate_diff_pp,
    CASE WHEN n_15_1=0 OR n_15_3=0 THEN NULL
         ELSE ROUND(((wr3 - wr1) - 1.96 *
                     SQRT(wr1*(1-wr1)/n_15_1 + wr3*(1-wr3)/n_15_3)) * 100, 2)
    END                                                       AS wr_ci_low_pp,
    CASE WHEN n_15_1=0 OR n_15_3=0 THEN NULL
         ELSE ROUND(((wr3 - wr1) + 1.96 *
                     SQRT(wr1*(1-wr1)/n_15_1 + wr3*(1-wr3)/n_15_3)) * 100, 2)
    END                                                       AS wr_ci_high_pp
FROM stats;


-- 대조 view : naïve 전체 풀
CREATE VIEW v_drift_naive AS
WITH totals AS (
    SELECT
        (SELECT COUNT(*) FROM participants WHERE patch='15.1') AS N1,
        (SELECT COUNT(*) FROM participants WHERE patch='15.3') AS N3
),
s1 AS (
    SELECT champion_name, COUNT(*) AS n1, SUM(win) AS w1
    FROM participants WHERE patch='15.1' GROUP BY champion_name
),
s3 AS (
    SELECT champion_name, COUNT(*) AS n3, SUM(win) AS w3
    FROM participants WHERE patch='15.3' GROUP BY champion_name
),
champs AS (
    SELECT champion_name FROM s1
    UNION
    SELECT champion_name FROM s3
),
joined AS (
    SELECT
        c.champion_name,
        COALESCE(s1.n1, 0) AS n_15_1,
        COALESCE(s3.n3, 0) AS n_15_3,
        COALESCE(s1.w1, 0) AS w_15_1,
        COALESCE(s3.w3, 0) AS w_15_3,
        t.N1, t.N3
    FROM champs c
    CROSS JOIN totals t
    LEFT JOIN s1 USING (champion_name)
    LEFT JOIN s3 USING (champion_name)
),
stats AS (
    SELECT
        *,
        1.0 * n_15_1 / N1                                     AS pr1,
        1.0 * n_15_3 / N3                                     AS pr3,
        CASE WHEN n_15_1=0 THEN NULL ELSE 1.0*w_15_1/n_15_1 END AS wr1,
        CASE WHEN n_15_3=0 THEN NULL ELSE 1.0*w_15_3/n_15_3 END AS wr3
    FROM joined
)
SELECT
    champion_name,
    n_15_1, n_15_3,
    ROUND(pr1*100, 3)              AS pickrate_15_1_pct,
    ROUND(pr3*100, 3)              AS pickrate_15_3_pct,
    ROUND((pr3 - pr1)*100, 3)      AS pickrate_diff_pp,
    CASE WHEN wr1 IS NULL OR wr3 IS NULL THEN NULL
         ELSE ROUND((wr3 - wr1)*100, 2) END AS winrate_diff_pp
FROM stats;


-- [1] 떠오른 챔프 TOP 15 (코호트 = 메인). 픽률 증가 큰 순.
SELECT *
FROM v_drift_cohort
WHERE n_15_1 >= 20 AND n_15_3 >= 20
ORDER BY pickrate_diff_pp DESC
LIMIT 15;


-- [2] 저문 챔프 BOTTOM 15 (코호트). 픽률 감소 큰 순.
SELECT *
FROM v_drift_cohort
WHERE n_15_1 >= 20 AND n_15_3 >= 20
ORDER BY pickrate_diff_pp ASC
LIMIT 15;


-- [3] 승률 급등 TOP 10 (코호트). n>=30 양쪽 모두에서.
SELECT
    champion_name, n_15_1, n_15_3,
    winrate_15_1_pct, winrate_15_3_pct,
    winrate_diff_pp, wr_ci_low_pp, wr_ci_high_pp,
    pickrate_15_1_pct, pickrate_15_3_pct, pickrate_diff_pp
FROM v_drift_cohort
WHERE n_15_1 >= 30 AND n_15_3 >= 30
ORDER BY winrate_diff_pp DESC
LIMIT 10;


-- [4] 승률 급락 BOTTOM 10 (코호트).
SELECT
    champion_name, n_15_1, n_15_3,
    winrate_15_1_pct, winrate_15_3_pct,
    winrate_diff_pp, wr_ci_low_pp, wr_ci_high_pp,
    pickrate_15_1_pct, pickrate_15_3_pct, pickrate_diff_pp
FROM v_drift_cohort
WHERE n_15_1 >= 30 AND n_15_3 >= 30
ORDER BY winrate_diff_pp ASC
LIMIT 10;


-- [5] role별 다양성 지표 변화 (코호트). HHI 변화 = 메타 쏠림 변화.
WITH cp AS (
    SELECT patch, role, champion_name, COUNT(*) AS n
    FROM v_cohort
    GROUP BY patch, role, champion_name
),
ranked AS (
    SELECT
        patch, role, n,
        1.0 * n / SUM(n) OVER (PARTITION BY patch, role)        AS share,
        ROW_NUMBER() OVER (PARTITION BY patch, role ORDER BY n) AS rk,
        COUNT(*)     OVER (PARTITION BY patch, role)            AS k
    FROM cp
),
agg AS (
    SELECT
        patch, role,
        MAX(k)                                                       AS unique_champs,
        SUM(share * share)                                           AS hhi_raw,
        2.0 * SUM(rk * share) / MAX(k) - (MAX(k) + 1.0) / MAX(k)     AS gini_raw
    FROM ranked GROUP BY patch, role
)
SELECT
    role,
    MAX(CASE WHEN patch='15.1' THEN unique_champs END)            AS uniq_15_1,
    ROUND(MAX(CASE WHEN patch='15.1' THEN hhi_raw END), 5)        AS hhi_15_1,
    ROUND(1.0 / MAX(CASE WHEN patch='15.1' THEN hhi_raw END), 1)  AS eff_15_1,
    ROUND(MAX(CASE WHEN patch='15.1' THEN gini_raw END), 4)       AS gini_15_1,
    MAX(CASE WHEN patch='15.3' THEN unique_champs END)            AS uniq_15_3,
    ROUND(MAX(CASE WHEN patch='15.3' THEN hhi_raw END), 5)        AS hhi_15_3,
    ROUND(1.0 / MAX(CASE WHEN patch='15.3' THEN hhi_raw END), 1)  AS eff_15_3,
    ROUND(MAX(CASE WHEN patch='15.3' THEN gini_raw END), 4)       AS gini_15_3,
    ROUND(MAX(CASE WHEN patch='15.3' THEN hhi_raw END) -
          MAX(CASE WHEN patch='15.1' THEN hhi_raw END), 5)        AS hhi_diff,
    ROUND(MAX(CASE WHEN patch='15.3' THEN gini_raw END) -
          MAX(CASE WHEN patch='15.1' THEN gini_raw END), 4)       AS gini_diff
FROM agg
GROUP BY role
ORDER BY role;


-- [6] 떠오른 챔프 TOP 10 (naïve = 대조). "통제 안 하면 이렇게 보인다"
SELECT
    champion_name, n_15_1, n_15_3,
    pickrate_15_1_pct, pickrate_15_3_pct, pickrate_diff_pp,
    winrate_diff_pp
FROM v_drift_naive
WHERE n_15_1 >= 20 AND n_15_3 >= 20
ORDER BY pickrate_diff_pp DESC
LIMIT 10;


-- [7] 코호트 TOP 15 ∪ naïve TOP 15 — 어느 쪽에만 등장하는 챔프 = 교란의 흔적
WITH cohort_top AS (
    SELECT champion_name, pickrate_diff_pp,
           ROW_NUMBER() OVER (ORDER BY pickrate_diff_pp DESC) AS rk
    FROM v_drift_cohort
    WHERE n_15_1 >= 20 AND n_15_3 >= 20
),
naive_top AS (
    SELECT champion_name, pickrate_diff_pp,
           ROW_NUMBER() OVER (ORDER BY pickrate_diff_pp DESC) AS rk
    FROM v_drift_naive
    WHERE n_15_1 >= 20 AND n_15_3 >= 20
),
universe AS (
    SELECT champion_name FROM cohort_top WHERE rk <= 15
    UNION
    SELECT champion_name FROM naive_top  WHERE rk <= 15
)
SELECT
    u.champion_name,
    ct.rk                AS rank_cohort,
    nt.rk                AS rank_naive,
    ct.pickrate_diff_pp  AS pp_cohort,
    nt.pickrate_diff_pp  AS pp_naive,
    ROUND(COALESCE(nt.pickrate_diff_pp, 0) - COALESCE(ct.pickrate_diff_pp, 0), 3)
                         AS naive_minus_cohort_pp
FROM universe u
LEFT JOIN cohort_top ct USING (champion_name)
LEFT JOIN naive_top  nt USING (champion_name)
ORDER BY COALESCE(ct.rk, 999), COALESCE(nt.rk, 999);
