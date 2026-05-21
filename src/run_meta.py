"""PHASE 2 — 메타 SQL 실행기.

설계:
- 각 SQL 파일은 (setup section before `-- [1]`) + (numbered blocks)로 구성.
- setup은 executescript, numbered는 read_sql_query.
- 블록별 CSV는 outputs/ 로 export (Looker Studio 연결 후보).

출력:
- 콘솔: 표 미리보기 + 핵심 요약
- outputs/01_*.csv, outputs/02_*.csv
"""
from __future__ import annotations
from pathlib import Path
import re
import sqlite3
import sys
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "processed" / "lol.db"
SQL_DIR = ROOT / "sql"
OUT_DIR = ROOT / "outputs"
OUT_DIR.mkdir(exist_ok=True)


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
        sql = "\n".join(
            line for line in body.splitlines()
            if not line.strip().startswith("--")
        ).strip()
        if sql:
            blocks.append((n, label, sql))
    return setup, blocks


def run_sql_file(con: sqlite3.Connection,
                 path: Path,
                 csv_map: dict[str, str] | None = None,
                 preview_rows: int = 25) -> None:
    print(f"\n\n############ {path.name} ############")
    text = path.read_text(encoding="utf-8")
    setup, blocks = split_setup_and_blocks(text)
    if setup.strip():
        con.executescript(setup)

    for n, label, sql in blocks:
        print(f"\n=== [{n}] {label} ===")
        df = pd.read_sql_query(sql, con)
        if df.empty:
            print("(no rows)")
            continue
        if csv_map and n in csv_map:
            out = OUT_DIR / csv_map[n]
            # excel/한글이 깨지지 않도록 utf-8-sig
            df.to_csv(out, index=False, encoding="utf-8-sig")
            print(f"→ wrote outputs/{csv_map[n]}  ({len(df):,} rows)")
        if len(df) > preview_rows:
            print(df.head(preview_rows).to_string(index=False))
            print(f"... ({len(df):,}행 중 상위 {preview_rows}행 표시)")
        else:
            print(df.to_string(index=False))


def main() -> None:
    with sqlite3.connect(DB) as con:
        # setup: 공유 뷰
        run_sql_file(con, SQL_DIR / "05_views.sql")

        run_sql_file(con, SQL_DIR / "10_champ_stats.sql", csv_map={
            "1": "10_champ_stats_cohort.csv",
        })
        run_sql_file(con, SQL_DIR / "11_diversity.sql", csv_map={
            "1": "11_diversity_by_role_cohort.csv",
        })
        run_sql_file(con, SQL_DIR / "12_flagging.sql", csv_map={
            "1": "12_flagging_cohort.csv",
            "2": "12_flagging_summary.csv",
        })
        run_sql_file(con, SQL_DIR / "13_patch_drift.sql", csv_map={
            "1": "13_rising_champs_cohort.csv",
            "2": "13_falling_champs_cohort.csv",
            "3": "13_winrate_up_cohort.csv",
            "4": "13_winrate_down_cohort.csv",
            "5": "13_diversity_drift_by_role.csv",
            "6": "13_rising_champs_naive.csv",
            "7": "13_cohort_vs_naive_top.csv",
        })


if __name__ == "__main__":
    main()
