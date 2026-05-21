"""PHASE 4 — Looker Studio 용 깨끗한 집계 CSV 4종 생성.

출력 (outputs/):
- champion_meta.csv   : patch × champion × role 단위 pick_rate/win_rate/flag/riot_action
- diversity.csv       : patch × role 단위 HHI / Gini / 유효 챔프 수
- patch_drift.csv     : 챔프별 15.1 → 15.3 변화량 + 95% CI + 라이엇 실제 조정
- player_segments.csv : 게임 단위 클러스터 라벨 (이미 존재, 컬럼 정리만)
- segment_summary.csv : 클러스터별 요약 (centroid + 비율 + 승률)

설계 원칙:
- 컬럼명은 사람이 읽기 쉽게 (snake_case + 단위 명시).
- patch 는 필터 차원으로 컬럼 유지 (drop 안 함).
- 한글 챔프명을 첫 컬럼에, 영문 ID(join key)를 두 번째.
- 라이엇 실제 패치 조정 컬럼(`riot_15_3_action`)을 챔프 단위 표에 부착해
  Looker P1 NERF/BUFF 테이블에서 "분석 신호 → 실제 패치"를 한 줄에서 보게.
"""
from __future__ import annotations
from pathlib import Path
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from champion_kr import to_kr

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "processed" / "lol.db"
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)


# ── 라이엇 15.3 패치 노트 챔프 조정 (위키 V15.3 출처) ─────────────────────
# 출처: https://wiki.leagueoflegends.com/en-us/V15.3
RIOT_15_3_ACTIONS: dict[str, str] = {
    # NERF
    "Cassiopeia": "NERF", "Galio": "NERF", "Jayce": "NERF",
    "MissFortune": "NERF", "Rell": "NERF", "Skarner": "NERF",
    "Teemo": "NERF", "Viego": "NERF", "MonkeyKing": "NERF",
    # BUFF
    "Evelynn": "BUFF", "Jax": "BUFF", "Kayn": "BUFF", "Nasus": "BUFF",
    "Quinn": "BUFF", "Rakan": "BUFF", "Samira": "BUFF",
    "Swain": "BUFF", "Thresh": "BUFF", "Varus": "BUFF",
    # ADJUSTMENT (system / non-numeric)
    "Ambessa": "ADJUSTMENT", "Elise": "ADJUSTMENT", "Mel": "ADJUSTMENT",
    "Neeko": "ADJUSTMENT", "Viktor": "ADJUSTMENT",
}


def ensure_views(con: sqlite3.Connection) -> None:
    """v_cohort, v_drift_cohort 가 항상 살아있게."""
    for sql_path in ["05_views.sql", "13_patch_drift.sql"]:
        text = (ROOT / "sql" / sql_path).read_text(encoding="utf-8")
        # 13_patch_drift 는 numbered SELECT 블록도 있음 → 첫 [N] 전까지의 setup만 실행
        import re
        parts = re.split(r"(?m)^-- \[(\d+)\]\s*(.*)$", text)
        con.executescript(parts[0])


# ── 1. champion_meta.csv ────────────────────────────────────────────────
def build_champion_meta(con: sqlite3.Connection) -> pd.DataFrame:
    q = """
    WITH base AS (
        SELECT patch, champion_name, role,
               COUNT(*) AS pick_count,
               SUM(win) AS wins
        FROM v_cohort
        GROUP BY patch, champion_name, role
    ),
    totals AS (
        SELECT patch, SUM(pick_count) AS N FROM base GROUP BY patch
    ),
    scored AS (
        SELECT b.patch, b.champion_name, b.role, b.pick_count,
               ROUND(100.0 * b.pick_count / t.N, 3) AS pick_rate_pct,
               1.0 * b.wins / b.pick_count          AS win_rate,
               NTILE(4) OVER (PARTITION BY b.patch, b.role ORDER BY b.pick_count) AS pop_quartile,
               ( ( 1.0*b.wins/b.pick_count + 1.96*1.96/(2.0*b.pick_count)
                 - 1.96 * SQRT( (1.0*b.wins/b.pick_count)*(1-1.0*b.wins/b.pick_count)/b.pick_count
                              + 1.96*1.96/(4.0*b.pick_count*b.pick_count) ) )
                 / (1 + 1.96*1.96/b.pick_count)
               ) AS wilson_low
        FROM base b JOIN totals t USING (patch)
    )
    SELECT
        patch, champion_name, role,
        pick_count,
        pick_rate_pct,
        ROUND(win_rate*100, 2)   AS win_rate_pct,
        ROUND(wilson_low*100, 2) AS wilson_low_pct,
        CASE
            WHEN pick_count >= 30 AND win_rate >= 0.52 AND pop_quartile  = 4 THEN 'NERF'
            WHEN pick_count >= 15 AND wilson_low >= 0.50 AND pop_quartile != 4 THEN 'BUFF_HIDDEN_STRONG'
            WHEN pick_count <  15 THEN 'LOW_N'
            ELSE ''
        END AS flag
    FROM scored
    """
    df = pd.read_sql_query(q, con)
    df.insert(1, "champion",     df["champion_name"].map(to_kr))
    df.insert(2, "champion_en",  df.pop("champion_name"))
    df["riot_15_3_action"] = df["champion_en"].map(RIOT_15_3_ACTIONS).fillna("")
    df = df.sort_values(["patch", "role", "pick_count"], ascending=[True, True, False])
    df.to_csv(OUT / "champion_meta.csv", index=False, encoding="utf-8-sig")
    print(f"  ✓ champion_meta.csv          {len(df):,} rows")
    return df


# ── 2. diversity.csv ────────────────────────────────────────────────────
def build_diversity(con: sqlite3.Connection) -> pd.DataFrame:
    q = """
    WITH cp AS (
        SELECT patch, role, champion_name, COUNT(*) AS n
        FROM v_cohort
        GROUP BY patch, role, champion_name
    ),
    ranked AS (
        SELECT patch, role, n,
               1.0 * n / SUM(n) OVER (PARTITION BY patch, role)        AS share,
               ROW_NUMBER() OVER (PARTITION BY patch, role ORDER BY n) AS rk,
               COUNT(*)     OVER (PARTITION BY patch, role)            AS k
        FROM cp
    )
    SELECT patch, role,
           MAX(k)                                                       AS unique_champs,
           ROUND(SUM(share * share), 5)                                 AS hhi,
           ROUND(1.0 / SUM(share * share), 1)                           AS effective_champs,
           ROUND(2.0 * SUM(rk * share) / MAX(k)
                 - (MAX(k) + 1.0) / MAX(k), 4)                          AS gini
    FROM ranked
    GROUP BY patch, role
    ORDER BY patch, role
    """
    df = pd.read_sql_query(q, con)
    df.to_csv(OUT / "diversity.csv", index=False, encoding="utf-8-sig")
    print(f"  ✓ diversity.csv              {len(df):,} rows")
    return df


# ── 3. patch_drift.csv ──────────────────────────────────────────────────
def build_patch_drift(con: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM v_drift_cohort", con)
    df.insert(0, "champion",    df["champion_name"].map(to_kr))
    df.insert(1, "champion_en", df.pop("champion_name"))
    df["riot_15_3_action"] = df["champion_en"].map(RIOT_15_3_ACTIONS).fillna("")
    # 표본 최소 컷 (양 패치 모두 n>=20) 안내 컬럼
    df["enough_sample"] = (df["n_15_1"] >= 20) & (df["n_15_3"] >= 20)
    df = df.sort_values("pickrate_diff_pp", ascending=False)
    df.to_csv(OUT / "patch_drift.csv", index=False, encoding="utf-8-sig")
    print(f"  ✓ patch_drift.csv            {len(df):,} rows")
    return df


# ── 4. player_segments.csv (이미 존재, 컬럼 정렬·이름 깔끔하게) ──────────
def clean_player_segments() -> pd.DataFrame:
    df = pd.read_csv(OUT / "player_segments.csv", encoding="utf-8-sig")
    rename = {"champion_name_kr": "champion", "champion_name": "champion_en"}
    df = df.rename(columns=rename)
    desired = [
        "patch", "game_id", "participant_id",
        "champion", "champion_en", "role", "win",
        "cluster", "persona",
        "gpm", "dpm_champ", "vision_score", "kill_participation",
        "kda", "deaths",
    ]
    cols = [c for c in desired if c in df.columns]
    df = df[cols]
    df.to_csv(OUT / "player_segments.csv", index=False, encoding="utf-8-sig")
    print(f"  ✓ player_segments.csv        {len(df):,} rows  (cleaned)")
    return df


# ── 5. segment_summary.csv ──────────────────────────────────────────────
def build_segment_summary() -> pd.DataFrame:
    cent = pd.read_csv(OUT / "segment_centroids.csv", encoding="utf-8-sig")
    seg = pd.read_csv(OUT / "player_segments.csv", encoding="utf-8-sig")
    win_rate = seg.groupby("cluster")["win"].mean().mul(100).round(2)
    win_rate.name = "win_rate_pct"

    df = cent.set_index("cluster").join(win_rate)
    # 컬럼 깔끔하게 정렬
    keep = ["persona", "n", "share_pct", "win_rate_pct",
            "mean_gpm", "mean_dpm_champ", "mean_vision_score",
            "mean_kill_participation", "mean_kda", "mean_deaths",
            "z_gpm_centroid", "z_dpm_champ_centroid",
            "z_vision_score_centroid", "z_kill_participation_centroid"]
    df = df[[c for c in keep if c in df.columns]].reset_index()
    df = df.rename(columns={
        "cluster": "cluster_id",
        "n": "n_games",
    })
    df.to_csv(OUT / "segment_summary.csv", index=False, encoding="utf-8-sig")
    print(f"  ✓ segment_summary.csv        {len(df):,} rows")
    return df


def main() -> None:
    print(f"[build] outputs/ 깨끗한 4종 CSV 생성\n  db = {DB}")
    with sqlite3.connect(DB) as con:
        ensure_views(con)
        build_champion_meta(con)
        build_diversity(con)
        build_patch_drift(con)
    clean_player_segments()
    build_segment_summary()
    print("\n[done] Looker Studio 연결 준비 완료.")


if __name__ == "__main__":
    main()
