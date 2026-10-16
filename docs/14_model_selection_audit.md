# 공개 모델 비교 범위 재점검

2026-10-05 기준. 이전에 공개 LLM 전체를 실측한 것은 아니다. 초기 비교는 네 개의 작은 원본 모델, Qwen3-0.6B의 LoRA 실험, Qwen3-4B의 GGUF 구성에 한정됐다. 이 문서는 누락 후보와 비교 방식의 차이를 다시 확인한 기록이다. 모든 파생 모델·크기·양자화·샘플링 설정을 전수 시험했다고 표현하지 않는다.

## 프로젝트의 선정 조건

현재 장비는 RAM 약 16GB, Intel Iris Xe이며 NVIDIA CUDA GPU가 없다. Windows CPU 네 스레드에서 브라우저·서비스와 함께 사용할 구성을 검토한다. 한국어, 상용 이용 조건, 실제 사용 메모리, 지연 시간, 누락 지표 처리, 설치·운영 가능성을 따로 확인한다.

서비스가 현재 모델에 맡기는 일은 여섯 지표와 포지션으로 **검토할 질문의 초점을 선택하는 것**이다. 모델이 경기 수치를 계산하거나 장면·승패 원인·티어 백분위를 생성하지 않는다. 계산은 코드가 하고, 검증한 초점에 대응하는 한국어 질문은 등록한 문구에서 가져온다. 자유 서술 요약은 후보의 언어·사실 보존을 살피는 실험이며 사용자 리포트에 그대로 전달하지 않는다.

## 누락 후보를 포함한 17개 계열 검토

공개 가중치와 완전한 학습 데이터·코드 공개는 같은 의미가 아니다. 아래에는 공개 가중치 모델과 별도 이용 약관이 있는 모델도 포함한다. 계열 전체의 조건을 하나로 일반화하지 않고 링크의 **특정 버전**을 확인했다.

| 계열·확인 자료 | 프로젝트에서의 판단 | 실측 여부 |
|---|---|---|
| [Qwen3](https://huggingface.co/Qwen/Qwen3-4B), [Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507), [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B), [Qwen3.6](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) | Apache 2.0. 작은 원본·4비트 구성을 비교. 3.6의 27B·35B는 이번 16GB 장비의 여유 메모리 목표에 맞지 않아 실측 제외 | 0.6B·1.7B·3.5-0.8B FP32, 4B·2507·3.5-4B GGUF |
| [Gemma 4 공식 QAT GGUF](https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf), [모델 카드](https://ai.google.dev/gemma/docs/core/model_card_4) | Gemma 4는 Apache 2.0. E2B는 유효 2.3B이지만 PLE 포함 총 5.1B이므로 이름만으로 메모리를 판단하면 안 됨. Google 공식 QAT Q4_0 추가 | E2B QAT GGUF |
| [Phi-4 mini](https://huggingface.co/microsoft/Phi-4-mini-instruct), [mini Flash reasoning](https://huggingface.co/microsoft/Phi-4-mini-flash-reasoning) | mini Instruct는 MIT, 한국어 포함. Flash는 수학 추론 중심·별도 구조이므로 Instruct 실측을 Flash 실측으로 취급하지 않음 | mini Instruct Q4_K_M |
| [LFM2.5](https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct) | 공식 카드와 이용 조건을 초기 조사에서 확인. 작은 CPU 모델이지만 현재 프롬프트의 구조 검증과 한국어 표현에 문제가 있었음 | 1.2B FP32 |
| [Granite 4.0 H 1B](https://huggingface.co/ibm-granite/granite-4.0-h-1b), [공식 GGUF](https://huggingface.co/ibm-granite/granite-4.0-h-1b-GGUF) | Apache 2.0, 공식 한국어 지원. 작은 하이브리드 모델을 같은 CPU 런타임 비교에 추가 | H 1B Q4_K_M |
| [Kanana 1.5 2.1B](https://huggingface.co/kakaocorp/kanana-1.5-2.1b-instruct-2505), [개발사 발표](https://www.kakaocorp.com/page/detail/11654) | 특정 2505 버전은 Apache 2.0이며 한국어·영어 특화. 구 버전의 조건으로 일괄 제외하면 안 됨. 원본에 연결된 GGUF 변환 구성 추가 | 2.1B Q4_K_M |
| [HyperCLOVA X SEED 1.5B](https://huggingface.co/naver-hyperclovax/HyperCLOVAX-SEED-Text-Instruct-1.5B), [이용 약관](https://huggingface.co/naver-hyperclovax/HyperCLOVAX-SEED-Text-Instruct-1.5B/blob/main/LICENSE) | 한국어 유망 후보. 별도 약관과 gated 접근이 있어 자동 동의·로그인을 수행하지 않음. 상용 이용 가능 발표와 Apache 라이선스를 혼동하지 않음 | 문헌 검토, 미실측 |
| [EXAONE 4.5](https://github.com/LG-AI-EXAONE/EXAONE-4.5), [약관](https://github.com/LG-AI-EXAONE/EXAONE-4.5/blob/main/LICENSE), [K-EXAONE 2.0](https://github.com/LG-AI-EXAONE/K-EXAONE-2.0) | EXAONE 4.x의 NC 조건과 K-EXAONE 2.0의 Apache 2.0을 구분. 후자는 총 750B·활성 37B이므로 현재 로컬 장비 후보가 아님 | 문헌 검토, 미실측 |
| [SmolLM3-3B](https://huggingface.co/HuggingFaceTB/SmolLM3-3B) | Apache 2.0, 공개 학습 자료·레시피 장점. 카드 언어 목록에 한국어가 없어 한국어 특화 후보보다 실측 우선순위를 낮춤. 한국어 실행 불가라고 단정하지 않음 | 문헌 검토, 미실측 |
| [Ministral 3 3B](https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512) | 새 2512 버전은 Apache 2.0·한국어 포함. 구 Ministral의 조건과 구분. 비전 projector 없이 텍스트만 비교 | 3B Q4_K_M |
| [Llama 3.2 3B](https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct) | 별도 Llama 약관·gated 접근. 공식 지원 언어 목록에 한국어가 없음. 계정 동의 없이 가중치를 받지 않음 | 문헌 검토, 미실측 |
| [OLMo 3 7B Instruct](https://huggingface.co/allenai/Olmo-3-7B-Instruct) | Apache 2.0, 공개 학습 자료가 유리함. 7B도 양자화하면 검토할 수 있으므로 FP32 용량만으로 배제하지 않음. 이번에는 작은 한국어 후보부터 실측 | 문헌 검토, 미실측 |
| [Nemotron Nano 9B v2](https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2) | 한국어 포함, 별도 NVIDIA 모델 이용 조건. 9B 양자화 가능성과 GPU 지향 최적화·추론 비용을 구분. 현 구성에서는 작은 후보보다 후순위 | 문헌 검토, 미실측 |
| [DeepSeek V4 Flash/Pro](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash), [R1 Distill Qwen 1.5B](https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B) | V4는 MIT, 총 284B/1.6T로 로컬 후보 밖. 작은 R1 Distill은 별개로 실행 가능하나 긴 추론이 중심이라 64토큰의 짧은 초점 선택 비교에서 우선하지 않음 | 문헌 검토, 미실측 |
| [GLM-5.1](https://huggingface.co/zai-org/GLM-5.1) | MIT 공개 모델이지만 대규모 추론 구성이며 현 장비에서 실측하지 않음. 작은 GLM 파생 모델까지 실측했다는 의미가 아님 | 문헌 검토, 미실측 |
| [Kimi K2.5](https://huggingface.co/moonshotai/Kimi-K2.5) | Modified MIT, 총 1T·활성 32B. 활성 크기만 보고 32B 메모리라고 판단하면 안 됨 | 문헌 검토, 미실측 |
| [gpt-oss-20b](https://huggingface.co/openai/gpt-oss-20b) | Apache 2.0, 총 약 21B·활성 3.6B. 원본 MXFP4의 절감과 전체 장비의 OS·브라우저·KV 여유를 별도로 고려. 16GB에서 무조건 실행 불가라고 하지 않고 이번 여유 메모리 목표상 후순위 | 문헌 검토, 미실측 |

이 목록은 모든 공개 모델의 존재 목록이 아니다. 유망한 작은 모델을 빠뜨렸는지, 특정 계열의 오래된 약관으로 새 모델을 배제했는지, MoE 활성 파라미터나 FP32 용량만으로 잘못 배제했는지를 점검하는 후보 목록이다. 미실측 모델은 성능이 낮다고 판정하지 않았다.

## 초기 비교의 수정 사항

1. 작은 FP32와 4B GGUF의 속도·메모리 차이는 모델 크기뿐 아니라 런타임과 양자화가 섞인 결과였다. 이번 GGUF 후보들은 같은 llama.cpp b11398, CPU 4스레드, 컨텍스트 2,048에서 비교한다.
2. 초기 Transformers 한국어 요약 지시는 “모르는 정보는 덧붙이지 말라”였고 GGUF 지시는 “모르는 정보를 빠뜨리지 말라”였다. 이전 한국어 요약 결과를 동일 프롬프트의 직접 우열이라고 해석하면 안 된다. 이번 GGUF 비교는 모든 프롬프트 SHA256을 기록해 동일 여부를 대조한다.
3. greedy·비추론·짧은 출력은 현재 서비스 실행 조건이다. Qwen의 [권장 샘플링](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)은 다른 설정이며, 제약된 실행의 결과가 모델의 최대 일반 능력을 뜻하지 않는다.
4. 이전 8개 라우팅 사례의 다섯 포지션은 수치가 같았다. 형식·null 처리를 살필 수 있지만 복기 초점의 적합성이나 유료 코칭 품질을 증명하지 못한다. 별도 누락·극값·한국어 지시 실험도 같은 한계 안에서 해석한다.
5. 자동 한국어 검사는 특정 단어·수치의 존재만 검사한다. “계산 불가” 누락, 알 수 없는 티어 생략, 문장의 중단·인과 추정은 원문을 읽어 별도로 확인한다. Phi 출력의 목록 번호 `1.`·`2.`를 새 경기 수치로 감지한 사례처럼 자동 숫자 검사는 오탐도 있다. 이를 사실 환각으로 판정하지 않는다.

## 재현과 산출물

`scripts/quantized_candidates.py`에 원본 모델과 변환 작성자의 저장소를 따로 기록한다. Hugging Face revision과 원격 SHA256을 고정하며 다운로드 뒤 전체 파일 해시를 대조한다. 공식 Qwen·Google·IBM 파일과 Unsloth·bartowski·DevQuasar 변환을 구분한다. Phi·Kanana 변환 카드의 라이선스 메타데이터 누락은 원본 라이선스와 별개로 기록하고 공식 배포 파일이라고 부르지 않는다. 현재 비교 가중치와 런타임은 `.local/`에만 있고 공개 저장소에는 포함하지 않는다.

```powershell
python scripts/download_quantized_candidates.py --model Gemma4-E2B-QAT-Q4_0
python scripts/benchmark_quantized_model.py --model Gemma4-E2B-QAT-Q4_0 --audit
python scripts/summarize_model_benchmarks.py
python scripts/benchmark_coach_grounding.py --model Qwen3-4B-Q4_K_M
```

기본 실험은 모델 구성별 8개 라우팅+3개 한국어 요약이다. 로딩 시간과 11요청의 중앙값, llama-server의 peak working set을 기록한다. working set은 당시 프로세스의 관측값이며 전체 가중치 파일 용량이나 모든 입력에서의 최대 메모리 보장이 아니다. HTTP 요청 제한은 30초다. 원문·실패·프롬프트 해시는 `outputs/model-benchmark/*-audit.json`, 추가 근거 실험은 `outputs/model-grounding/`에 보관한다. 과거 결과를 덮어쓰지 않는다.

Gemma는 공식 QAT Q4_0이며 다른 후보의 Q4_K_M과 양자화 방식까지 동일하지 않다. 따라서 비교 단위는 “모델과 실행 구성”이다. 한 번의 노트북 실행이며 열·백그라운드 작업·파일 캐시가 통제된 연구실 다회 실험은 아니다.

Kanana 변환 구성은 공식 tokenizer의 `<|eot_id|>`가 응답 본문에 노출됐다. 해당 문자열을 검증기에서 임의로 잘라 통과시키지 않고, 런타임의 종료 조건으로 지정해 재검증했다. 원래 측정과 종료 조건 보정 측정을 따로 보관한다. 보정 후 6/8을 통과했고, 남은 두 실패는 지표 이름을 `focus_id`로 생성한 문제였다. 종료 조건과 모델 출력 오류를 구분한다.

## 실제 비교 결과

12개 원본 버전의 14개 실행 구성을 비교했다. 4개 FP32, 1개 LoRA, 8개 GGUF에 Kanana 종료 조건 보정 구성을 추가한 수다. 이전 Qwen3-4B 실행을 재측정한 기록까지 포함하면 기본 평가 파일은 15개지만, 재측정을 별도 모델로 세지 않는다. 아래 표는 이번의 동일 프롬프트 GGUF 비교다.

| 실행 구성 | 원문 검증 / 정확한 코드펜스 정규화 후 검증 | 로딩(초) | 11요청 중앙값(초) | 프로세스 peak working set(GiB) |
|---|---:|---:|---:|---:|
| Granite 4.0 H 1B Q4_K_M | 8/8 · 8/8 | 2.45 | 3.563 | 2.694 |
| Kanana 1.5 2.1B Q4_K_M | 0/8 · 0/8 | 3.19 | 5.594 | 2.447 |
| Kanana 위 구성 + 종료 조건 보정 | 6/8 · 6/8 | 4.77 | 6.000 | 2.446 |
| Gemma 4 E2B QAT Q4_0 | 0/8 · 8/8 | 5.26 | 6.156 | 2.506 |
| Phi-4 mini Q4_K_M | 0/8 · 8/8 | 4.36 | 6.844 | 3.974 |
| Ministral 3 3B Q4_K_M | 0/8 · 8/8 | 5.67 | 7.719 | 3.765 |
| **Qwen3 4B Q4_K_M** | **8/8 · 8/8** | **6.76** | **8.453** | **4.443** |
| Qwen3 4B Instruct-2507 Q4_K_M | 8/8 · 8/8 | 7.78 | 8.765 | 4.477 |
| Qwen3.5 4B Q4_K_M | 8/8 · 8/8 | 7.02 | 9.719 | 4.663 |

원문 검증은 JSON 구문만의 성공률이 아니다. 허용된 초점·1~2개 근거·누락되지 않은 실제 지표 이름까지 통과한 수다. Gemma·Phi·Ministral은 정확한 JSON 코드펜스를 반환했고, 이를 제거하는 기존 검증 규칙으로 8/8을 통과했다. 작은 표본의 8/8을 안정성 보장이나 모델 순위로 해석하지 않는다. 중앙값에는 한국어 요약도 섞여 있고 로딩 시간은 별도다. 예를 들어 Qwen3 4B는 사용자가 요청할 때 새 프로세스를 시작하므로 체감 대기에 로딩이 더해진다.

초기 FP32/LoRA 기록은 비교 조건이 달라 별도로 제시한다.

| 이전 실행 구성 | 정규화 후 검증 | 11요청 중앙값(초) | peak working set(GiB) |
|---|---:|---:|---:|
| Qwen3 0.6B FP32 | 8/8 | 9.468 | 3.325 |
| Qwen3 1.7B FP32 | 8/8 | 15.109 | 6.516 |
| Qwen3.5 0.8B FP32 | 6/8 | 12.093 | 3.819 |
| LFM2.5 1.2B FP32 | 0/8 | 14.156 | 4.849 |
| Qwen3 0.6B FP32 + LoRA | 8/8 | 5.531 | 3.337 |

### 한국어 원문에서 확인한 차이

| 후보 | 세 개 요약 원문에서 확인한 내용 |
|---|---|
| Qwen3 4B · Instruct-2507 · Qwen3.5 4B | 입력 수치, 팀 킬 0일 때 계산 불가, 경기 당시 티어 미확인 조건을 보존했다. Qwen3 4B의 일반 요약은 요청한 두 문장 대신 한 문장이었다. |
| Granite | 응답은 빠르지만 분당 골드 400과 계산 불가 조건을 생략했고 비교 요약이 문장 중간에서 끝났다. |
| Gemma 4 | 일반·누락 요약은 사실을 보존했다. 비교 요약은 차이 25만 남겨 375·400과 티어 미확인 조건을 생략했다. |
| Phi-4 mini | 일반 요약에서 획득 골드 12,000을 생략했다. 누락·비교 요약은 조건을 보존했다. 목록 번호를 경기 수치로 판단한 자동 검사의 오탐은 수치 날조로 취급하지 않았다. |
| Kanana 종료 보정 | 일반·누락 요약은 사실을 보존했다. 비교 요약에서 분당 단위와 티어 미확인 조건이 사라졌다. |
| Ministral 3 | 분당 골드 400을 4,000으로 바꿨고, 입력에 없는 0:0 무승부와 양 팀의 킬·도움 정보를 생성했다. 자유 요약에는 쓰지 않는다. |

이는 세 문장의 관찰 기록이며 한국어 능력 전체를 평가한 점수가 아니다. 자동 검사 결과만으로 사실 보존을 판정하지 않았다. 실제 서비스는 어느 후보의 자유 요약도 바로 사용자에게 전달하지 않는다.

## 추가 근거 검증과 조건부 선정

누락·0·극값과 영어/한국어 지시를 바꾼 12개 입력을 **8개 GGUF 후보 모두에 적용해 96건**을 추가 비교했다. Kanana는 종료 조건을 보정한 구성이다. 결과 원문과 입력·프롬프트 해시는 `outputs/model-grounding/`에 남겼다. 지표가 존재하는지와 출력 형식의 검증이며, 최적의 복기 초점을 맞혔다는 정답률이 아니다. 한국어 지시는 별도 작성한 문구이므로 언어만의 효과를 분리한 실험으로 해석하지 않는다.

| 후보 | 형식·존재하는 근거 검증 | 추가 12요청 중앙값(초) | 유효 출력의 초점 분포 |
|---|---:|---:|---|
| Granite 4.0 H 1B | 11/12 | 4.109 | 시야 11 |
| Kanana 1.5 2.1B 종료 보정 | 11/12 | 4.946 | 시야 7 · 매치업 3 · 교전 1 |
| Gemma 4 E2B QAT | 12/12 | 6.055 | 시야 8 · 자원 4 |
| Phi-4 mini | 12/12 | 6.976 | 시야 12 |
| Qwen3 4B | 12/12 | 7.500 | 시야 12 |
| Ministral 3 3B | 11/12 | 7.532 | 시야 11 |
| Qwen3 4B Instruct-2507 | 12/12 | 7.805 | 시야 12 |
| Qwen3.5 4B | 12/12 | 9.226 | 시야 12 |

Granite의 모든 값 0 입력과 Kanana의 관여율 누락 입력에서 세 개 근거를 반환해 제한을 벗어났다. Ministral의 모든 값 0 입력은 제공하지 않은 `vision_time`·`vision_score`를 근거로 만들었다. 이 출력은 실제 서비스 검증기로 차단된다.

Qwen 세 후보와 Phi는 이 다양한 입력에서도 모두 시야를 골랐다. 형식이 정확하다는 사실만으로 입력에 맞는 좋은 초점을 선택한다고 볼 수 없다. Gemma의 다른 선택이나 Kanana의 분포가 더 좋은 코칭이라는 평가도 전문가 정답 없이 하지 않는다. 기본 비교 9회 실행의 11개 프롬프트 해시가 모두 동일하다는 결과는 `outputs/model-benchmark/summary.json`의 `audit_prompt_hashes_identical`로 재확인했다.

현재 기본값은 공식 배포 파일을 사용하는 **Qwen3-4B Q4_K_M + llama.cpp**다. 이번 작은 표본에서 수치와 모르는 조건을 보존했고 추가 구조 검증 12/12을 통과했지만, 시야를 반복 선택하는 한계도 확인했다. 새 Qwen 후보를 도입해야 할 확실한 품질 우위는 확인되지 않았다. 속도만 우선하면 Granite가 유리하지만 추가 구조 검증 실패가 있었고, Kanana는 종료 조건을 맞춰도 허용하지 않은 초점을 반환했다. 공식 파일의 출처와 기존 운영 검증도 선택 근거다. Qwen 최신 후보보다 일반 성능이 높거나 모든 공개 모델 중 최적이라는 결론은 아니다.

**Gemma 4 E2B는 낮은 메모리·지연의 유망한 대안**이다. 추가 구조 검증 12/12과 공식 QAT 배포 파일이라는 장점이 있다. 별도 요약 과제에서 비교 수치와 미확인 조건의 누락이 있어 곧바로 자유 분석 리포트에 연결하지 않았다. 현재 서비스의 초점 선택에 한정하면 더 빠른 대안일 수 있으므로, 전문가 초점 라벨을 갖춘 평가 없이 Qwen이 Gemma보다 우수하다고 결론 내리지 않는다. 기존 기본값의 유지는 운영상의 조건부 결정이며 경쟁 후보에 대한 확정 순위가 아니다.

가중치·런타임은 로컬에 준비돼 있으며 서비스의 복기 제안에 연결했다. 초점 선택은 검증 후 등록된 한국어 질문으로 변환하고, 실패해도 기본 리포트를 유지한다. 계정·장면·원본 전적은 모델에 보내지 않는다. 전문가가 검토한 경기별 라벨, 타임라인 근거, 다양한 실제 경기의 평가 없이 자유 생성 유료 코칭 수준을 주장하지 않는다.

초기 LoRA는 Qwen3-0.6B 전용의 합성 소규모 실험이다. 다른 모델까지 파인튜닝한 결과가 아니며 선정한 4B 모델에 그 어댑터를 붙이지 않는다. 형식 학습과 코칭 품질 향상을 구분하고, 상세 데이터·학습 분할·검증 한계는 [초기 실험 기록](13_local_llm_research.md)에 남겼다.
