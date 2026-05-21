"""sql/00_validate.sql 의 각 블록을 실행해 라벨과 함께 출력."""
from pathlib import Path
import re
import sqlite3
import sys
import pandas as pd

# Windows 콘솔이 기본 cp949라 em-dash/한글에서 깨짐 → UTF-8 강제.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "processed" / "lol.db"
SQL_PATH = ROOT / "sql" / "00_validate.sql"


def split_blocks(text: str) -> list[tuple[str, str]]:
    """주석 헤더(`-- [N]`)로 SQL 블록을 분할."""
    blocks = []
    chunks = re.split(r"(?m)^-- \[(\d+)\]\s*(.*)$", text)
    # chunks: [pre, n1, label1, body1, n2, label2, body2, ...]
    for i in range(1, len(chunks), 3):
        n, label, body = chunks[i], chunks[i + 1], chunks[i + 2]
        sql = "\n".join(
            line for line in body.splitlines()
            if not line.strip().startswith("--")
        ).strip()
        if sql:
            blocks.append((f"[{n}] {label}".strip(), sql))
    return blocks


def main() -> None:
    text = SQL_PATH.read_text(encoding="utf-8")
    with sqlite3.connect(DB) as con:
        for label, sql in split_blocks(text):
            print(f"\n=== {label} ===")
            df = pd.read_sql_query(sql, con)
            if df.empty:
                print("(no rows)")
            else:
                print(df.to_string(index=False))


if __name__ == "__main__":
    main()
