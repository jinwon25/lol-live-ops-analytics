-- ============================================================================
-- PHASE 2 — 공유 뷰
-- v_cohort : 메인 분석에 쓰는 공통 티어 코호트(PLATINUM+EMERALD+DIAMOND).
--   * 15.1 → 22.9% / 15.3 → 7.0% 였던 MASTER+ 의 표본 비대칭, 그리고
--     15.1 → 12.0% / 15.3 → 35.6% 였던 EMERALD 의 분포 차이를 통제.
--   * 두 패치 모두 이 코호트에 ~9.5k / ~46k 행이 남아 챔프 비교에 충분.
-- ============================================================================

DROP VIEW IF EXISTS v_cohort;
CREATE VIEW v_cohort AS
SELECT *
FROM participants
WHERE solo_tier IN ('PLATINUM', 'EMERALD', 'DIAMOND');
