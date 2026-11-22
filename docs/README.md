# 서비스·분석 문서 안내

[프로젝트 README](../README.md)에서 서비스 대상과 주요 결과를 확인한 뒤, 필요한 주제로 이동합니다.

## 읽는 순서

| 읽고 싶은 내용 | 문서 | 확인할 점 |
| --- | --- | --- |
| 직접 서비스 실행 | [웹서비스 안내](../service/README.md) → [Riot 연동](08_riot_integration.md) | 서버 시작, 키 설정, 최근 경기 조회, 행동 기록과 백업 |
| 아브실골 복기 서비스 이해 | [서비스 방향과 검증 계획](24_project_review.md) → [보관함 경기 비교](23_service_references_and_match_comparison.md) | 지금 가능한 복기·연습과 근거를 활용하는 에이전트 개발 범위 |
| 과거 데이터와 분석 결과 확인 | [데이터와 표본](01_phase1_notes.md) → [메타 분석](02_phase2_notes.md) → [경기 행동 군집](03_phase3_notes.md) | EUN 15.1·15.3의 비교 조건과 경기×참여자 단위 |
| 수집·배치를 재현 | [데이터 파이프라인](25_data_pipeline.md) → [EUN·KR 백필](26_backfill_sample.md) | 스냅샷, 경기 격리, 집계 게시, 체크포인트 복구와 분석용 내보내기 |

## 주제별 문서

| 주제 | 문서 | 용도 |
| --- | --- | --- |
| 패치 분석과 시각화 | [패치 노트 대조](04_patch_notes_match.md) · [대시보드 설계](05_dashboard_plan.md) | 이미 공개된 패치와 관측치를 비교하고 BI용 지표 해석 |
| 서비스의 출발점 | [복기 서비스 구상](06_companion_plan.md) · [상용 서비스 참고](07_service_benchmark.md) | 개인 복기 흐름과 근거 표시를 설계한 배경 |
| 외부 데이터 | [공개 데이터 연구](11_public_data_research.md) · [별도 API 수집 예제](../api/README.md) | 출처·커버리지·라이선스와 SQLite 적재 예제 |
| 로컬 AI | [모델 후보와 실측](14_model_selection_audit.md) · [초기 LoRA 실험](13_local_llm_research.md) | 실행 환경, 출력 검증, 모델 실험의 평가 범위 |
| 저장과 운영 | [기록 보존과 로컬 보호](19_storage_and_local_service_hardening.md) · [AI 준비 상태와 행동 노트](20_runtime_and_notes_followup.md) · [Redis 요청 예산](22_shared_budget_followup.md) | 보관·복구, 로컬 실행과 장애 처리 |

<details>
<summary>초기 화면과 구현 기록</summary>

- [개인 복기 기능](09_service_status.md) · [개인 분석 UI](10_personal_analysis_ui.md) · [자동 리포트와 내비게이션](12_structure_and_auto_reports.md)
- [상용 UI 참고](15_commercial_ui_refinement.md) · [컬러·내비게이션](16_geng_theme_and_navigation.md)
- [경기 탐색·메타 수집](17_match_explorer_and_riot_collection.md) · [전적 중심 흐름과 기반 점검](18_service_foundation_and_api_only_flow.md)

</details>

## 먼저 이해할 용어

| 용어 | 이 프로젝트에서의 뜻 |
|---|---|
| 코호트(cohort) | 같은 조건으로 묶어 비교하는 표본입니다. 이 분석은 공통 티어를 맞춰 비교합니다. |
| 패치 번호 | 기존 경기의 15.1·15.3, 현재 정적 자료의 16.19.1, 패치 노트의 26.19는 서로 다른 표기·자료입니다. |
| HHI / Gini | 챔피언 선택이 특정 챔피언에 몰리는 정도 / 선택 비중의 불균등 정도입니다. |
| 역할 내 표준화 | 포지션별 분포를 기준으로 지표를 변환해 역할 차이를 줄이는 과정입니다. |
| K-means / K | 비슷한 관측을 묶는 군집 방법 / 군집 수입니다. 여기서는 사람의 고정 성격이 아니라 경기별 행동을 묶습니다. |
| silhouette | 군집 내부의 유사성과 다른 군집과의 분리를 요약하는 지표입니다. |
| %p | 두 비율의 차이인 퍼센트포인트입니다. 상대 증가율인 %와 다릅니다. |
| PoC | 연결 방식이 가능한지 확인하는 작은 구현입니다. 대규모 운영 안정성 검증과 구분합니다. |
| 동일 조건 비교 | 지역·큐·패치·티어·챔피언·역할이 같은 경기끼리 비교합니다. 작은 표본의 차이를 코칭 효과로 단정하지 않습니다. |

## 해석 기준

기술 통계, 개인의 복기 기록, 템플릿 응답, 향후 분석 계획을 구분합니다. 원본 경기·계정 식별자·API 키는 공개 문서나 이미지에 넣지 않습니다.
