"""Riot Games API 얇은 래퍼.

핵심:
- API 키는 env(`RIOT_API_KEY`)에서만. 코드/커밋에 절대 X.
- 개발자 키 rate limit: **20 req/sec, 100 req/2min**.
  토큰 버킷 두 단으로 추적 + 429 응답 시 Retry-After 헤더로 백오프.
- 매치/플레이어 호출 분리. Platform routing(EUN1) vs Regional(europe) 자동 선택.
"""
from __future__ import annotations
import os
import sys
import time
from collections import deque
from dataclasses import dataclass

import requests

# Rate limit 상수 (개발자 키 기준)
PER_SEC_LIMIT = 20
PER_2MIN_LIMIT = 100
WINDOW_SHORT = 1.0
WINDOW_LONG = 120.0

# 매치 V5 는 regional routing, summoner/league 은 platform routing
PLATFORM_HOSTS = {
    "EUN1": "eun1.api.riotgames.com",
    "EUW1": "euw1.api.riotgames.com",
    "KR":   "kr.api.riotgames.com",
    "NA1":  "na1.api.riotgames.com",
}
REGIONAL_HOSTS = {
    "europe":   "europe.api.riotgames.com",
    "americas": "americas.api.riotgames.com",
    "asia":     "asia.api.riotgames.com",
}


@dataclass
class RateLimiter:
    """토큰 버킷 두 단 — 단기(1s) + 장기(120s)."""
    short_stamps: deque
    long_stamps: deque

    def wait(self) -> None:
        now = time.monotonic()
        # 만료 토큰 제거
        while self.short_stamps and now - self.short_stamps[0] > WINDOW_SHORT:
            self.short_stamps.popleft()
        while self.long_stamps and now - self.long_stamps[0] > WINDOW_LONG:
            self.long_stamps.popleft()

        # 단기 한도 초과면 가장 오래된 토큰이 만료될 때까지 대기
        if len(self.short_stamps) >= PER_SEC_LIMIT:
            sleep_s = WINDOW_SHORT - (now - self.short_stamps[0]) + 0.01
            time.sleep(max(0.0, sleep_s))
            return self.wait()
        if len(self.long_stamps) >= PER_2MIN_LIMIT:
            sleep_s = WINDOW_LONG - (now - self.long_stamps[0]) + 0.5
            print(f"  [rate] 장기 한도 도달, {sleep_s:.1f}s 대기", file=sys.stderr)
            time.sleep(max(0.0, sleep_s))
            return self.wait()

        # 토큰 발급
        self.short_stamps.append(now)
        self.long_stamps.append(now)


class RiotClient:
    def __init__(self,
                 api_key: str | None = None,
                 platform: str = "EUN1",
                 region: str = "europe") -> None:
        self.api_key = api_key or os.environ.get("RIOT_API_KEY")
        if not self.api_key:
            raise SystemExit(
                "RIOT_API_KEY 가 설정되지 않았습니다. "
                "api/.env.example 을 .env 로 복사하고 키를 채우거나 "
                "환경 변수 RIOT_API_KEY 로 export 하세요."
            )
        if platform not in PLATFORM_HOSTS:
            raise ValueError(f"Unknown platform: {platform}")
        if region not in REGIONAL_HOSTS:
            raise ValueError(f"Unknown region: {region}")

        self.platform_host = PLATFORM_HOSTS[platform]
        self.region_host = REGIONAL_HOSTS[region]
        self.session = requests.Session()
        self.session.headers.update({"X-Riot-Token": self.api_key})
        self.rate = RateLimiter(deque(), deque())

    # ── 내부 ───────────────────────────────────────────────────────────
    def _get(self, host: str, path: str, params: dict | None = None) -> dict | list:
        url = f"https://{host}{path}"
        for attempt in range(6):
            self.rate.wait()
            r = self.session.get(url, params=params, timeout=10)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                retry = int(r.headers.get("Retry-After", "1"))
                print(f"  [429] {path} retry-after {retry}s (attempt {attempt+1})",
                      file=sys.stderr)
                time.sleep(retry + 0.5)
                continue
            if r.status_code in (500, 502, 503, 504):
                wait = 2 ** attempt
                print(f"  [{r.status_code}] {path} 서버 일시 오류, {wait}s 대기",
                      file=sys.stderr)
                time.sleep(wait)
                continue
            r.raise_for_status()
        raise RuntimeError(f"GET {path} 6회 재시도 모두 실패")

    # ── 공개 API ───────────────────────────────────────────────────────
    def summoner_by_name(self, summoner_name: str) -> dict:
        path = f"/lol/summoner/v4/summoners/by-name/{requests.utils.quote(summoner_name)}"
        return self._get(self.platform_host, path)

    def matches_by_puuid(self, puuid: str, *, queue: int = 420,
                        count: int = 20, start: int = 0) -> list[str]:
        path = f"/lol/match/v5/matches/by-puuid/{puuid}/ids"
        params = {"queue": queue, "count": count, "start": start, "type": "ranked"}
        return self._get(self.region_host, path, params)

    def match_detail(self, match_id: str) -> dict:
        path = f"/lol/match/v5/matches/{match_id}"
        return self._get(self.region_host, path)
