# AI 서버 상태·공유 요청 예산·행동 노트 보존 — 2026-11-15

기존 백업 개선 이후 남은 코드를 점검해 설정만으로 AI가 준비되었다고 표시하는 문제, Redis 장애 시 워커별 예산으로 전환하는 문제, 손상된 행동 노트를 새 저장으로 덮어쓰는 문제를 보완했다. 기존 미커밋 변경과 개인 자료를 유지하며 로컬용 서비스의 범위에서 진행했다.

## 구현과 근거

| 작업 | 결과 | 근거·적용한 판단 |
| --- | --- | --- |
| AI 상태 | 기본 양자화 모델의 `/health` 확인, 전체 2초 제한, 리다이렉트 미추적, 본문·주소 비노출, 다시 확인 버튼 | [llama.cpp 서버 문서](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)의 200·503 의미와 [HTTPX 시간 제한](https://www.python-httpx.org/advanced/timeouts/)을 참고 |
| 공유 예산 | Redis가 설정된 상태에서 공유 예약 실패 또는 초기화 실패 시 새 외부 호출을 503으로 중단. 로컬에서 관측한 429 대기도 유지 | [Redis Lua 문서](https://redis.io/docs/latest/develop/programmability/eval-intro/)의 원자성은 Redis 내부 연산에 대한 것이다. 네트워크 장애 때 독립 예산으로 바꾸면 공유 한도 보장을 잃으므로 이 프로젝트는 중단하는 방식을 선택 |
| 행동 노트 | 같은 저장 키 유지, 정상 과거 null 항목 호환, 손상 시 쓰기 거부, 10개 초과 자동 삭제 제거, 선택 삭제·전체 삭제 취소 | [Storage.setItem](https://developer.mozilla.org/en-US/docs/Web/API/Storage/setItem)과 [Web Storage 표준](https://html.spec.whatwg.org/multipage/webstorage.html)을 참고. 여러 탭의 읽기·쓰기를 트랜잭션으로 보장한다고 주장하지 않음 |
| 노트 백업 | 날짜·내용만 허용 목록으로 내보내고 JSON 버전·형식·중복·16KB·10개 한도를 검사. 미리보기 뒤 현재 자료를 다시 읽어 병합 | 기존 리포트 백업과 같은 복구 흐름을 별도 단일 저장 키에 적용. 계정 필드·리포트·이전 초안은 포함하지 않음 |

`runtime_status=ready`는 llama-server가 모델 로딩 완료를 보고한 상태다. 실제 추론 성공, 선택한 모델 파일과 실행 중인 모델의 동일성, 코칭의 유용성을 보증하지 않는다. 기존 비양자화 연구 모델은 `worker_not_checked`로 표시하고 요청 시 작업자 실행을 검증한다.

## 참고한 스킬의 실제 적용

- [Ponytail](https://github.com/DietrichGebert/ponytail): 기존 검증기와 저장 키를 재사용하고 런타임 의존성을 추가하지 않았다.
- [Impeccable](https://github.com/pbakaus/impeccable): 기존 블랙·골드 테마를 유지하며 오류·빈 상태·취소·복구·모바일 줄바꿈에 집중했다.
- [Superpowers 완료 전 검증](https://github.com/obra/superpowers/tree/main/skills/verification-before-completion): 변경 여부와 테스트 성공을 구분하고 미확인 항목을 남겼다.
- [Anthropic 웹앱 테스트](https://github.com/anthropics/skills/tree/main/skills/webapp-testing): 기존 임시 서버·격리 컨텍스트·합성 데이터 흐름에 노트 백업·복원·손상 보존 검사를 추가했다. 프로젝트에 이미 있는 서버 생명주기 코드를 재사용했다.
- [Vercel 웹 인터페이스 지침](https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines): 삭제 취소, 명시적 레이블·접근성 이름, 상태 알림, 실패 시 입력 보존, 긴 내용 줄바꿈을 적용했다. React 전용 최적화는 이 프로젝트의 일반 JavaScript 화면에 적용하지 않았다.

스킬은 원저자·스타 수·실제 구성과 보조 파일을 확인해 선택했다. 스타 수는 인기도 지표이며 스킬 효과의 독립적인 검증 자료가 아니다.

## 검증 결과와 한계

Python 71개 검사가 통과했다. AI 확인은 모의 HTTP 전송으로 정상·로딩·이상 응답·시간 초과를 검증하며 프롬프트를 전송하지 않는 것도 확인한다. Redis 장애 검사는 실제 Riot 호출이 0회임을 확인하고 재설정 시 단일 프로세스 모드가 복구되는지 검사한다. 실제 다중 서버 부하·Redis Lua 운영 통합 검증과는 구분한다.

Redis 장애 검사는 기존 HEAD의 예약 메서드를 메모리에서만 대입했을 때 실패하고 현재 메서드에서는 통과하는 것도 확인했다. 이 과정에서 원본 파일을 되돌리거나 미커밋 작업을 변경하지 않았다. 임시 서버의 준비 상태 17개 항목은 필수 연결 실패 없이 `limited`였다. 오래된 메타 표본과 미연결 AI 서버를 실제 제한으로 표시했다.

JavaScript는 30개 검사가 통과했다. 행동 노트에 손상 원문 보존, 10개 초과 거부, 삭제 취소, 한국어 백업 왕복, 중복 병합, 저장 실패, 미리보기 뒤 변경을 추가했다. 기존 수동 복기와 리포트 검사를 함께 실행했다.

자동 브라우저 접근 호스트는 현재 사용할 수 없다. 기존 Playwright도 이 환경의 사용자 경로 접근 제한이 있어 새 화면의 모바일·전체 브라우저 검증을 완료하지 못했다. 노트·AI 재확인 화면 회귀 검사는 CI 스크립트에 추가했으며 실행 성공을 주장하지 않는다. Ruff·Mypy·커버리지·Docker 실행 검증도 앞선 환경 제한이 유지된다. 실제 계정 전적 수집이나 모델 추론·재학습·외부 배포를 실행하지 않았다.

## 다음 작업

1. 실행 가능한 환경에서 전체 브라우저 회귀, 정적 검사, 커버리지와 Docker 볼륨 검증을 확인한다.
2. 실제 Redis 두 워커 통합·장애 복구와 동시 요청 부하를 검증한다.
3. 자동 데이터 수집·갱신은 공식 API 요청 예산과 별도 실행 정책을 정한 뒤 추가한다.
4. 다중 사용자 로그인·인증과 서버 동기화 UI 연결은 별도 설계가 필요하다. 현재 로컬·사설망 경계와 `client_id` 구분은 로그인 인증을 대신하지 않는다.
