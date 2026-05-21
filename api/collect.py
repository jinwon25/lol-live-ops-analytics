"""PHASE 5 — Riot API 수집 파이프라인 (소량 실작동 증명).

목적:
- 캐글 정적 데이터에 의존하지 않고 Riot API 에서 직접 수집할 수 있음을 보임.
- PHASE 1 의 공통 스키마(matches / participants)로 적재 → 기존 SQL 그대로 동작.
- puuid 보존 → PHASE 3 의 "게임 단위 프로필" 한계를 "플레이어 누적 프로필"로
  확장하는 길을 연다.

설계:
1. 시드 소환사 1명 → 그의 최근 N경기 ID 수집.
2. 각 경기 상세 호출 → participants 10명 행으로 분해.
3. 두 번째 시드(participant 중 한 명의 puuid)로 같은 절차 반복하면 BFS 가능.
   본 스크립트는 시드 1명, 매치 limit 만 받음 (PoC).
4. PHASE 1 의 캐노니컬 스키마로 변환 후 SQLite 에 적재.
5. 적재 후 같은 검증 쿼리(00_validate.sql 일부)와 메타 쿼리(10_champ_stats.sql)
   를 돌려서 결과 출력 → 파이프라인이 분석까지 일관되게 흐르는 것을 증명.

실행:
    export RIOT_API_KEY=RGAPI-...
    python api/collect.py --seed "<소환사명>" --matches 20

환경:
- 키는 env RIOT_API_KEY (또는 api/.env 에 두고 python-dotenv 로 로드).
- 본 스크립트는 표준 라이브러리 + requests + pandas + sqlite3 만 사용.
"""
from __future__ import annotations
import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from riot_client import RiotClient


def _load_dotenv(path: Path) -> None:
    """python-dotenv 의존성 없이 간단한 KEY=VALUE 로더.
    이미 export 된 env 가 우선(setdefault) — 의도된 환경변수 덮어쓰기 방지.
    값에 둘러싼 큰/작은 따옴표는 벗긴다.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


# 모듈 import 시점에 api/.env 자동 로드 (있을 때만).
_load_dotenv(Path(__file__).resolve().parent / ".env")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "processed" / "lol_api.db"   # 캐글 DB(lol.db)와 분리
DB.parent.mkdir(parents=True, exist_ok=True)


ROLE_MAP = {
    "TOP": "TOP", "JUNGLE": "JUNGLE",
    "MIDDLE": "MID", "MID": "MID",
    "BOTTOM": "BOT", "BOT": "BOT",
    "SUPPORT": "SUPPORT", "UTILITY": "SUPPORT",
}


def patch_from_version(v: str) -> str | None:
    parts = str(v).split(".")
    return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else None


def participant_to_canonical(match: dict, p: dict) -> dict:
    info = match["info"]
    duration_sec = info["gameDuration"]
    duration_min = duration_sec / 60.0 if duration_sec else 1.0
    role = ROLE_MAP.get(p.get("teamPosition") or p.get("individualPosition") or "", None)
    if role is None:
        return {}
    kills, deaths, assists = p["kills"], p["deaths"], p["assists"]
    return {
        "patch": patch_from_version(info["gameVersion"]),
        "game_id": int(match["metadata"]["matchId"].split("_")[-1]),
        "participant_id": p["participantId"],
        "puuid": p["puuid"],
        "champion_name": p["championName"],
        "role": role,
        "win": int(p["win"]),
        "kills": kills, "deaths": deaths, "assists": assists,
        "gold_earned": p["goldEarned"],
        "dmg_to_champ": p["totalDamageDealtToChampions"],
        "dmg_taken":    p["totalDamageTaken"],
        "vision_score": p["visionScore"],
        "solo_tier": "UNKNOWN",   # 매치 V5 응답엔 solo tier 없음 — 별도 league API 필요
        "duration_sec": duration_sec,
        "kda": (kills + assists) / max(deaths, 1),
        "gpm": p["goldEarned"] / duration_min,
        "dpm_champ": p["totalDamageDealtToChampions"] / duration_min,
        "team_side": 100 if p["teamId"] == 100 else 200,
    }


SCHEMA = """
DROP TABLE IF EXISTS participants;
DROP TABLE IF EXISTS matches;
CREATE TABLE matches (
    patch         TEXT,
    game_id       INTEGER,
    duration_sec  INTEGER,
    PRIMARY KEY (patch, game_id)
);
CREATE TABLE participants (
    patch              TEXT NOT NULL,
    game_id            INTEGER NOT NULL,
    participant_id     INTEGER NOT NULL,
    puuid              TEXT,
    champion_name      TEXT NOT NULL,
    role               TEXT NOT NULL,
    win                INTEGER NOT NULL,
    kills              INTEGER NOT NULL,
    deaths             INTEGER NOT NULL,
    assists            INTEGER NOT NULL,
    gold_earned        INTEGER NOT NULL,
    dmg_to_champ       INTEGER NOT NULL,
    dmg_taken          INTEGER NOT NULL,
    vision_score       INTEGER NOT NULL,
    solo_tier          TEXT NOT NULL,
    kda                REAL,
    gpm                REAL,
    dpm_champ          REAL,
    kill_participation REAL,
    PRIMARY KEY (patch, game_id, participant_id)
);
CREATE INDEX ix_part_patch ON participants(patch);
CREATE INDEX ix_part_puuid ON participants(puuid);   -- ★ puuid 인덱스 (캐글 DB엔 없음)
"""


def collect(seed_riot_id: str, match_limit: int = 20, queue: int = 420) -> None:
    client = RiotClient(
        platform=os.environ.get("RIOT_REGION_PLATFORM", "EUN1"),
        region=os.environ.get("RIOT_REGION_ROUTING", "europe"),
    )

    if "#" not in seed_riot_id:
        raise SystemExit(
            "--seed 는 Riot ID 형식이어야 합니다 (예: 'Hide on bush#KR1'). "
            "2024년부터 summoner-by-name API 는 deprecated 되었습니다."
        )
    game_name, tag_line = seed_riot_id.rsplit("#", 1)

    print(f"[1] Riot ID 조회: {game_name}#{tag_line}")
    acc = client.account_by_riot_id(game_name, tag_line)
    puuid = acc["puuid"]
    print(f"    puuid = {puuid[:12]}…")

    print(f"[2] 최근 {match_limit} 경기 ID 수집 (queue={queue})")
    match_ids = client.matches_by_puuid(puuid, queue=queue, count=match_limit)
    print(f"    수집된 match_ids = {len(match_ids)}")

    print(f"[3] 매치 상세 호출 (rate-limited)…")
    rows_part: list[dict] = []
    rows_match: list[dict] = []
    t0 = time.monotonic()
    for i, mid in enumerate(match_ids, 1):
        m = client.match_detail(mid)
        info = m["info"]
        rows_match.append({
            "patch": patch_from_version(info["gameVersion"]),
            "game_id": int(mid.split("_")[-1]),
            "duration_sec": info["gameDuration"],
        })
        for p in info["participants"]:
            rec = participant_to_canonical(m, p)
            if rec:
                rows_part.append(rec)
        if i % 5 == 0 or i == len(match_ids):
            print(f"    [{i}/{len(match_ids)}] 누적 participants = {len(rows_part)}"
                  f"  elapsed = {time.monotonic()-t0:.1f}s")

    df_part = pd.DataFrame(rows_part)
    df_match = pd.DataFrame(rows_match).drop_duplicates(["patch", "game_id"])

    # KP 계산 (게임 + 팀 단위)
    if len(df_part):
        tk = df_part.groupby(["patch", "game_id", "team_side"])["kills"].transform("sum")
        df_part["kill_participation"] = (df_part["kills"] + df_part["assists"]) / tk.where(tk > 0)

    print(f"\n[4] SQLite 적재: {DB}")
    if DB.exists():
        DB.unlink()
    with sqlite3.connect(DB) as con:
        con.executescript(SCHEMA)
        df_match.to_sql("matches", con, if_exists="append", index=False)
        # participants 테이블 스키마에 없는 컬럼은 사전 제거 (duration_sec → matches, team_side → 계산 보조)
        non_part_cols = {"team_side", "duration_sec"}
        out_cols = [c for c in df_part.columns if c not in non_part_cols]
        df_part[out_cols].to_sql("participants", con, if_exists="append", index=False)
        print(f"    matches = {len(df_match)}  participants = {len(df_part)}")

        print("\n[5] 검증 — 캐글 DB 와 동일한 분석 쿼리가 작동하는지")
        con.executescript("""
            DROP VIEW IF EXISTS v_cohort;
            CREATE VIEW v_cohort AS SELECT * FROM participants;
        """)
        # 캐글 DB 의 10_champ_stats 쿼리와 동일 구조
        q = """
        WITH base AS (
            SELECT patch, champion_name, role,
                   COUNT(*) AS pick_count,
                   SUM(win) AS wins,
                   AVG(kda) AS avg_kda
            FROM v_cohort
            GROUP BY patch, champion_name, role
        ),
        totals AS (SELECT patch, SUM(pick_count) AS N FROM base GROUP BY patch)
        SELECT b.patch, b.champion_name, b.role, b.pick_count,
               ROUND(100.0 * b.pick_count / t.N, 2) AS pick_rate_pct,
               ROUND(100.0 * b.wins / b.pick_count, 1) AS win_rate_pct,
               ROUND(b.avg_kda, 2) AS avg_kda
        FROM base b JOIN totals t USING (patch)
        ORDER BY b.patch, b.pick_count DESC
        LIMIT 10
        """
        df_top = pd.read_sql_query(q, con)
        print(df_top.to_string(index=False))
        print(f"\n[done] api 수집 → 공통 스키마 적재 → 동일 분석 쿼리 동작 확인 완료.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Riot API 소량 수집 PoC")
    ap.add_argument("--seed", required=False,
                    default=os.environ.get("RIOT_SEED_RIOT_ID",
                                           os.environ.get("RIOT_SEED_SUMMONER", "")),
                    help="시드 Riot ID 'GameName#TagLine' (또는 env RIOT_SEED_RIOT_ID)")
    ap.add_argument("--matches", type=int, default=20, help="수집할 매치 수 (rate limit 고려, 권장 ≤ 30)")
    ap.add_argument("--queue", type=int, default=420, help="큐 ID (기본 420 = 솔로/듀오)")
    args = ap.parse_args()

    if not args.seed:
        raise SystemExit("--seed 'GameName#TagLine' 또는 env RIOT_SEED_RIOT_ID 필요")

    collect(args.seed, args.matches, args.queue)


if __name__ == "__main__":
    main()
