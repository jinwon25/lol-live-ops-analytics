"""표본 비교가능성 점검 — 패치 15.1 vs 15.3 그룹의 표본 크기·구성을 한눈에.

PHASE 2로 넘어가기 전 게이트:
- 두 그룹 표본 크기가 비교 가능한 수준인가?
- 15.1 그룹의 solo_tier UNKNOWN 비율은?
- 역할/티어 분포의 비대칭 정도는?
"""
from __future__ import annotations
from pathlib import Path
import sqlite3
import sys
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "processed" / "lol.db"


def main() -> None:
    con = sqlite3.connect(DB)

    # ── 1) 최상단 요약 ────────────────────────────────────────────────
    head = pd.read_sql_query("""
        SELECT
            p.patch,
            COUNT(DISTINCT p.game_id)                         AS games,
            COUNT(*)                                          AS rows,
            COUNT(DISTINCT p.champion_name)                   AS unique_champs,
            ROUND(AVG(m.duration_sec) / 60.0, 2)              AS avg_min,
            ROUND(100.0 * SUM(CASE WHEN p.solo_tier = 'UNKNOWN'
                                   THEN 1 ELSE 0 END) /
                  COUNT(*), 2)                                AS unknown_tier_pct
        FROM participants p
        JOIN matches m USING (patch, game_id)
        GROUP BY p.patch
        ORDER BY p.patch
    """, con)
    print("=== [표본 요약] 패치별 게임/행/챔피언/평균길이/UNKNOWN 티어 비율 ===")
    print(head.to_string(index=False))

    # 표본 크기 비율(15.1 / 15.3) — 비교가능성 신호
    g_151 = int(head.loc[head["patch"] == "15.1", "games"].iloc[0])
    g_153 = int(head.loc[head["patch"] == "15.3", "games"].iloc[0])
    ratio = g_151 / g_153
    print(f"\n>>> 표본 크기 비율: 15.1 / 15.3 = {g_151:,} / {g_153:,} = {ratio:.2%}")

    # ── 2) 역할 분포 (피벗) ──────────────────────────────────────────
    role = pd.read_sql_query("""
        SELECT patch, role, COUNT(*) AS n,
               ROUND(100.0 * COUNT(*) /
                     SUM(COUNT(*)) OVER (PARTITION BY patch), 2) AS pct
        FROM participants
        GROUP BY patch, role
        ORDER BY patch, role
    """, con)
    role_pivot = role.pivot(index="role", columns="patch", values="n").fillna(0).astype(int)
    role_pivot.loc["TOTAL"] = role_pivot.sum()
    print("\n=== [역할 분포] 패치 × role 행 수 ===")
    print(role_pivot.to_string())

    # ── 3) solo_tier 분포 (피벗, %) ──────────────────────────────────
    tier_pct = pd.read_sql_query("""
        SELECT patch, solo_tier,
               ROUND(100.0 * COUNT(*) /
                     SUM(COUNT(*)) OVER (PARTITION BY patch), 2) AS pct
        FROM participants
        GROUP BY patch, solo_tier
        ORDER BY patch
    """, con)
    tier_pivot = tier_pct.pivot(index="solo_tier", columns="patch", values="pct").fillna(0.0)
    # 의미 있는 순서로 정렬
    order = ["CHALLENGER", "GRANDMASTER", "MASTER", "DIAMOND", "EMERALD",
             "PLATINUM", "GOLD", "SILVER", "BRONZE", "IRON", "UNKNOWN"]
    tier_pivot = tier_pivot.reindex([t for t in order if t in tier_pivot.index])
    print("\n=== [티어 분포] 패치 × solo_tier (%) ===")
    print(tier_pivot.to_string())

    # ── 4) 공통 코호트(EMERALD~DIAMOND) 표본 크기 — PHASE 2 컨트롤 뷰 후보 ──
    cohort = pd.read_sql_query("""
        SELECT patch,
               COUNT(DISTINCT game_id) AS games_in_cohort,
               COUNT(*)                 AS rows_in_cohort
        FROM participants
        WHERE solo_tier IN ('EMERALD', 'DIAMOND', 'PLATINUM')
        GROUP BY patch
        ORDER BY patch
    """, con)
    print("\n=== [공통 티어 코호트] PLATINUM/EMERALD/DIAMOND 한정 표본 ===")
    print(cohort.to_string(index=False))

    # ── 5) PHASE 2 픽률 신뢰성 가이드: 최소 표본 권고 (Wilson 5% mid 기준) ─
    #   픽률 p 의 95% CI half-width 가 ±2%p 이내가 되려면 n ≥ ~1000 필요
    #   각 패치 풀의 1% 챔프 = 행수 0.01 × N 이므로 N이 너무 작으면 픽률 노이즈 큼.
    print("\n=== [픽률 노이즈 가이드] ===")
    for _, r in head.iterrows():
        n = int(r["rows"])
        # 픽률 1% 챔프의 절대 표본 수
        n_at_1pct = n * 0.01
        print(f"  patch {r['patch']}: 전체 행 {n:,} → 픽률 1% 챔프 ≈ {n_at_1pct:,.0f} 행")
    print("  (전제: 픽률 ≥ 0.5% 챔프만 메인 비교에 사용, 그 이하는 신뢰구간 플래그)")

    con.close()


if __name__ == "__main__":
    main()
