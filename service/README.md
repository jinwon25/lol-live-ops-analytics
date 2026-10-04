# 웹서비스 실행·확장 안내

현재 구성은 FastAPI + HTML/CSS/JavaScript다. API 키·원본 DB 없이 개인 복기와 참고 분석을 실행한다. 공식 전적 가져오기를 사용하려면 서버 키가 필요하다.

프로젝트 루트에서:

```powershell
python -m pip install -r service/requirements.txt
python -m uvicorn service.main:app --reload --host 127.0.0.1 --port 8000
```

브라우저: http://127.0.0.1:8000 · API 스키마: http://127.0.0.1:8000/docs

## 구성

| 경로 | 역할 |
| --- | --- |
| `main.py` | 조회·도우미·수동 복기 API, 입력 범위 검증 |
| `evidence.py` | 집계 CSV와 근거를 읽는 계층 |
| `review.py` | 경기 요약·4가지 복기 초점·저장 조건 |
| `riot.py` | KR 공식 전적 조회·제한·캐시·본인 수치 정규화 |
| `data/catalogue.json` | 공식 한국어 챔피언 정적 자료의 버전 고정 사본 |
| `../web/` | 네 개 화면·개인 경기 기록·조건별 비교 |
| `../scripts/sync_catalogue.py` | KR realm 기준 정적 자료 갱신 |
| `../tests/` | 현재성·분모·개인 기록 조건·공식 연결의 모의 응답 검증 |

도우미는 등록된 분석의 키워드·템플릿 응답이며 LLM 추론은 아직 연결되지 않았다. API 연결 코드는 모의 응답으로 검증했고 실제 키로 본인 전적을 조회하는 확인은 남아 있다.

## 개인 복기 사용

완료 경기 입력 → 초점 선택 → 요약 확인 → 장면에서 본 사실·다음 행동 기록 → 저장 순서로 사용한다. 합성 예제는 수정해도 저장되지 않는다. `내 경기 입력 시작`으로 초기화한 뒤 실제 수치를 입력한다.

개인 경기·행동 기록은 이 브라우저의 localStorage에 경기 일시 기준 최근 50개, 기존 자유 노트는 별도 최근 10개를 보관한다. 같은 조건·일시는 갱신한다. 개인 비교는 지역·큐·게임 버전·티어·챔피언·포지션이 같은 6경기부터 최근 3개/직전 3개의 평균과 유효한 분모를 보여준다. 6경기는 표시 기준이며 통계적 유의성이나 실력 향상을 보장하지 않는다.

복기 장면·행동은 서버로 보내지 않는다. 요약을 위해 입력한 수치는 로컬 서버가 처리하되 디스크에 저장하지 않는다. 공유 PC에서는 경기별 삭제·자유 노트 삭제를 사용하거나 해당 사이트의 브라우저 데이터를 지운다. 브라우저 데이터 삭제·포트/호스트 변경으로 기록이 사라지거나 다른 저장 공간이 될 수 있으므로 장기 기록의 내보내기는 후속 범위다.

선택적으로 Git에서 제외된 `.local/companion.json`에 `region`, `queue`, `tier`, `division`, `role`, `champions` 기본값을 둔다. 챔피언은 공식 ID 1~3개를 사용한다. 이는 현재의 입력 기본값이며 과거 경기 당시 조건을 확인하는 일을 대신하지 않는다. Riot ID·키·전적은 이 파일에 넣지 않는다.

## 공식 전적 연결

[Riot Developer Portal](https://developer.riotgames.com/)에서 본인용 키를 발급·신청한다. 개발 키는 24시간마다 만료되며 공개 운영용 키와 다르다. [키 종류·연동 방식 검토](../docs/08_riot_integration.md)

프로젝트 루트에서 최초 설정:

```powershell
if (-not (Test-Path -LiteralPath service/.env)) {
    Copy-Item -LiteralPath service/.env.example -Destination service/.env
}
```

로컬 편집기로 `service/.env`의 `RIOT_API_KEY=`에 실제 키를 입력한다. 파일은 Git에서 제외한다. 키를 채팅·브라우저 폼·README에 입력하지 않는다. 환경 변수가 이미 설정되어 있다면 파일 없이 기본 실행 명령을 사용해도 된다.

```powershell
python -m uvicorn service.main:app --reload --host 127.0.0.1 --port 8000 --env-file service/.env
```

경기 복기 화면에서 Riot ID 게임 이름·태그를 입력한다. 기본 KR 솔로듀오 최근 5개를 조회하며 연결 경로는 로컬에서만 허용한다. 현재 랭크는 별도 표시하고 경기 당시 티어는 자동 적용하지 않는다. 경기 선택 후 조건을 확인하고 요약한다. 입력한 ID는 로컬 서버와 Riot에 전달되지만 이 구현은 ID·PUUID·원본 전적을 디스크에 저장하지 않는다.

키 설정 여부와 유효성은 다르다. 401/403은 키·권한·만료를 확인하고, 429는 응답의 대기 안내를 따른다. 404는 ID·태그를 확인한다. 누락·짧은 경기·조기 종료·미지원 포지션은 제외한다. API 키·응답·원본 전적을 공개 로그에 추가하지 않는다.

## 공식 자료 갱신

```powershell
python scripts/sync_catalogue.py
# 필요하면 공식 목록에 존재하는 버전을 고정
python scripts/sync_catalogue.py --version 16.19.1
```

자료에 버전·확인 시각·공식 URL·정규화된 원본 JSON 해시를 남긴다. 서비스 실행 중 갱신했다면 서버를 재시작한다. 공식 패치 노트 링크·게시일은 검토 후 `main.py`의 별도 기록도 갱신한다. 정적 자료 갱신으로 승률이나 과거 분석 CSV가 갱신되지는 않는다.

## 검증

```powershell
python -m unittest discover -s tests -v
```

현재 CI는 데이터 없이 가능한 서비스 API 검증이다. 원본을 이용한 전체 SQL·군집 분석과 실시간 API 운영을 대신하지 않는다.

브라우저 흐름 검증은 선택적으로 실행한다. 임시 서버는 검증 후 종료된다.

```powershell
python -m pip install playwright
python -m playwright install chromium
python scripts/check_service_ui.py
```

## 후속 개발 경계

기존 `api/`는 SQLite 적재 PoC이고 `service/riot.py`는 원본을 저장하지 않는 선택 조회다. 단일 로컬 서버의 메모리 캐시·제한을 여러 이용자 운영에 그대로 사용하지 않는다. 타임라인 분석·LLM은 구조화된 근거 계층 뒤에 연결한다. 공개 서버 배포 전에 제품 등록·승인과 운영용 키 범위를 확인한다. [분석·서비스 기획](../docs/06_companion_plan.md)을 참고한다.
