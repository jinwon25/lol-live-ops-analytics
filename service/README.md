# 웹서비스 실행·확장 안내

현재 구성은 FastAPI + HTML/CSS/JavaScript다. Node.js·API 키·원본 DB 없이 저장된 집계와 공식 정적 자료로 실행한다.

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
| `data/catalogue.json` | 공식 한국어 챔피언 정적 자료의 버전 고정 사본 |
| `../web/` | 네 개 화면과 브라우저 복기 노트 |
| `../scripts/sync_catalogue.py` | KR realm 기준 정적 자료 갱신 |
| `../tests/test_service.py` | 현재성·근거·입력 경계·미정의 분모 검증 |

도우미는 등록된 분석의 키워드·템플릿 응답이다. 최신 경기 조회와 LLM 추론은 아직 연결되지 않았다. 수동 경기 입력은 요청 처리 후 저장하지 않고, 복기 노트는 브라우저 localStorage에 최근 10개만 저장한다. shared PC에서는 화면의 기록 삭제 기능으로 지울 수 있다.

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

Riot 수집은 기존 `api/`와 연결하되 서버 측 키·수집 예산·호출 제한·데이터 보관을 먼저 정한다. LLM은 구조화된 근거를 반환하는 도구 계층 뒤에 둔다. 공개 서버 배포 전에 제품 등록·승인 범위를 확인한다. [분석·서비스 기획](../docs/06_companion_plan.md)을 참고한다.
