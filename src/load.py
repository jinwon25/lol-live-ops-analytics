"""PHASE 1 — 두 원본을 공통 스키마로 하모나이즈하여 SQLite에 정규화 적재.

설계는 CLAUDE.md와 docs/_inspect_*.txt 참조.

산출:
    data/processed/lol.db  (테이블: matches, participants)
실행:
    python src/load.py
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
P153_PATH = ROOT / "data" / "raw" / "2025.csv"
P151_PATH = ROOT / "data" / "raw" / "2024.xlsx"
DB_PATH = ROOT / "data" / "processed" / "lol.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# MIDDLE→MID, BOTTOM→BOT, UTILITY→SUPPORT 등 캐노니컬 5종으로 통일.
ROLE_MAP = {
    "TOP": "TOP",
    "JUNGLE": "JUNGLE",
    "MIDDLE": "MID",
    "MID": "MID",
    "BOTTOM": "BOT",
    "BOT": "BOT",
    "SUPPORT": "SUPPORT",
    "UTILITY": "SUPPORT",
}

COMMON_COLS = [
    "patch", "game_id", "participant_id", "champion_name", "role", "win",
    "kills", "deaths", "assists", "gold_earned",
    "dmg_to_champ", "dmg_taken", "vision_score", "solo_tier",
    "duration_sec", "kda", "gpm", "dpm_champ", "kill_participation",
    "team_side",
]


def patch_from_version(v: object) -> str | None:
    """'15.3.656.4086' -> '15.3' / '14.24.644.2327' -> '14.24' / 결측 -> None"""
    if pd.isna(v):
        return None
    parts = str(v).split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return None


def load_p153() -> pd.DataFrame:
    """2025.csv (패치 15.3 위주, 솔랭만)"""
    df = pd.read_csv(P153_PATH, usecols=[
        "game_id", "duration", "game_version", "participant_id",
        "champion_name", "position", "win",
        "kills", "deaths", "assists",
        "gold_earned", "damage_to_champ", "damage_taken",
        "vision_score", "solo_tier",
    ])
    n0 = len(df)
    df["patch"] = df["game_version"].map(patch_from_version)
    df = df[df["patch"] == "15.3"].copy()
    df["role"] = df["position"].map(ROLE_MAP)
    df = df[df["role"].notna()].copy()                  # MIDDLE 등은 위에서 매핑됨, 그 외(Invalid 등) 제외
    df["win"] = df["win"].astype(int)
    df = df.rename(columns={
        "duration": "duration_sec",
        "damage_to_champ": "dmg_to_champ",
        "damage_taken": "dmg_taken",
    })
    df["solo_tier"] = df["solo_tier"].fillna("UNKNOWN")
    # P153은 명시적 팀 구분 컬럼이 없음 → 같은 게임에서 win값이 같은 5명이 한 팀.
    df["team_side"] = df["win"]
    print(f"[P153] {n0:,} → {len(df):,} (after patch=15.3 + role normalize)")
    return df


def load_p151() -> pd.DataFrame:
    """2024.xlsx / sheet=league_data.csv (패치 15.1 위주, 큐 혼합)"""
    df = pd.read_excel(P151_PATH, sheet_name="league_data.csv", usecols=[
        "game_id", "game_duration", "game_version", "queue_id", "participant_id",
        "champion_name", "team_position", "win", "team_id",
        "kills", "deaths", "assists",
        "gold_earned", "total_damage_dealt_to_champions", "total_damage_taken",
        "vision_score", "solo_tier",
    ])
    n0 = len(df)
    df = df[df["queue_id"] == 420].copy()               # 솔로/듀오만
    n_q = len(df)
    df["patch"] = df["game_version"].map(patch_from_version)
    df = df[df["patch"] == "15.1"].copy()
    n_p = len(df)
    df["role"] = df["team_position"].map(ROLE_MAP)
    df = df[df["role"].notna()].copy()
    df["win"] = df["win"].astype(int)
    df = df.rename(columns={
        "game_duration": "duration_sec",
        "total_damage_dealt_to_champions": "dmg_to_champ",
        "total_damage_taken": "dmg_taken",
    })
    df["solo_tier"] = df["solo_tier"].fillna("UNKNOWN")
    df["team_side"] = df["team_id"]                     # 100/200
    print(f"[P151] {n0:,} → queue420 {n_q:,} → patch15.1 {n_p:,} → role-ok {len(df):,}")
    return df


def derive_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """KDA / GPM / DPM / KP — 양쪽 동일 공식으로 재계산"""
    df["kda"] = (df["kills"] + df["assists"]) / df["deaths"].clip(lower=1)
    minutes = df["duration_sec"] / 60.0
    df["gpm"] = df["gold_earned"] / minutes
    df["dpm_champ"] = df["dmg_to_champ"] / minutes
    team_kills = df.groupby(["patch", "game_id", "team_side"])["kills"].transform("sum")
    df["kill_participation"] = (df["kills"] + df["assists"]) / team_kills.where(team_kills > 0)
    return df


SCHEMA = """
DROP TABLE IF EXISTS participants;
DROP TABLE IF EXISTS matches;

CREATE TABLE matches (
    patch         TEXT    NOT NULL,
    game_id       INTEGER NOT NULL,
    duration_sec  INTEGER NOT NULL,
    PRIMARY KEY (patch, game_id)
);

CREATE TABLE participants (
    patch              TEXT    NOT NULL,
    game_id            INTEGER NOT NULL,
    participant_id     INTEGER NOT NULL,
    champion_name      TEXT    NOT NULL,
    role               TEXT    NOT NULL,
    win                INTEGER NOT NULL CHECK (win IN (0, 1)),
    kills              INTEGER NOT NULL,
    deaths             INTEGER NOT NULL,
    assists            INTEGER NOT NULL,
    gold_earned        INTEGER NOT NULL,
    dmg_to_champ       INTEGER NOT NULL,
    dmg_taken          INTEGER NOT NULL,
    vision_score       INTEGER NOT NULL,
    solo_tier          TEXT    NOT NULL,
    kda                REAL,
    gpm                REAL,
    dpm_champ          REAL,
    kill_participation REAL,
    PRIMARY KEY (patch, game_id, participant_id),
    FOREIGN KEY (patch, game_id) REFERENCES matches(patch, game_id)
);

CREATE INDEX ix_part_patch          ON participants(patch);
CREATE INDEX ix_part_patch_champion ON participants(patch, champion_name);
CREATE INDEX ix_part_patch_role     ON participants(patch, role);
CREATE INDEX ix_part_tier           ON participants(solo_tier);
"""


def main() -> None:
    p153 = derive_metrics(load_p153())
    p151 = derive_metrics(load_p151())
    full = pd.concat([p153[COMMON_COLS], p151[COMMON_COLS]], ignore_index=True)

    matches = (
        full[["patch", "game_id", "duration_sec"]]
        .drop_duplicates(["patch", "game_id"])
        .reset_index(drop=True)
    )
    participants_cols = [c for c in COMMON_COLS if c not in ("duration_sec", "team_side")]
    participants = full[participants_cols].copy()

    if DB_PATH.exists():
        DB_PATH.unlink()
    with sqlite3.connect(DB_PATH) as con:
        con.executescript(SCHEMA)
        matches.to_sql("matches", con, if_exists="append", index=False)
        participants.to_sql("participants", con, if_exists="append", index=False)
        con.commit()

        print()
        for label, sql in [
            ("matches by patch     ", "SELECT patch, COUNT(*) AS n FROM matches GROUP BY patch ORDER BY patch"),
            ("participants by patch", "SELECT patch, COUNT(*) AS n FROM participants GROUP BY patch ORDER BY patch"),
        ]:
            print(label, "→", list(con.execute(sql)))

    print(f"\n[done] wrote {DB_PATH}  size={DB_PATH.stat().st_size/1e6:.1f} MB")


if __name__ == "__main__":
    main()
