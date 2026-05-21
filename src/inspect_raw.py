"""두 원본 파일의 스키마/표본을 검사해서 하모나이즈 매핑을 확정한다.

산출:
    docs/_inspect_p153.txt
    docs/_inspect_p151.txt
콘솔에도 핵심 요약만 출력.
"""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
P153_PATH = ROOT / "data" / "raw" / "2025.csv"           # 패치 15.3 위주, 솔랭만
P151_PATH = ROOT / "data" / "raw" / "2024.xlsx"          # 패치 15.1 위주, 큐 혼합
OUT_DIR = ROOT / "docs"
OUT_DIR.mkdir(exist_ok=True)


def report(name: str, df: pd.DataFrame) -> str:
    lines = []
    lines.append(f"=== {name} ===")
    lines.append(f"shape: {df.shape}")
    lines.append(f"columns ({len(df.columns)}):")
    for c in df.columns:
        lines.append(f"  - {c}  ({df[c].dtype})")
    lines.append("")
    lines.append("head(2):")
    lines.append(df.head(2).to_string())
    lines.append("")
    # 패치/큐/포지션 핵심 컬럼 값 분포
    for candidate in ["game_version", "queue_id", "position", "team_position",
                      "team_id", "win", "solo_tier"]:
        if candidate in df.columns:
            vc = df[candidate].astype(str).value_counts(dropna=False).head(10)
            lines.append(f"value_counts[{candidate}] (top10):\n{vc.to_string()}\n")
    return "\n".join(lines)


def main() -> None:
    # ---- P153 (csv) ----
    p153 = pd.read_csv(P153_PATH, nrows=5000)        # 헤더+표본만
    p153_full_cols = pd.read_csv(P153_PATH, nrows=0).columns.tolist()
    p153_rep = report("P153 (2025.csv, 처음 5000행 표본)", p153)
    p153_rep += f"\n\nFULL_COLUMNS({len(p153_full_cols)}): {p153_full_cols}"
    (OUT_DIR / "_inspect_p153.txt").write_text(p153_rep, encoding="utf-8")

    # ---- P151 (xlsx) ----
    xls = pd.ExcelFile(P151_PATH)
    print("[P151 sheets]", xls.sheet_names)
    sheet = "league_data.csv" if "league_data.csv" in xls.sheet_names else xls.sheet_names[0]
    p151 = pd.read_excel(P151_PATH, sheet_name=sheet, nrows=5000)
    p151_rep = report(f"P151 ({P151_PATH.name} / sheet={sheet}, 처음 5000행 표본)", p151)
    (OUT_DIR / "_inspect_p151.txt").write_text(p151_rep, encoding="utf-8")

    # ---- 콘솔 요약 ----
    print("\n--- P153 columns ---")
    print(p153.columns.tolist())
    print("\n--- P151 columns ---")
    print(p151.columns.tolist())
    print("\n[wrote]", OUT_DIR / "_inspect_p153.txt")
    print("[wrote]", OUT_DIR / "_inspect_p151.txt")


if __name__ == "__main__":
    main()
