"""PHASE 2 — 메타 SQL 실행기 및 다중 검정 보정(Benjamini-Hochberg FDR) 후처리기.

설계:
- 각 SQL 파일은 (setup section before `-- [1]`) + (numbered blocks)로 구성.
- setup은 executescript, numbered는 read_sql_query.
- 패치 드리프트(`13_patch_drift.sql`) 및 플래깅(`12_flagging.sql`)의 z-통계량 컬럼이 존재하면
  양측 정규근사 p-value와 Benjamini-Hochberg FDR 보정 q-value(`*_q_value`, `*_fdr_significant`)를
  계산하여 1종 오류(위양성)를 통제한다.
- 블록별 CSV는 outputs/ 로 export (Looker Studio 연결 후보).
"""

from __future__ import annotations

import io
import math
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "processed" / "lol.db"
SQL_DIR = ROOT / "sql"
OUT_DIR = ROOT / "outputs"
OUT_DIR.mkdir(exist_ok=True)

DEFAULT_FDR_ALPHA = 0.05
SQRT_TWO = math.sqrt(2.0)


def two_sided_normal_p_values(z_scores: pd.Series | np.ndarray) -> np.ndarray:
    """Compute two-sided normal approximation p-values from z-statistics without SciPy."""
    z_array = np.asarray(z_scores, dtype=float)
    p_values = np.full(z_array.shape, np.nan, dtype=float)
    valid_mask = np.isfinite(z_array)
    if np.any(valid_mask):
        p_values[valid_mask] = [
            min(1.0, max(0.0, math.erfc(abs(float(z_val)) / SQRT_TWO))) for z_val in z_array[valid_mask]
        ]
    return p_values


def benjamini_hochberg_fdr(
    p_values: pd.Series | np.ndarray,
    alpha: float = DEFAULT_FDR_ALPHA,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply Benjamini-Hochberg FDR correction to control Type I error across multiple comparisons."""
    p_array = np.asarray(p_values, dtype=float)
    q_values = np.full(p_array.shape, np.nan, dtype=float)
    significant = np.zeros(p_array.shape, dtype=bool)

    valid_indices = np.flatnonzero(np.isfinite(p_array))
    num_tests = len(valid_indices)
    if num_tests == 0:
        return q_values, significant

    valid_p = np.clip(p_array[valid_indices], 0.0, 1.0)
    sort_order = np.argsort(valid_p, kind="mergesort")
    sorted_p = valid_p[sort_order]
    ranks = np.arange(1, num_tests + 1, dtype=float)

    raw_q = sorted_p * (num_tests / ranks)
    monotonic_q = np.minimum.accumulate(raw_q[::-1])[::-1]
    monotonic_q = np.clip(monotonic_q, 0.0, 1.0)

    unsorted_q = np.empty_like(monotonic_q)
    unsorted_q[sort_order] = monotonic_q
    q_values[valid_indices] = np.round(unsorted_q, 6)
    significant[valid_indices] = unsorted_q <= alpha
    return q_values, significant


def apply_fdr_postprocessing(
    df: pd.DataFrame,
    alpha: float = DEFAULT_FDR_ALPHA,
) -> pd.DataFrame:
    """Attach Benjamini-Hochberg p-values, q-values, and significance flags to SQL query results."""
    if df.empty:
        return df
    result = df.copy()
    z_col_specs = [
        ("pr_z_stat", "pr_p_value", "pr_q_value", "pr_fdr_significant"),
        ("wr_z_stat", "wr_p_value", "wr_q_value", "wr_fdr_significant"),
        ("wr_z_vs_50", "wr_p_value", "wr_q_value", "wr_fdr_significant"),
    ]
    for z_col, p_col, q_col, sig_col in z_col_specs:
        if z_col in result.columns:
            p_vals = two_sided_normal_p_values(result[z_col])
            q_vals, sig_flags = benjamini_hochberg_fdr(p_vals, alpha=alpha)
            result[p_col] = np.round(p_vals, 6)
            result[q_col] = q_vals
            result[sig_col] = sig_flags
    return result


def split_setup_and_blocks(text: str) -> tuple[str, list[tuple[str, str, str]]]:
    """SQL 파일을 (setup, [(n, label, body), ...])로 쪼갠다.
    setup = 첫 `-- [N]` 헤더 이전 모든 내용 (CREATE VIEW 포함).
    """
    parts = re.split(r"(?m)^-- \[(\d+)\]\s*(.*)$", text)
    setup = parts[0]
    blocks: list[tuple[str, str, str]] = []
    for i in range(1, len(parts), 3):
        n = parts[i]
        label = parts[i + 1].strip()
        body = parts[i + 2]
        sql = "\n".join(line for line in body.splitlines() if not line.strip().startswith("--")).strip()
        if sql:
            blocks.append((n, label, sql))
    return setup, blocks


def run_sql_file(
    con: sqlite3.Connection,
    path: Path,
    csv_map: dict[str, str] | None = None,
    preview_rows: int = 25,
    fdr_alpha: float = DEFAULT_FDR_ALPHA,
) -> dict[str, pd.DataFrame]:
    print(f"\n\n############ {path.name} ############")
    text = path.read_text(encoding="utf-8")
    setup, blocks = split_setup_and_blocks(text)
    if setup.strip():
        con.executescript(setup)

    results: dict[str, pd.DataFrame] = {}
    for n, label, sql in blocks:
        print(f"\n=== [{n}] {label} ===")
        raw_df = pd.read_sql_query(sql, con)
        if raw_df.empty:
            print("(no rows)")
            results[n] = raw_df
            continue
        df = apply_fdr_postprocessing(raw_df, alpha=fdr_alpha)
        results[n] = df
        if csv_map and n in csv_map:
            out = OUT_DIR / csv_map[n]
            df.to_csv(out, index=False, encoding="utf-8-sig")
            print(f"→ wrote outputs/{csv_map[n]}  ({len(df):,} rows)")
        if len(df) > preview_rows:
            print(df.head(preview_rows).to_string(index=False))
            print(f"... ({len(df):,}행 중 상위 {preview_rows}행 표시)")
        else:
            print(df.to_string(index=False))
    return results


def main() -> None:
    with closing(sqlite3.connect(DB)) as con:
        run_sql_file(con, SQL_DIR / "05_views.sql")
        run_sql_file(
            con,
            SQL_DIR / "10_champ_stats.sql",
            csv_map={
                "1": "10_champ_stats_cohort.csv",
            },
        )
        run_sql_file(
            con,
            SQL_DIR / "11_diversity.sql",
            csv_map={
                "1": "11_diversity_by_role_cohort.csv",
            },
        )
        run_sql_file(
            con,
            SQL_DIR / "12_flagging.sql",
            csv_map={
                "1": "12_flagging_cohort.csv",
                "2": "12_flagging_summary.csv",
            },
        )
        run_sql_file(
            con,
            SQL_DIR / "13_patch_drift.sql",
            csv_map={
                "1": "13_rising_champs_cohort.csv",
                "2": "13_falling_champs_cohort.csv",
                "3": "13_winrate_up_cohort.csv",
                "4": "13_winrate_down_cohort.csv",
                "5": "13_diversity_drift_by_role.csv",
                "6": "13_rising_champs_naive.csv",
                "7": "13_cohort_vs_naive_top.csv",
            },
        )


if __name__ == "__main__":  # pragma: no cover
    main()
