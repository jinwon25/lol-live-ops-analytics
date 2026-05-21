# Riot API 수집 파이프라인 (PHASE 5)

캐글 정적 데이터 외에 **Riot API 에서 직접 수집할 수 있음**을 증명하기 위한 작은 PoC.
설계 의도는 *대량 수집*이 아니라 *파이프라인이 실제로 작동한다 + PHASE 1 공통 스키마로 적재 + 캐글에 쓴 SQL 그대로 도는 것까지*.

## 구조

| 파일 | 역할 |
|---|---|
| `riot_client.py` | 얇은 API 래퍼. 토큰 버킷 rate limit(20/sec · 100/2min) + 429 백오프 |
| `collect.py` | 시드 소환사 → 매치 ID → 매치 상세 → PHASE 1 공통 스키마로 SQLite 적재 → 동일 분석 쿼리 실행 |
| `.env.example` | 환경 변수 템플릿 — 실제 키는 `api/.env` (gitignore 대상) |

## 사용법

### 1. 키 발급

[Riot Developer Portal](https://developer.riotgames.com/) 에서 개발자 키 발급.
- 개발자 키는 **24시간 만료** + rate limit (20 req/sec, 100 req/2min).
- 프로덕션 키는 별도 신청 필요.

### 2. 환경 변수 설정

```bash
# 옵션 A — 셸 export (간단)
export RIOT_API_KEY="RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# 옵션 B — api/.env 파일 (python-dotenv 사용 시)
cp api/.env.example api/.env
# 편집기로 api/.env 열어 키 입력
```

`api/.env` 는 `.gitignore` 에 의해 **절대 커밋되지 않습니다.** (`.env`, `.env.*`, `api/.env`)

### 3. 실행

```bash
python api/collect.py --seed "Hide on bush" --matches 20
```

`--matches` 는 rate limit 고려 **권장 ≤ 30**.

기본 지역은 EUN1 / europe. 다른 지역은 env 로:

```bash
export RIOT_REGION_PLATFORM=KR
export RIOT_REGION_ROUTING=asia
```

### 4. 산출

- `data/processed/lol_api.db` — 캐글 DB(`lol.db`) 와 동일한 `matches` / `participants` 테이블 구조 + **`participants.puuid` 인덱스** (캐글 DB에는 없는 컬럼)
- 적재 직후 `10_champ_stats` 와 동일 구조의 쿼리가 자동 실행되어 **공통 SQL 이 그대로 도는 것** 을 콘솔에 출력.

## 보안

- **`X-Riot-Token` 헤더만 사용** — URL 쿼리로 키를 노출하지 않음.
- `Session().headers` 에 키를 1회 설정 후 재사용 — 로그/예외 메시지에서 키 노출 위험 최소.
- `.env` 류는 `.gitignore` 에 등재됨 (`.env`, `.env.*`, `api/.env`).
- 적재 데이터에 `puuid` 가 포함됨 — 외부 공개 시 익명화 검토 필요.

## Rate Limit 처리

`riot_client.RateLimiter` 가 토큰 버킷 두 단(1초 / 120초)을 동시 추적.

- 단기 한도(20/sec) 도달 시 가장 오래된 토큰 만료까지 sleep.
- 장기 한도(100/2min) 도달 시 동일.
- 429 응답 시 `Retry-After` 헤더 + 0.5s 여유로 sleep, 최대 6회 재시도.
- 5xx 응답 시 지수 백오프 (2, 4, 8, 16, 32s).

## PHASE 3 한계 해소의 길

PHASE 3 의 군집화는 puuid 부재(P153 데이터 한계)로 *게임 단위 행동 프로필*에 머물렀다.
이 파이프라인으로 puuid 기반 데이터를 누적하면 **플레이어 단위 평균 프로필** 군집화가 가능해진다.

확장 방안:
1. 시드 소환사를 BFS 큐로 두고 participant 의 puuid 를 다음 시드로 — 표본 다양성 확보.
2. 일정 puuid 마다 동일 절차 수집 → 한 플레이어의 최근 50경기 프로필 평균.
3. 이걸 PHASE 3 의 K-means 입력으로 사용 → "부진 위축형이 잦은 *플레이어*" 와 같은 진짜 페르소나 산출.
