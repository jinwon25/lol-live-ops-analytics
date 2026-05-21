"""PHASE 4 — 대시보드용 후처리: outputs CSV 들에 champion_name_kr 컬럼 추가.

대상: champion_name 컬럼이 있는 모든 outputs CSV.
한글 매핑: src/champion_kr.py
"""
from __future__ import annotations
from pathlib import Path
import sys
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from champion_kr import to_kr

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"


def add_kr(path: Path) -> bool:
    df = pd.read_csv(path, encoding="utf-8-sig")
    if "champion_name" not in df.columns:
        return False
    if "champion_name_kr" in df.columns:
        # 이미 들어있으면 갱신만
        df["champion_name_kr"] = df["champion_name"].map(to_kr)
    else:
        idx = df.columns.get_loc("champion_name") + 1
        df.insert(idx, "champion_name_kr", df["champion_name"].map(to_kr))
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return True


def main() -> None:
    n_done = 0
    for p in sorted(OUT.glob("*.csv")):
        if add_kr(p):
            n_done += 1
            print(f"  ✓ {p.name}")
    print(f"\n[done] {n_done} CSV updated with champion_name_kr")


if __name__ == "__main__":
    main()
