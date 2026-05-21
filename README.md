# League of Legends 라이브 운영 분석 — 패치 드리프트 + 유저 세그멘테이션

게임 회사(모바일 가챠 RPG, 라이브 운영) 데이터 분석 직무 지원용 포트폴리오. 롤 랭크 데이터를 *"누가 이기나"* 승부 예측이 아니라 **라이브 운영 분석가의 시선**으로 분석한다 — 게임이 건강한가, 유저는 어떻게 나뉘나, 패치로 무엇이 바뀌었나.

## 진행 기간

2026년 5월 (1주, Day 1~7) · 단독 작업

## 역할

- 데이터 하모나이즈 / SQLite 정규화 적재
- SQL(CTE · 윈도우 함수) 기반 메타 분석 + Wilson 신뢰구간 통계 처리
- 역할 내 z-score → K-means 세그멘테이션 + 페르소나 명명
- Riot API 수집 파이프라인 (rate limit · 백오프 · .env 보안)
- Looker Studio 대시보드 기획

## 데이터

| 데이터 | 출처 | 비고 |
|---|---|---|
| 2025.csv (패치 15.3 위주) | Kaggle — League of Legends Ranked Match Data Season 15 (EUN) | 6,830 경기 / 68,300 행, 솔로듀오만 |
| 2024.xlsx (패치 15.1 위주) | Kaggle — league_data | 4,045 경기 / 40,412 행, 큐 혼합 → queue_id=420 필터 |
| Riot Games API (PHASE 5) | https://developer.riotgames.com/ | KR 서버 / 실시간 수집 PoC (검증 통과) |

> 두 캐글 파일은 *연도 비교가 아니라* **패치 15.1 vs 15.3 메타 드리프트** 비교다. 모든 산출물·메모·차트에 동일 표기 통일.

## 분석 흐름

### Phase 1 — 데이터 하모나이즈 & 정규화 적재
- 두 파일을 공통 캐노니컬 스키마로 변환 (positions: MIDDLE→MID, BOTTOM→BOT, UTILITY→SUPPORT)
- SQLite 정규화 — `matches` / `participants` 2 테이블 + PK·FK·인덱스
- 적재 검증 7개 쿼리 (`sql/00_validate.sql`)

### Phase 2 — 메타 SQL (축1: 메타 헬스 + 패치 드리프트)
- 챔프 픽률 · 승률 · 평균 KDA/GPM/시야 (`sql/10_champ_stats.sql`)
- 다양성 지표 HHI / 유효 챔프 수 / Gini (`sql/11_diversity.sql`)
- NERF / BUFF_HIDDEN_STRONG 자동 플래깅 — 라벨별 컷 분리 + Wilson 95% 하한 (`sql/12_flagging.sql`)
- 15.1→15.3 드리프트 + Wilson 신뢰구간 + ⭐ 코호트(PLAT+EM+DIA) vs naïve 교란 통제 (`sql/13_patch_drift.sql`)

### Phase 3 — 플레이 스타일 세그멘테이션 (축2)
- 분석가 판단으로 피처 재선택 — 결과 신호(KDA · deaths) 제거 후 프로세스 4지표(GPM · DPM · 시야 · KP)만으로 재군집화
- 역할 내 z-score → K-means → 엘보우+실루엣 → K=4 채택
- 4개 페르소나 명명 + 콘텐츠/리텐션 가설 3건

### Phase 4 — Looker Studio 대시보드
- 깨끗한 5종 집계 CSV (한글 챔프명 + 라이엇 패치노트 매칭 컬럼 포함)
- 3페이지 구성안 — P1 메타 헬스 + 패치 검증, P2 ⭐ 교란 효과, P3 페르소나

### Phase 5 — Riot API 수집 파이프라인
- Account-v1 (RiotID) → Match V5 → PHASE 1 공통 스키마로 적재
- Rate limit 토큰 버킷 2단(20/sec + 100/2min) + 429 Retry-After 백오프
- `.env` 자동 로더 + `api/.env` gitignore (키 안전 분리)
- 적재 직후 캐글 SQL 그대로 동작 → puuid 인덱스로 PHASE 3 한계 확장의 길 확보

## 기술 스택

| 영역 | 도구 |
|---|---|
| 데이터 처리 | Python (pandas, openpyxl) |
| 적재 / 집계 | SQLite + SQL (CTE · 윈도우 함수 · NTILE) |
| 통계 | Wilson 95% 신뢰구간(직접 SQL 구현), 정규근사 두 비율 차 CI |
| 모델링 | scikit-learn (StandardScaler, KMeans, PCA, silhouette_score) |
| 시각화 | matplotlib (한글 폰트), Looker Studio |
| API | requests (Riot Games API V5: Account, Match) |
| 협업 | Git, GitHub |

## 주요 결과

### ⭐⭐ 스웨인 예측 적중 — 분석 → 라이엇 실제 패치 매칭

PHASE 2 에서 `BUFF_HIDDEN_STRONG` 후보로 잡은 **Swain MID (15.1, n=21, win 81%, Wilson 95% 하한 60%)** 챔프를, **라이엇이 다음 패치 15.3 에 실제로 버프** (Ravenous Flock 영혼당 체력 12→15, Nevermove AP비 70%↑).

이는 단순 사후 매칭이 아니라 *분석이 라이엇 밸런스팀과 같은 결론에 독립적으로 도달*한 증거. 컷을 라벨별로 분리한 분석가 판단(초기 0건 → 진단 → Wilson 신뢰구간 기반 재정의 → 발견 → 외부 검증)의 인과 사슬은 `docs/02_phase2_notes.md §9.2`.

### 라이엇 패치노트 정밀 매칭 6건

| 챔프 | 분석 신호 | 라이엇 15.3 실제 |
|---|---|---|
| 비에고 | 픽률 −0.59pp (저묾 3위) | base AD 60 → 57 NERF |
| 오공 | 픽률 −0.97pp (저묾 1위) | Warrior Trickster CD↑, Nimbus Strike AS↓ NERF |
| 미스 포츈 | 픽률 −0.43pp | base armor 28 → 25 NERF |
| 스카너 | 픽률·승률 동시 하락 | armor 성장↓, Q 스턴 1.5→1.1s NERF |
| 케인 | 픽률 +0.40pp (떠오름 7위) | Reaping Slash 데미지↑ BUFF |
| 퀸 | 교란 효과 분석에 등장 | Heightened Senses AS 60→80% BUFF |

### ⭐ 교란 효과 — 이즈리얼

티어 통제 없이 본 픽률 변화(naïve)는 패치 효과를 **최대 2.7배 부풀림**.
- 이즈리얼: **naïve rank 5위 ↔ 코호트(PLAT+EM+DIA) rank 30위**
- 픽률 변화의 대부분은 패치 효과가 아니라 표본의 티어 분포 차이였음

### 4개 플레이 스타일 페르소나 (역할 내 z-score 기반)

| 페르소나 | 비중 | 승률 | 특징 |
|---|---|---|---|
| 시야 컨트롤형 | 20.0% | 52% | vision z=+1.34, 나머지 평균 |
| 전투 추격형 | 34.0% | 49% | KP↑ + vision↓ (와드 없이 싸움만) |
| 스노우볼 패배 프로필 | 27.0% | 33% | 모든 행동 지표 ↓ |
| 슈퍼 캐리형 | 19.0% | 76% | GPM·DPM·KP 모두 ↑↑ |

모든 페르소나가 5개 role을 17~22% 균등 포함 → 역할 통제 검증 완료. 콘텐츠/리텐션 가설 3건은 `docs/03_phase3_notes.md §6`.

## 디렉토리 구조

```
lol-live-ops-analytics/
├── CLAUDE.md                  # 프로젝트 규약 · 단일 진실원천
├── README.md                  # 이 문서
├── .gitignore                 # data/raw, *.db, .env 등 제외
├── data/
│   ├── raw/                   # 원본 (gitignore 대상)
│   └── processed/             # SQLite (gitignore 대상)
├── sql/
│   ├── 00_validate.sql        # PHASE 1 적재 검증
│   ├── 05_views.sql           # v_cohort = PLAT+EM+DIA
│   ├── 10_champ_stats.sql     # 챔프×역할 통계
│   ├── 11_diversity.sql       # HHI / Gini / 유효 챔프 수
│   ├── 12_flagging.sql        # NERF / BUFF_HIDDEN_STRONG 자동 라벨링
│   └── 13_patch_drift.sql     # 15.1→15.3 드리프트 + naïve 대조
├── src/
│   ├── inspect_raw.py         # 원본 스키마 인스펙션
│   ├── load.py                # PHASE 1 적재
│   ├── run_validate.py        # 검증 쿼리 실행기
│   ├── sample_check.py        # PHASE 2 진입 표본 점검
│   ├── run_meta.py            # PHASE 2 SQL 일괄 실행 + CSV export
│   ├── segment.py             # PHASE 3 K-means + 페르소나
│   ├── build_dashboard_csv.py # PHASE 4 깨끗한 5종 CSV
│   ├── add_kr_names.py        # 챔프명 한글 컬럼 후처리
│   └── champion_kr.py         # 데이터드래곤 기반 영문→한글 매핑
├── outputs/                   # Looker Studio 연결용 CSV + PNG
│   ├── champion_meta.csv      # patch × champion × role + flag + 라이엇 매칭
│   ├── diversity.csv          # patch × role HHI/Gini
│   ├── patch_drift.csv        # 챔프별 드리프트 + 95% CI + 라이엇 매칭
│   ├── player_segments.csv    # 게임 단위 클러스터 라벨
│   ├── segment_summary.csv    # 클러스터 centroid + 비율 + 승률
│   ├── _clusters_pca_2d.png   # 페르소나 산점도
│   ├── _cluster_role_heatmap.png
│   └── _elbow_silhouette.png
├── docs/                      # 인사이트 메모 / 대시보드 plan / 패치노트 대조
│   ├── 01_phase1_notes.md
│   ├── 02_phase2_notes.md
│   ├── 03_phase3_notes.md
│   ├── 04_patch_notes_match.md
│   └── 05_dashboard_plan.md
└── api/                       # PHASE 5 Riot API 수집
    ├── README.md
    ├── .env.example           # 키 템플릿 (실제 .env 는 gitignore)
    ├── riot_client.py         # rate limit + 429 백오프
    └── collect.py             # Account-v1 → Match V5 → 공통 스키마
```

## 실행 방법

```bash
# 1. 의존성
pip install pandas scikit-learn matplotlib openpyxl requests

# 2. 캐글 데이터 적재 (data/raw/ 에 2024.xlsx, 2025.csv 배치 후)
python src/load.py
python src/run_validate.py

# 3. 메타 SQL 분석 (PHASE 2)
python src/run_meta.py

# 4. 세그멘테이션 (PHASE 3)
python src/segment.py

# 5. 대시보드용 깨끗한 CSV 생성 (PHASE 4)
python src/build_dashboard_csv.py
python src/add_kr_names.py

# 6. (선택) Riot API 수집 PoC (PHASE 5)
cp api/.env.example api/.env
# api/.env 에 RIOT_API_KEY, RIOT_SEED_RIOT_ID 채운 후
python api/collect.py --matches 20
```

## 인사이트 메모 인덱스

| 문서 | 핵심 내용 |
|---|---|
| [docs/01_phase1_notes.md](docs/01_phase1_notes.md) | 하모나이즈/적재 + 솔로 티어 분포 비대칭 발견 (코호트 통제의 출발점) |
| [docs/02_phase2_notes.md](docs/02_phase2_notes.md) | 메타 SQL · ⭐ 스웨인 인과 사슬 · 잔나 사각지대 · 신중 해석 박스 · 패치노트 매칭 |
| [docs/03_phase3_notes.md](docs/03_phase3_notes.md) | 세그멘테이션 · 피처 재선택 판단 · 4 페르소나 · 콘텐츠/리텐션 가설 |
| [docs/04_patch_notes_match.md](docs/04_patch_notes_match.md) | 라이엇 15.1/15.3 실제 너프·버프와 분석 신호 대조표 |
| [docs/05_dashboard_plan.md](docs/05_dashboard_plan.md) | Looker Studio 3페이지 구성안 (한 페이지 한 메시지) |
| [api/README.md](api/README.md) | Riot API 수집 사용법 + 보안 / rate limit 설명 |

## 진행 상태

- [x] PHASE 0–5 완료 (6 커밋, PHASE 단위로 분리된 깨끗한 히스토리)
- [x] Riot API 실작동 검증 (KR 서버, 20경기, 2.3초, 캐글 SQL 그대로 동작)
- [x] 패치 노트 외부 검증 — 분석 신호 6건 + 예측 적중 1건 (Swain)
- [ ] Looker Studio 대시보드 시각화 배포 (`docs/05_dashboard_plan.md` 기반)

## Contact

최진원 · munjwc25@gmail.com
