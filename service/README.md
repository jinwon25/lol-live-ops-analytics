# 웹서비스 실행 안내

LoL 인사이트 노트는 KR 솔로듀오 전적을 불러와 복기할 시각과 다음 경기에서 연습할 행동을 찾는 로컬 웹서비스입니다. FastAPI가 전적·집계 근거를 제공하고, HTML·CSS·JavaScript 화면은 행동과 보관 기록을 브라우저에 저장합니다.

## 실행 조건과 확인 방법

Python 3.11 이상에서 프로젝트 루트 기준으로 실행합니다. 저장된 공개 참고 집계와 챔피언 도감은 Riot 키나 연구 원본 없이 열립니다.

```powershell
python -m pip install -r service/requirements.txt
python -m uvicorn service.main:app --host 127.0.0.1 --port 8001
```

[로컬 서비스](http://127.0.0.1:8001)를 열고 **내 전적·리포트 / 보관함 / 데이터 인사이트**를 확인합니다.

## 공식 전적 연결

1. [Riot Developer Portal](https://developer.riotgames.com/)에서 사용 목적에 맞는 키를 준비합니다. 개인 연구는 개인 키를 신청할 수 있고 개발 키는 24시간마다 만료됩니다. 공개 운영에는 Riot 승인과 프로덕션 키가 필요합니다. [키 종류와 신청 범위](../docs/08_riot_integration.md)
2. `service/.env.example`을 `service/.env`로 복사한 뒤 로컬 편집기에서 `RIOT_API_KEY` 값을 설정합니다. 이미 파일이 있으면 그 파일을 사용합니다.
3. 서버를 다시 실행한 뒤 게임 이름과 태그를 입력합니다. KR 솔로듀오 최근 완료 경기 5개 또는 10개를 선택할 수 있습니다.

```powershell
if (-not (Test-Path -LiteralPath service/.env)) {
    Copy-Item -LiteralPath service/.env.example -Destination service/.env
}
python -m uvicorn service.main:app --host 127.0.0.1 --port 8001 --env-file service/.env
```

401·403은 키와 권한·만료를 확인하고, 404는 Riot ID와 태그를 확인합니다. 429는 화면의 대기 안내를 따릅니다. 경기 목록에서 조기 종료·짧은 경기·필수 정보 누락 또는 미지원 포지션의 경기를 제외합니다.

## 개인 복기와 보관함

| 기능 | 사용 방법 | 기록 범위 |
| --- | --- | --- |
| 경기 분석 | 경기를 선택해 핵심 요약의 종료 수치, 팀 비교, 시간대별 흐름을 읽습니다. 타임라인 연결은 조회 후 30분 동안 유효합니다. | 첫 15분에 관측된 본인 첫 데스 시각과 상대 포지션 대비 골드·CS를 확인합니다. |
| 연습 행동과 결과 | 제안한 행동을 저장한 뒤 **지난 연습 돌아보기**에서 시도 여부를 남깁니다. | 행동 노트 최대 10개. 별도 JSON 백업에 행동과 결과가 포함됩니다. |
| 자동 리포트 보관 | **이 리포트 보관**을 누르고, 보관함에서 포지션·승패·검색으로 찾습니다. 같은 챔피언·포지션·게임 버전인 두 경기의 지표를 비교할 수 있습니다. | 최대 50경기. 보관함 전용 JSON 백업을 사용합니다. |
| 기존 수동 복기 | 기존 기록을 가져와 검색·수정하거나, 같은 지역·큐·티어·챔피언·포지션·패치의 최근 3경기와 직전 3경기를 비교합니다. | 최대 500경기. 예전 경기 기록에 쓰던 JSON 형식을 읽고 새 직접 입력 화면은 제공하지 않습니다. |

JSON 복원은 파일을 선택해 미리보기에서 추가·중복 건수를 확인한 뒤 실행합니다. 중복은 현재 브라우저 기록을 우선합니다. 기록은 접속 주소별로 나뉘므로 호스트나 포트 변경 전에 해당 백업을 내보냅니다. Riot ID와 PUUID는 개인 보관함 및 행동 노트에 포함되지 않습니다. [두 경기 비교와 보관함](../docs/23_service_references_and_match_comparison.md) · [복구와 삭제 취소](../docs/19_storage_and_local_service_hardening.md)

현재 랭크는 조회 시점 기준입니다. 타임라인은 관측된 시각과 수치를 보여주며, 연습 행동의 시도 여부는 사용자가 직접 표시합니다. 로컬 AI는 모델과 추론 서버를 설정한 경우 종료 지표로 복기 초점 후보를 제안합니다. [서비스 방향과 검증 계획](../docs/24_project_review.md) · [로컬 모델의 실측 조건](../docs/14_model_selection_audit.md)

## Docker와 요청 예산

Docker Compose 2.24 이상에서 API와 Redis를 함께 실행할 수 있습니다. Riot 키는 `service/.env`로 전달됩니다.

```powershell
docker compose up --build -d
```

API 기본 포트는 `127.0.0.1:8001`에 연결됩니다. 서버 동기화 API의 SQLite 파일은 `service-data` 볼륨에 저장됩니다. 브라우저 기록은 각 브라우저 쪽에 보관됩니다. 로컬 추론 서버까지 실행할 때는 먼저 GGUF 모델을 [모델 문서](../docs/14_model_selection_audit.md)의 배치 경로에 두고 `docker compose --profile llm up -d`를 실행합니다.

Redis가 설정된 경우 여러 작업자가 요청 예산을 공유하며, Redis 장애 동안 새 Riot 요청은 중단됩니다. 동기화 API는 로컬·사설망의 같은 출처로 제한합니다. 다중 사용자 공개 배포에는 인증과 사용자 소유권 설계가 필요합니다. [요청 제한·장애 처리](../docs/22_shared_budget_followup.md) · [저장과 로컬 보호](../docs/19_storage_and_local_service_hardening.md)

## 데이터 인사이트와 자료 갱신

공식 챔피언 도감, 패치별 메타 표본, 과거 연구 집계의 범위를 각각 표시합니다. KR 메타 표본은 경기 당시 티어가 확인된 동티어 집계로 사용하지 않습니다. [메타 수집·표시 조건](../docs/17_match_explorer_and_riot_collection.md)

```powershell
python scripts/sync_catalogue.py
python scripts/sync_ui_assets.py
```

정적 자료에는 버전·확인 시각·공식 URL·원본 해시를 기록합니다. 과거 배치와 승률 표본은 자체 수집·집계 경로에서 갱신합니다. [데이터 파이프라인](../docs/25_data_pipeline.md) · [EUN·KR 백필](../docs/26_backfill_sample.md)

## 검증

```powershell
python -m pip install -e ".[analytics,dev]"
python -m pytest -q
node --test tests/test_journal.cjs tests/test_analysis.cjs tests/test_reports.cjs tests/test_notes.cjs
python -m playwright install chromium
python scripts/check_service_ui.py
```

브라우저 검증은 임시 로컬 서버와 모의 Riot 응답을 사용합니다. 실행 중인 서버의 준비 상태는 `python scripts/check_service_readiness.py`로 확인할 수 있습니다. GitHub Actions에서 Redis 통합 검사, 브라우저 검증, Docker 이미지와 저장 볼륨 검사도 실행합니다. [서비스 검증 워크플로](../.github/workflows/checks.yml)

## 주요 파일

| 경로 | 역할 |
| --- | --- |
| [API와 접근 제어](main.py) · [Riot 게이트웨이](riot.py) · [요청 예산](riot_transport.py) | 기능별 엔드포인트, 전적 연결, 캐시와 요청 제한 |
| [리포트](match_report.py) · [타임라인](timeline.py) · [로컬 AI](local_coach.py) | 종료 수치, 시간대 관측, 선택적 모델 실행 |
| [경기 화면](../web/match_views.js) · [보관함](../web/reports.js) · [행동 노트](../web/notes.js) | 경기 탐색, 로컬 기록·결과, JSON 백업 |
| [근거 계층](evidence.py) · [정적·집계 자료](data/) | 저장한 분석과 챔피언 도감 읽기 |

[서비스·분석 문서 안내](../docs/README.md)
