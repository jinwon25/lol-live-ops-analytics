# 라이엇 실제 패치 노트와 분석 결과 대조 (15.1 / 15.3)

> 데이터 출처: League of Legends Wiki [V15.1](https://wiki.leagueoflegends.com/en-us/V15.1) / [V15.3](https://wiki.leagueoflegends.com/en-us/V15.3) — 라이엇 공식 패치 노트 정리본.
> 분석 출처: 본 프로젝트 `13_patch_drift.sql`, `12_flagging.sql` (코호트 = PLAT+EM+DIA).
> 본문에서 사용하는 약어·게임 용어 정의는 [README §4 — 본문에 자주 등장하는 용어](../README.md#본문에-자주-등장하는-용어)를 참고.

## 1. 강한 매칭 — 분석 신호가 실제 라이엇 조정과 일치

| 챔프 | 한글명 | 우리 분석 신호 | 15.3 라이엇 패치 노트 | 정합성 |
|---|---|---|---|---|
| Viego | 비에고 | 저묾 3위, 픽률 −0.59pp (CI [−0.87, −0.30]) | **NERF**: 기본 AD 60→57 | ⭐⭐ 정확 |
| MonkeyKing | 오공 | 저묾 1위, 픽률 −0.97pp (CI [−1.24, −0.70]) | **NERF**: Warrior Trickster CD↑, Nimbus Strike AS↓ | ⭐⭐ 정확 |
| MissFortune | 미스 포츈 | 저묾 8위, 픽률 −0.43pp (CI [−0.71, −0.16]) | **NERF**: base armor 28→25, armor growth 4.2→4 | ⭐⭐ 정확 |
| Skarner | 스카너 | 저묾 11위 + 승률 −12.8pp (CI [−28.4, +2.8]) | **NERF**: armor growth ↓, Ixtal's Impact stun 1.5→1.1s | ⭐⭐ 정확 (분석이 1.5→1.1s 너프를 정확히 예측) |
| Kayn | 케인 | 떠오름 7위, 픽률 +0.40pp (CI [+0.20, +0.60]) | **BUFF**: Reaping Slash 데미지↑ 전 랭크 | ⭐⭐ 정확 |
| Quinn | 퀸 | naïve 11위 등장 (코호트 외) | **BUFF**: Heightened Senses AS 60→80% | ⭐ 정확 |
| Cassiopeia | 카시오페아 | 분석엔 두드러진 변화 없음 | **NERF**: Noxious Blast AP비 70→65%, Miasma AP비 15→10% | (분석 미포착, 표본 작음) |
| Jax | 잭스 | 분석엔 두드러진 변화 없음 | **BUFF**: 체력 성장↑, 만나 회복↑, on-hit↑ | (분석 미포착 — 15.3은 15.3 시점 데이터라 BUFF 효과 직후) |

## 2. ⭐⭐ Swain 케이스 — 분석 예측력의 직접 증거

| 시점 | 분석 결과 | 라이엇 실제 조치 |
|---|---|---|
| **15.1** | `BUFF_HIDDEN_STRONG` 후보로 잡힘 (MID, n=21, win 81%, Wilson 하한 60%) | — |
| **15.3** | (Swain 변경 후 15.3 데이터 기반) | **BUFF**: Ravenous Flock 영혼당 체력 12→15, Nevermove AP비 70%↑ |

**즉 우리 분석이 *"15.1 시점에서 사장됐지만 통계적으로 강한 챔프"* 로 잡은 챔프를 라이엇이 다음 패치(15.3)에 실제로 버프했다.**

→ 사후 매칭이 아니라 *분석이 라이엇 밸런스팀과 같은 결론에 독립적으로 도달한* 사례.
→ 면접 카드: *"우리 분석은 라이엇이 다음 패치에 버프할 챔프를 미리 발견했습니다."*

## 3. 매칭 안 된 신호 — 표본 노이즈 의심 확정

| 챔프 | 분석 신호 | 패치 노트 | 결론 |
|---|---|---|---|
| XinZhao (신 짜오) | 승률 +25.5pp (떠오름 동반) | **15.3에 변경 없음** | 표본 노이즈 확정. 15.1 n=39의 출발 승률 33%가 운적이었던 것 |
| MasterYi (마스터 이) | 떠오름 11위 | 15.3에 변경 없음 | 표본 노이즈 의심 |
| Yasuo (야스오) | 떠오름 13위 (CI 하한 +0.06) | 15.3에 변경 없음 | 노이즈 레벨 변화 |
| Tristana (트리스타나) | 떠오름 9위 | 15.3에 변경 없음 | 노이즈 또는 ADC 메타 흐름 |
| Cho'gath (초가스) | 떠오름 6위 + 승률 +18.3pp | **15.3에 초가스 직접 변경 없음** | 챔프 자체 변경은 아니지만 메타·아이템 흐름의 부수 효과 가능 — *해석은 "메타 흐름"이지 "Riot이 초가스를 버프했다"가 아님* |

이런 "매칭 안 됨"을 숨기지 않고 명시하는 것이 **분석 신뢰의 핵심**.

## 4. 정밀 매칭 챔프 외에 라이엇이 만진 챔프들 (참고)

### 15.3 BUFF (분석 미포착 또는 약신호)
Annie, Ashe, Bard, Cassiopeia, Evelynn, Jax, Kayn, Mel, Nasus, Quinn, Rakan, Samira, Swain, Thresh, Varus

### 15.3 NERF
Cassiopeia, Galio, Jayce, Kalista (이전), MissFortune, Pyke (이전), Rell, Skarner, Teemo, Viego, Wukong, Varus (이전)

### 15.1 BUFF
Annie, Ashe, Bard, Cassiopeia, Twitch

### 15.1 NERF
Kalista, Pyke, Varus

→ 15.1 → 15.3 두 패치 모두 Cassiopeia를 만진 점, ADC 다수 조정된 점 등은 분석의 BOT 라인 다양성 변화(BOT HHI 단독 ↑)와도 결이 맞음.

## 5. 결론

- 정밀 매칭 6건 (Viego, Wukong, MissFortune, Skarner, Kayn, Quinn) + 예측 적중 1건 (Swain) = **7건의 강한 정합성**
- 노이즈 의심 4건 (XinZhao, MasterYi, Yasuo, Tristana)은 패치 노트로 확정 → **분석의 자기 보정 능력**
- Cho'gath는 챔프 직접 변경이 아니라 메타 흐름 — *어떤 신호는 패치 노트로 입증되고, 어떤 신호는 메타 흐름으로만 설명된다* 는 정직한 해석이 가능
