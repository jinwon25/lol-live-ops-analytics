# 공개 데이터 조사와 실제 반영 — 2026-10-05

공개 자료 13개를 공식 제공 페이지·카드·API 메타데이터 중심으로 검토했다. 모든 대용량 원본을 내려받은 것은 아니다. 실제 반영 자료는 Zenodo 8303397의 시점별 팀 데이터 5개 CSV이며, 나머지는 확인 수준과 적용 판단을 아래에 적었다. 최신 KR 개인 분석에는 Riot Match-V5를 우선 사용한다.

## 조사 결과

| 자료 | 시기·단위 | 이용 조건 | 확인 수준·적용 판단 |
|---|---|---|---|
| [Riot Match-V5 · Timeline](https://developer.riotgames.com/apis#match-v5/GET_getTimeline) | 조회 가능한 실제 경기 기준 · 경기·참여자·분별 프레임·이벤트 | Riot API 약관·개발자 정책 | 공식 전적 연결 사용 중 · 타임라인은 후속<br>API 키·호출 한도 필요. 수집 당시 현재 랭크를 경기 당시 티어로 대체할 수 없음. |
| [Riot Data Dragon](https://developer.riotgames.com/docs/lol#data-dragon) | 현재 서비스 고정 버전 16.19.1 · 챔피언·아이템·룬·정적 이미지 | Riot 게임 정적 자료·개발자 정책 | 반영 중<br>경기 표본이나 승률·개인 실력 데이터가 아님. |
| [Zenodo · 시점별 랭크 경기](https://zenodo.org/records/8303397) | 2023-01-12~2023-05-18 · 경기·팀 · 종료 길이의 20/40/60/80/100% | CC BY 4.0 | 검증·집계 반영<br>개별 지역·패치·티어·챔피언·포지션 없음. 현재 개인 백분위·실시간 예측에 사용 불가. |
| [Zenodo · KR High Elo 5v5](https://zenodo.org/records/6636849) | 2022-06-12 기준 · KR 챌린저에서 시드한 경기 | CC BY 4.0 | 후보 · 대용량 원본 미다운로드<br>제공자 설명: 2,078개 16분 초과 경기, 경기 파일 1.11GB. 상위권 시드와 혼합 로비를 현재 모든 티어로 일반화할 수 없음. |
| [Hugging Face · leagueData](https://huggingface.co/datasets/renecotyfanboy/leagueData) | 2024-01-10~2024-04-11 · EUW 경기×참여자 | 제공자 카드: MIT | 스키마 확인 · 원본 반영 보류<br>원본 CSV 3.19GB. 열 목록에 matchId 없음. elo는 표본 선정 당시 랭크. 중복 경기 검증·경기 당시 티어 비교에 부적합. |
| [GPTilt · Challenger basic matches](https://huggingface.co/datasets/gptilt/lol-basic-matches-challenger-10k) | 2025 자료 · 마지막 수정 2025-07-15 · 경기·참여자·이벤트 | CC BY-NC 4.0 | 제품 반영 보류 · 비상업 조건<br>상위권 시드이며 로비의 모든 참가자가 챌린저라는 뜻이 아님. 유료 제품용 데이터와 분리 필요. |
| [GPTilt · Enriched Events](https://huggingface.co/datasets/gptilt/lol-ultimate-events-challenger-10m) | 2025 자료 · 위치·자원·아이템을 포함한 이벤트 | CC BY-NC 4.0 | 제품 반영 보류 · 비상업 조건<br>약 2.38GB. 변환 이벤트는 Riot 원본 이벤트와 다름. 현재 KR 동티어 표본 아님. |
| [Kaggle · Diamond Ranked Games (10 min)](https://www.kaggle.com/datasets/bobbyscience/league-of-legends-diamond-ranked-games-10-min) | 2020 공개 자료 · 경기·팀 · 고정 10분 | 현재 데이터 카드본문·라이선스 확인 불가 | 후보 · 원본·조건 재검증 전<br>약 1만 경기로 소개. 개인 챔피언·역할·현재 KR 기준이 아님. 코드 노트북 라이선스와 데이터 라이선스는 구분해야 함. |
| [Kaggle · SOLO-Q Ranked Games](https://www.kaggle.com/bobbyscience/league-of-legends-soloq-ranked-games/activity) | 2020 공개 자료 · 경기·팀 · 10분부터 2분 간격 | 제공자 카드: CC0 | 후보 · 원본 미검증<br>제공자 설명: 약 2.5만 경기·24만 프레임, PLATINUM. 경기별로 나눠야 하며 프레임 무작위 분할은 누수 위험. |
| [Oracle’s Elixir](https://oracleselixir.com/tools/downloads) | 연도별 프로 대회 데이터 · 프로 경기·선수·팀 | 다운로드 파일의 이용 조건 미확인 | 보류 · 직접 다운로드 페이지 403<br>프로 경기를 일반 솔로랭크 비교 표본으로 대체할 수 없음. 사이트 일부 콘텐츠의 라이선스를 전체 데이터에 적용하지 않음. |
| [HakimT · Champion Ranked Stats](https://huggingface.co/datasets/HakimT/lol-champion-ranked-stats) | 2015-02~2026-04 · 16.7까지 · 챔피언·역할·패치별 집계 | 제공자 카드: CC BY 4.0 | 보류 · 원출처·분모 확인 필요<br>익명 통계 사이트 수집이라고 설명. 지역·표본 수·원 제공자 이용 조건이 없어 최신 KR 추천이나 신뢰구간 계산에 사용하지 않음. |
| [EsportsBench](https://huggingface.co/datasets/EsportsBench/EsportsBench) | 버전별 대회 결과 · 6.0 기준 2025-06-30 cutoff · 대회 팀 간 결과 | CC BY-SA 3.0 | 범위 외 · 제품 미반영<br>개인 행동·분별 경기 프레임이 없는 대회 결과. 이 서비스의 개인 실력 점수 학습에 맞지 않음. |
| [GPTilt · Esports Matches](https://huggingface.co/datasets/gptilt/lol-esports-matches) | 2011~2026-09 · 수정 2026-09-27 · 대회 일정·게임·밴픽 | CC BY-SA 3.0 · 카드 Direct Use는 non-commercial로 기술 | 보류 · 용도 조건 불일치 확인 필요<br>Leaguepedia 파생 자료. attribution·share-alike 필요. 솔로랭크 표본이 아니며 카드의 상업 용도 기술을 별도 확인해야 함. |

Zenodo 두 자료는 제공자 메타데이터에서 CC BY 4.0을 확인했다. leagueData는 공식 카드·파일 크기·CSV 열 목록·첫 행 스키마를 확인했다. GPTilt의 비상업 조건은 실제 README를 확인했으며 유료 서비스 지향과 맞지 않아 원본을 반영하지 않았다. Kaggle Diamond 10min은 자료 카드 접근에 실패해 라이선스를 확정하지 않았다. SOLOQ 프레임 자료의 CC0는 제공자 설명 기준이며 원본은 아직 내려받지 않았다. Oracle’s Elixir 다운로드 페이지는 접근이 막혀 전체 CSV의 이용 조건을 확인하지 못했다. HF 집계 자료도 원천 수집 사이트의 권리까지 확인한 것으로 취급하지 않는다.

## 채택 자료와 재현

[League of Legends Match Data at Various Time Intervals](https://zenodo.org/records/8303397), Jailson Barros da Silva Junior·Claudio Campelo, 2023. 제공자 [메타데이터](https://zenodo.org/api/records/8303397)와 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 조건을 확인했다. 원본을 변환·정제해 팀 골드 격차 구간과 최종 블루 팀 승리 관측 비율을 집계했다. 제공자의 원래 분석이나 실시간 예측 모델을 재현했다고 주장하지 않는다.

```powershell
python scripts/sync_public_data.py
python -m unittest discover -s tests -v
```

원본은 Git에서 제외된 `data/raw/public/zenodo-8303397/`, 집계는 `service/data/public_flow.json`, 조사 목록은 `service/data/data_sources.json`에 있다. 공식 제공자의 고정 파일명·MD5를 검사하고 SHA256·원본 URL·파일 크기·저작자·변환 방식·제외 사유를 집계 파일에 남겼다. 개인 식별자와 경기 ID는 서비스 응답에 포함하지 않는다.

## 파일을 읽고 확인한 품질 문제

- 각 CSV는 **64,556행**이다. 5개 시점의 행을 별도 경기로 세지 않고 `matchID`로 결합했다.
- 20·40·60·80% 파일 각각에서 5~90분 범위 밖의 2,935경기를 제외했다. 실제 제외 경기들은 5분 미만이었다.
- 100% 파일에서는 위 2,935경기와 프레임 시각이 경기 종료 길이와 맞지 않는 6경기를 추가 제외했다.
- 파일 안 동일·충돌 중복은 발견되지 않았다. 공통 **61,615경기**에서 결과·경기 길이·시점 순서·누적 골드를 검증했고 추가 불일치는 없었다. 경기 길이 중앙값은 30분이다.
- `timePercent`라는 열은 실제로 프레임 시각을 **분**으로 담는다. 종료 길이의 비율은 파일명 20·40·60·80·100에서 얻는다. 20% 프레임의 실제 시각 중앙값은 5분이다.

같은 경기 안에서 시점·골드가 역전하거나 승패가 다르면 경기 전체를 제외한다. 숫자 누락·비유한 값·잘못된 승패를 0으로 채우지 않는다. 종료 100% 프레임은 검증에만 사용하고 골드와 승패의 관계 표에는 사용하지 않는다. 구간 표본이 30 미만이면 비율을 표시하지 않는다.

## 화면과 분석에서 사용하는 범위

`데이터 인사이트 → 경기 흐름 분석`에서 종료 길이의 20·40·60·80% 시점을 바꾸고 팀 골드 격차 구간별 경기 수와 관측 승리 비율을 본다. `데이터 출처`에서 원본·라이선스·집계 기준·13개 자료의 반영 여부를 확인한다. 개인 전적 리포트와 이 과거 팀 표본은 별도 경로다.

이 자료에는 개별 경기의 지역·패치·티어·챔피언·포지션이 없다. 따라서 현재 KR 동티어 백분위·챔피언 티어 순위·개인 약점 점수로 사용하지 않는다. 종료 길이를 알아야 비율 시점을 정할 수 있으므로 실시간 예측에는 미래 정보가 포함된다. 반복 참여자를 확인할 식별자도 없어 표본 독립성을 검증하지 못했다.

## 다음 데이터 고도화의 우선순위

최신 KR 개인 분석은 공식 Match-V5 종료 수치로 시작하고 Timeline의 분별 골드·CS·경험치·이벤트를 추가한다. 정규화 단계에서 불명확한 챌린지·이벤트 정의를 먼저 검증한다. 현재 랭크를 과거 경기 당시 티어로 대체하지 않는다.

챔피언 티어와 역할별 기준선을 만들려면 최신 패치·지역·큐·포지션·표본 수·수집 기간을 확보해야 한다. 수집 시점 랭크의 편향과 혼합 로비를 기록하고 작은 표본에는 순위 산출을 보류한다. 공개 프로 경기 자료는 선수·대회 비교에 쓰며 개인 솔로 랭크의 기준선과 구분한다.

예측 모델은 경기 단위 그룹 분할과 시간 순서 검증을 적용한다. 플레이어 식별자가 있을 때는 플레이어 중복 누수도 따로 검사한다. 현재 종료 길이 상대 프레임을 고정 10분 모델로 변환하거나 동일 경기의 다른 시점을 훈련·시험 양쪽에 나누지 않는다.
