"""PHASE 3 — 플레이 스타일 세그멘테이션 (K-means).

설계 근거 (분석 결정 + 그 이유):
1. v_cohort(PLATINUM+EMERALD+DIAMOND)에서만 클러스터링.
   전체 풀로 돌리면 마스터>골드의 KDA/GPM 격차 때문에 클러스터가 그냥 "티어 사다리"를
   재현. 코호트로 좁히면 같은 실력대 안에서 "스타일이 어떻게 갈리나"가 드러남.

2. 식별자 puuid가 P153에 없음 → "플레이어" 군집화 대신 "플레이 스타일
   (게임 단위 행동 프로필)" 군집화. 데이터 한계를 정직하게 명시.

3. role을 어떻게 처리할지가 핵심 선택. 세 가지 옵션을 두고:
   (a) 원핫 + 전체 표준화 : role 더미가 z-score 큰 분산을 가져 결국 클러스터를 지배.
   (b) role 제거          : SUPPORT의 낮은 GPM 같은 구조적 차이를 무시하면 정보 손실.
   (c) **역할 내 z-score**: 각 (role) 그룹에서 평균/표준편차 계산해 표준화. SUPPORT는
       SUPPORT 평균 대비 위치만 사용 → "역할 안에서의 상대적 플레이 성향"이 클러스터링
       대상이 됨. 본 스크립트는 (c) 채택.

4. 피처 6종: kda, gpm, dpm_champ, vision_score, kill_participation, deaths.
   - 행동 지표만 사용(승패는 결과지표라 제외).
   - kill_participation NULL(팀킬 0인 경기) 행은 drop.

5. K 결정은 엘보우(inertia) + 실루엣 동시 확인. silhouette은 5000행 샘플에서.
"""
from __future__ import annotations
from pathlib import Path
import sqlite3
import sys

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
# 한글 폰트 (Windows)
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "processed" / "lol.db"
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)

RNG = 42

# ── 피처 선택의 분석가 판단 ────────────────────────────────────────────────
# 1차 시도에서 6피처(kda, gpm, dpm_champ, vision_score, kill_participation, deaths)로
# 돌렸더니 K=2 가 silhouette 최댓값이었고, 두 클러스터 승률이 75% vs 33% 로 갈림.
# 즉 군집화가 "플레이 스타일"이 아니라 "이긴 게임 vs 진 게임"으로 수렴.
#
# 원인: KDA = (k+a)/d, deaths = 죽음 횟수 — 둘 다 결과(win)와 강하게 상관된
# 결과 신호(outcome proxy). 이걸 입력으로 넣으면 K-means가 자연스럽게 win 축으로 갈림.
#
# 해결: 결과 신호 제외, "어떻게 플레이했는지"만 남는 프로세스 지표 4종으로 재군집화.
#   gpm                 : 분당 골드 획득(자원 운용)
#   dpm_champ           : 분당 챔프 대상 데미지(딜링 기여)
#   vision_score        : 시야 점수(맵 컨트롤)
#   kill_participation  : 킬 관여율(팀파이트 참여도)
# (kda 와 deaths 는 결과 지표로만 사용 — 사후 클러스터 해석에는 참고용으로 평균만 출력.)
FEATURES = ["gpm", "dpm_champ", "vision_score", "kill_participation"]
REFERENCE_METRICS = ["kda", "deaths"]  # 사후 클러스터 해석 참고용 (군집화 입력 X)


# ─────────────────────────── 데이터 ─────────────────────────────────────────

def load_cohort() -> pd.DataFrame:
    """v_cohort 의 참여 행 전부 로드 (PLAT+EM+DIA 양 패치)."""
    q = """
        SELECT
            patch, game_id, participant_id, champion_name, role, win,
            kills, deaths, assists, gold_earned, dmg_to_champ, vision_score,
            kda, gpm, dpm_champ, kill_participation
        FROM participants
        WHERE solo_tier IN ('PLATINUM', 'EMERALD', 'DIAMOND')
    """
    with sqlite3.connect(DB) as con:
        df = pd.read_sql_query(q, con)
    n0 = len(df)
    df = df.dropna(subset=FEATURES + REFERENCE_METRICS).reset_index(drop=True)
    print(f"[load] cohort rows={n0:,} → after dropna={len(df):,}")
    return df


def role_internal_z(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """역할 내 z-score: 각 role 그룹의 mean·std로 표준화. (c) 선택의 구현부."""
    z = pd.DataFrame(index=df.index)
    for f in features:
        mean = df.groupby("role")[f].transform("mean")
        std = df.groupby("role")[f].transform("std").replace(0, np.nan)
        z[f"z_{f}"] = (df[f] - mean) / std
    return z


# ─────────────────────────── K 선택 ─────────────────────────────────────────

def k_selection(X: np.ndarray, k_range=range(2, 9)) -> pd.DataFrame:
    """엘보우(inertia) + 실루엣. silhouette은 5000행 샘플로(O(n²) 회피)."""
    rs = np.random.RandomState(RNG)
    sample_idx = rs.choice(X.shape[0], size=min(5000, X.shape[0]), replace=False)
    X_sample = X[sample_idx]

    rows = []
    for k in k_range:
        km = KMeans(n_clusters=k, random_state=RNG, n_init=10)
        km.fit(X)
        labels_sample = km.predict(X_sample)
        sil = silhouette_score(X_sample, labels_sample)
        rows.append({"k": k, "inertia": km.inertia_, "silhouette": sil})
        print(f"  K={k}: inertia={km.inertia_:.0f}, silhouette={sil:.4f}")
    return pd.DataFrame(rows)


def plot_k_selection(stats: pd.DataFrame, out_path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].plot(stats["k"], stats["inertia"], marker="o", color="steelblue")
    axes[0].set_title("Elbow — inertia (↓)")
    axes[0].set_xlabel("K"); axes[0].set_ylabel("inertia")
    axes[1].plot(stats["k"], stats["silhouette"], marker="o", color="darkorange")
    axes[1].set_title("Silhouette (↑ better)")
    axes[1].set_xlabel("K"); axes[1].set_ylabel("score")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


# ─────────────────────────── 페르소나 명명 ──────────────────────────────────

def label_personas(centroid_z: pd.DataFrame) -> dict[int, str]:
    """클러스터 중심 z-score(프로세스 4지표) 기반 휴리스틱 라벨링.
    프로세스 피처: gpm, dpm_champ, vision_score, kill_participation.
    """
    names: dict[int, str] = {}
    for cid, r in centroid_z.iterrows():
        gpm = r["z_gpm"]; dpm = r["z_dpm_champ"]
        vis = r["z_vision_score"]; kp = r["z_kill_participation"]

        if gpm > 0.8 and dpm > 0.8:
            label = "슈퍼 캐리형"                     # 모든 자원·딜 폭주
        elif gpm < -0.5 and dpm < -0.5 and kp < -0.5:
            label = "위축·부진형"                     # 전반적 행동량 ↓ (패배 행동 프로필)
        elif vis > 0.8 and abs(dpm) < 0.3:
            label = "시야 컨트롤형"                   # 시야 점수만 두드러짐
        elif kp > 0.3 and dpm < 0.2 and vis < 0.3:
            label = "팀합세형"                        # 킬 가담은 높지만 메인 딜러 아님
        elif dpm > 0.4 and gpm > 0.2 and kp < 0.4:
            label = "공격적 솔로 라이너형"
        elif gpm > 0.3 and dpm < 0.1 and kp < 0.1:
            label = "안정 파밍형"
        elif all(abs(r[c]) < 0.3 for c in r.index):
            label = "평균 균형형"
        else:
            top2 = r.abs().sort_values(ascending=False).index[:2]
            tags = [f"{t.replace('z_', '')}{'↑' if r[t] > 0 else '↓'}" for t in top2]
            label = "·".join(tags) + "형"
        names[cid] = label
    return names


# ─────────────────────────── 시각화 ─────────────────────────────────────────

def plot_pca_2d(X: np.ndarray, labels: np.ndarray, names: dict[int, str],
                out_path: Path) -> None:
    pca = PCA(n_components=2, random_state=RNG).fit(X)
    coords = pca.transform(X)
    rs = np.random.RandomState(RNG)
    if X.shape[0] > 8000:
        idx = rs.choice(X.shape[0], size=8000, replace=False)
        coords, labels = coords[idx], labels[idx]

    fig, ax = plt.subplots(figsize=(11, 8))
    cmap = plt.get_cmap("tab10")
    for cid in sorted(np.unique(labels)):
        m = labels == cid
        ax.scatter(coords[m, 0], coords[m, 1], s=8, alpha=0.45,
                   color=cmap(cid), label=f"C{cid}: {names[cid]}")
    ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]:.1%})")
    ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]:.1%})")
    ax.set_title("플레이 스타일 클러스터 (PCA 2D)")
    ax.legend(loc="best", fontsize=9, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_cluster_role_heatmap(df: pd.DataFrame, names: dict[int, str],
                              out_path: Path) -> None:
    """각 클러스터의 role 비율. role-z 가 잘 작동하면 한 role 에 100% 쏠리지 않음."""
    pv = df.groupby(["cluster", "role"]).size().unstack(fill_value=0)
    pct = pv.div(pv.sum(axis=1), axis=0) * 100
    pct = pct[["TOP", "JUNGLE", "MID", "BOT", "SUPPORT"]]

    fig, ax = plt.subplots(figsize=(8, max(4, len(pct) * 0.7)))
    im = ax.imshow(pct.values, aspect="auto", cmap="Blues", vmin=0, vmax=100)
    ax.set_xticks(range(pct.shape[1])); ax.set_xticklabels(pct.columns)
    ax.set_yticks(range(pct.shape[0]))
    ax.set_yticklabels([f"C{c}: {names[c]}" for c in pct.index])
    for i in range(pct.shape[0]):
        for j in range(pct.shape[1]):
            v = pct.values[i, j]
            ax.text(j, i, f"{v:.0f}%", ha="center", va="center",
                    color="white" if v > 50 else "black", fontsize=10)
    ax.set_title("클러스터 × 역할 비율 (행 합 100%)")
    fig.colorbar(im, ax=ax, label="% within cluster")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


# ─────────────────────────── 메인 파이프라인 ────────────────────────────────

def main() -> None:
    df = load_cohort()
    print(f"[load] patches: {df['patch'].value_counts().to_dict()}")
    print(f"[load] roles  : {df['role'].value_counts().to_dict()}")

    print("\n[step] 역할 내 z-score 표준화")
    z = role_internal_z(df, FEATURES)
    df = pd.concat([df, z], axis=1)
    z_cols = [f"z_{f}" for f in FEATURES]
    X = df[z_cols].to_numpy()
    print(f"  z matrix shape = {X.shape}")

    print("\n[step] K 선택 (엘보우 + 실루엣)")
    k_stats = k_selection(X, range(2, 9))
    k_stats.to_csv(OUT / "_k_selection_stats.csv", index=False)
    plot_k_selection(k_stats, OUT / "_elbow_silhouette.png")
    # 분석가 판단: silhouette 최댓값에 더해 elbow 꺾임도 고려.
    # K=2 가 자명한 분리("이긴 게임 vs 진 게임")로 갈리지 않도록 프로세스 피처만 사용했음.
    # 그 후엔 silhouette 추이를 보고 K 결정.  silhouette 단조 감소면 elbow 꺾임 ≥ K=4 우선.
    K_best = int(k_stats.loc[k_stats["silhouette"].idxmax(), "k"])
    # 자명-분리 회피: K=2가 max라도 페르소나 다양성을 위해 inertia 감소율이 큰
    # 다음 후보로 격상.  prev/cur 감소율을 보고 "꺾임" 직전을 선택.
    inertia = k_stats["inertia"].to_numpy()
    drops = np.diff(inertia) / inertia[:-1]            # 음수, 작을수록 큰 감소
    # 감소율이 직전 1.5배 이내로 줄어드는 첫 K 를 elbow 로 본다.
    elbow_K = int(k_stats["k"].iloc[1])
    for i in range(1, len(drops)):
        if abs(drops[i]) < abs(drops[i - 1]) * 0.55:
            elbow_K = int(k_stats["k"].iloc[i + 1])
            break
    K = max(K_best, elbow_K, 4)                        # 최소 K=4 보장 (페르소나 다양성)
    print(f"  → silhouette max K = {K_best}, elbow K = {elbow_K}, 최종 K = {K}")

    print("\n[step] 최종 K-means 적합")
    km = KMeans(n_clusters=K, random_state=RNG, n_init=10).fit(X)
    df["cluster"] = km.labels_

    centroid_z = pd.DataFrame(km.cluster_centers_, columns=z_cols)
    print("\n[centroid z]")
    print(centroid_z.round(2).to_string())

    centroid_raw = df.groupby("cluster")[FEATURES].mean()
    print("\n[centroid raw means]")
    print(centroid_raw.round(2).to_string())

    persona = label_personas(centroid_z)
    df["persona"] = df["cluster"].map(persona)
    print(f"\n[persona] {persona}")

    # ── 산출 CSV ──────────────────────────────────────────────────────────
    print("\n[export] CSV")
    # 1) per-row 세그먼트
    seg_cols = ["patch", "game_id", "participant_id", "champion_name", "role",
                "win", "cluster", "persona"] + FEATURES
    df[seg_cols].to_csv(OUT / "player_segments.csv", index=False, encoding="utf-8-sig")

    # 2) 클러스터 요약(평균 + z + 비율)
    summary = centroid_raw.copy()
    summary.columns = [f"mean_{c}" for c in summary.columns]
    for c in z_cols:
        summary[c + "_centroid"] = centroid_z[c].values
    summary["n"] = df.groupby("cluster").size()
    summary["share_pct"] = (summary["n"] / len(df) * 100).round(2)
    summary["persona"] = pd.Series(persona)
    summary.to_csv(OUT / "segment_centroids.csv", encoding="utf-8-sig")
    print(f"  segment_centroids.csv\n{summary.round(3).to_string()}")

    # 3) 클러스터 × 역할 분포
    role_pv = df.groupby(["cluster", "role"]).size().unstack(fill_value=0)
    role_pct = (role_pv.div(role_pv.sum(axis=1), axis=0) * 100).round(2)
    role_pct["persona"] = pd.Series(persona)
    role_pct.to_csv(OUT / "segment_role_distribution.csv", encoding="utf-8-sig")
    print("\n  segment_role_distribution.csv (cluster × role, %)")
    print(role_pct.to_string())

    # 4) 패치별 클러스터 비율 (보너스)
    patch_pv = df.groupby(["patch", "cluster"]).size().unstack(fill_value=0)
    patch_pct = (patch_pv.div(patch_pv.sum(axis=1), axis=0) * 100).round(2)
    patch_pct.columns = [f"C{c}({persona[c]}) %" for c in patch_pct.columns]
    patch_pct.to_csv(OUT / "segment_patch_shift.csv", encoding="utf-8-sig")
    print("\n  segment_patch_shift.csv (patch → cluster %)")
    print(patch_pct.to_string())

    # 5) 클러스터 × 승률 (참고용, 군집화 입력은 아님)
    win_rate = (df.groupby("cluster")["win"].mean() * 100).round(2)
    win_rate.name = "win_rate_pct"
    print("\n[reference] cluster × win_rate_pct (군집화 입력 X)")
    print(win_rate.to_string())

    # ── 그림 ──────────────────────────────────────────────────────────────
    print("\n[plot] PCA 2D + role 분포 heatmap")
    plot_pca_2d(X, df["cluster"].to_numpy(), persona, OUT / "_clusters_pca_2d.png")
    plot_cluster_role_heatmap(df, persona, OUT / "_cluster_role_heatmap.png")

    print("\n[done]")


if __name__ == "__main__":
    main()
