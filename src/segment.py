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

from contextlib import closing
import hashlib
from pathlib import Path
import platform
import sqlite3
import sys

import matplotlib

matplotlib.use("Agg")
from matplotlib import font_manager
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score

OS_FONT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "Windows": ("Malgun Gothic", "NanumGothic", "DejaVu Sans"),
    "Linux": ("NanumGothic", "Noto Sans CJK KR", "UnDotum", "DejaVu Sans"),
    "Darwin": ("AppleGothic", "Apple SD Gothic Neo", "NanumGothic", "DejaVu Sans"),
}
HEADLESS_FALLBACK_FONT = "DejaVu Sans"
DEFAULT_EWM_SPAN = 5
ANON_HASH_PREFIX_LEN = 16


def configure_matplotlib_font(
    os_name: str | None = None,
    installed_fonts: set[str] | None = None,
) -> str:
    """Configure Matplotlib font family dynamically by OS and installed fonts with headless fallback."""
    detected_os = os_name or platform.system()
    available_fonts = (
        installed_fonts
        if installed_fonts is not None
        else {font_entry.name for font_entry in font_manager.fontManager.ttflist}
    )
    candidates = OS_FONT_CANDIDATES.get(detected_os, ("NanumGothic", HEADLESS_FALLBACK_FONT))
    selected_font = HEADLESS_FALLBACK_FONT
    for candidate in candidates:
        if candidate in available_fonts:
            selected_font = candidate
            break
    plt.rcParams["font.family"] = selected_font
    plt.rcParams["axes.unicode_minus"] = False
    return selected_font


configure_matplotlib_font()

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

def load_cohort(db_path: Path = DB) -> pd.DataFrame:
    """v_cohort 의 참여 행 전부 로드 (PLAT+EM+DIA 양 패치)."""
    q = """
        SELECT
            patch, game_id, participant_id, champion_name, role, win,
            kills, deaths, assists, gold_earned, dmg_to_champ, vision_score,
            kda, gpm, dpm_champ, kill_participation
        FROM participants
        WHERE solo_tier IN ('PLATINUM', 'EMERALD', 'DIAMOND')
    """
    with closing(sqlite3.connect(db_path)) as con:
        df = pd.read_sql_query(q, con)
    n0 = len(df)
    df = df.dropna(subset=FEATURES + REFERENCE_METRICS).reset_index(drop=True)
    print(f"[load] cohort rows={n0:,} → after dropna={len(df):,}")
    return df


def role_internal_z(df: pd.DataFrame, features: list[str] = FEATURES) -> pd.DataFrame:
    """역할 내 z-score: 각 role 그룹의 mean·std로 표준화. (c) 선택의 구현부."""
    z = pd.DataFrame(index=df.index)
    for f in features:
        mean = df.groupby("role")[f].transform("mean")
        std = df.groupby("role")[f].transform("std").replace(0, np.nan)
        z[f"z_{f}"] = ((df[f] - mean) / std).fillna(0.0)
    return z


def anonymize_puuid(raw_id: object) -> str:
    """Hash a raw player identifier (PUUID) into a deterministic anonymized key."""
    text = str(raw_id or "").strip()
    if text.startswith("anon_"):
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:ANON_HASH_PREFIX_LEN]
    return f"anon_{digest}"


def build_player_temporal_features(
    df: pd.DataFrame,
    player_col: str = "puuid",
    time_col: str = "game_id",
    features: list[str] = FEATURES,
    ewm_span: int = DEFAULT_EWM_SPAN,
    min_games: int = 1,
) -> pd.DataFrame:
    """Aggregate match snapshots into anonymized player-level temporal behavioral features.

    For each role-internal z-score feature (`z_gpm`, `z_dpm_champ`, `z_vision_score`, `z_kill_participation`),
    computes:
      - `z_<feat>_mean` : Cumulative mean across the player's match history
      - `z_<feat>_ewm`  : Exponentially weighted moving average (recent form)
      - `z_<feat>_std`  : Match-to-match standard deviation (consistency/volatility)
      - `z_<feat>_trend`: Temporal shift (`ewm - mean`)
    """
    if df.empty:
        return pd.DataFrame()

    working = df.copy()
    if player_col not in working.columns:
        fallback_col = "participant_id" if "participant_id" in working.columns else working.columns[0]
        working["anon_puuid"] = working[fallback_col].map(anonymize_puuid)
    else:
        working["anon_puuid"] = working[player_col].map(anonymize_puuid)

    z_cols = [f"z_{f}" for f in features]
    missing_z = [col for col in z_cols if col not in working.columns]
    if missing_z:
        z_df = role_internal_z(working, features)
        for col in z_cols:
            working[col] = z_df[col]

    sort_cols = ["anon_puuid"] + ([time_col] if time_col in working.columns else [])
    working = working.sort_values(sort_cols).reset_index(drop=True)

    records: list[dict[str, object]] = []
    for anon_id, group in working.groupby("anon_puuid", sort=False):
        n_games = len(group)
        if n_games < min_games:
            continue
        primary_role = (
            str(group["role"].mode().iloc[0])
            if "role" in group.columns and not group["role"].mode().empty
            else "UNKNOWN"
        )
        row_dict: dict[str, object] = {
            "anon_puuid": anon_id,
            "games_played": n_games,
            "primary_role": primary_role,
            "win_rate_pct": round(float(group["win"].mean() * 100.0), 2) if "win" in group.columns else np.nan,
        }
        for z_col in z_cols:
            series = group[z_col].astype(float)
            mean_val = float(series.mean())
            ewm_val = float(series.ewm(span=max(1, ewm_span), adjust=False).mean().iloc[-1])
            std_val = float(series.std(ddof=0)) if n_games > 1 else 0.0
            trend_val = ewm_val - mean_val
            row_dict[f"{z_col}_mean"] = round(mean_val, 4)
            row_dict[f"{z_col}_ewm"] = round(ewm_val, 4)
            row_dict[f"{z_col}_std"] = round(std_val, 4)
            row_dict[f"{z_col}_trend"] = round(trend_val, 4)
        records.append(row_dict)

    return pd.DataFrame(records)


def cluster_player_temporal_profiles(
    df: pd.DataFrame,
    n_clusters: int = 4,
    player_col: str = "puuid",
    time_col: str = "game_id",
    features: list[str] = FEATURES,
    ewm_span: int = DEFAULT_EWM_SPAN,
    min_games: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cluster anonymized player temporal profiles using cumulative mean, EWM, volatility, and trend."""
    profiles = build_player_temporal_features(
        df=df,
        player_col=player_col,
        time_col=time_col,
        features=features,
        ewm_span=ewm_span,
        min_games=min_games,
    )
    if profiles.empty:
        return profiles, pd.DataFrame()

    z_cols = [f"z_{f}" for f in features]
    temporal_cols = [
        f"{z_col}_{suffix}"
        for z_col in z_cols
        for suffix in ("mean", "ewm", "std", "trend")
    ]
    matrix = profiles[temporal_cols].to_numpy(dtype=float)
    effective_k = max(1, min(n_clusters, len(profiles)))

    km = KMeans(n_clusters=effective_k, random_state=RNG, n_init=10).fit(matrix)
    profiles["cluster"] = km.labels_

    mean_cols = [f"{z_col}_mean" for z_col in z_cols]
    centroid_means = profiles.groupby("cluster")[mean_cols].mean()
    centroid_for_labeling = centroid_means.rename(
        columns={f"{z_col}_mean": z_col for z_col in z_cols}
    )
    persona_map = label_personas(centroid_for_labeling)
    profiles["persona"] = profiles["cluster"].map(persona_map)

    centroid_summary = profiles.groupby("cluster")[temporal_cols].mean().round(4)
    centroid_summary["players"] = profiles.groupby("cluster").size()
    centroid_summary["persona"] = pd.Series(persona_map)
    return profiles, centroid_summary


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

    페르소나 명칭은 LoL 도메인 외 독자도 이해할 수 있도록 일반 어휘 위주로 정함.
    """
    names: dict[int, str] = {}
    for cid, r in centroid_z.iterrows():
        gpm = r["z_gpm"]; dpm = r["z_dpm_champ"]
        vis = r["z_vision_score"]; kp = r["z_kill_participation"]

        if gpm > 0.8 and dpm > 0.8:
            # 자원·딜·교전 기여가 모두 높은 주도적 플레이.
            label = "주도 캐리형"
        elif gpm < -0.5 and dpm < -0.5 and kp < -0.5:
            # 모든 행동 지표가 낮은 부진 게임 패턴.
            # "위축/부진"은 게임 결과에 대한 라벨이지 플레이어 낙인이 아님 — puuid 없이
            # 사람 추적이 불가한 본 데이터에서는 "이 게임에서 보인 패턴"의 의미.
            label = "부진 위축형"
        elif vis > 0.8 and abs(dpm) < 0.3:
            # 팀 시야 확보·정찰 활동량이 두드러짐.
            label = "시야 관리형"
        elif kp > 0.3 and dpm < 0.2 and vis < 0.3:
            # 교전 참여는 활발하지만 시야 활동은 낮은 공격형.
            label = "교전 집중형"
        elif dpm > 0.4 and gpm > 0.2 and kp < 0.4:
            label = "솔로 공격형"
        elif gpm > 0.3 and dpm < 0.1 and kp < 0.1:
            label = "자원 안정형"
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

def main(
    db_path: Path = DB,
    out_dir: Path = OUT,
    k_range: range = range(2, 9),
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    df = load_cohort(db_path=db_path)
    print(f"[load] patches: {df['patch'].value_counts().to_dict()}")
    print(f"[load] roles  : {df['role'].value_counts().to_dict()}")

    print("\n[step] 역할 내 z-score 표준화")
    z = role_internal_z(df, FEATURES)
    df = pd.concat([df, z], axis=1)
    z_cols = [f"z_{f}" for f in FEATURES]
    X = df[z_cols].to_numpy()
    print(f"  z matrix shape = {X.shape}")

    print("\n[step] K 선택 (엘보우 + 실루엣)")
    k_stats = k_selection(X, k_range)
    k_stats.to_csv(out_dir / "_k_selection_stats.csv", index=False)
    plot_k_selection(k_stats, out_dir / "_elbow_silhouette.png")
    K_best = int(k_stats.loc[k_stats["silhouette"].idxmax(), "k"])
    inertia = k_stats["inertia"].to_numpy()
    drops = np.diff(inertia) / inertia[:-1]
    elbow_K = int(k_stats["k"].iloc[min(1, len(k_stats) - 1)])
    for i in range(1, len(drops)):
        if abs(drops[i]) < abs(drops[i - 1]) * 0.55:
            elbow_K = int(k_stats["k"].iloc[i + 1])
            break
    K = min(max(K_best, elbow_K, 4), len(df))
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
    seg_cols = ["patch", "game_id", "participant_id", "champion_name", "role",
                "win", "cluster", "persona"] + FEATURES
    df[seg_cols].to_csv(out_dir / "player_segments.csv", index=False, encoding="utf-8-sig")

    summary = centroid_raw.copy()
    summary.columns = [f"mean_{c}" for c in summary.columns]
    for c in z_cols:
        summary[c + "_centroid"] = centroid_z[c].values
    summary["n"] = df.groupby("cluster").size()
    summary["share_pct"] = (summary["n"] / len(df) * 100).round(2)
    summary["persona"] = pd.Series(persona)
    summary.to_csv(out_dir / "segment_centroids.csv", encoding="utf-8-sig")
    print(f"  segment_centroids.csv\n{summary.round(3).to_string()}")

    role_pv = df.groupby(["cluster", "role"]).size().unstack(fill_value=0)
    role_pct = (role_pv.div(role_pv.sum(axis=1), axis=0) * 100).round(2)
    role_pct["persona"] = pd.Series(persona)
    role_pct.to_csv(out_dir / "segment_role_distribution.csv", encoding="utf-8-sig")
    print("\n  segment_role_distribution.csv (cluster × role, %)")
    print(role_pct.to_string())

    patch_pv = df.groupby(["patch", "cluster"]).size().unstack(fill_value=0)
    patch_pct = (patch_pv.div(patch_pv.sum(axis=1), axis=0) * 100).round(2)
    patch_pct.columns = [f"C{c}({persona[c]}) %" for c in patch_pct.columns]
    patch_pct.to_csv(out_dir / "segment_patch_shift.csv", encoding="utf-8-sig")
    print("\n  segment_patch_shift.csv (patch → cluster %)")
    print(patch_pct.to_string())

    win_rate = (df.groupby("cluster")["win"].mean() * 100).round(2)
    win_rate.name = "win_rate_pct"
    print("\n[reference] cluster × win_rate_pct (군집화 입력 X)")
    print(win_rate.to_string())

    print("\n[step] 유저 시계열 누적 성향 군집")
    temporal_profiles, temporal_centroids = cluster_player_temporal_profiles(
        df=df,
        n_clusters=K,
        player_col="puuid" if "puuid" in df.columns else "participant_id",
        time_col="game_id",
    )
    if not temporal_profiles.empty:
        temporal_profiles.to_csv(out_dir / "player_temporal_segments.csv", index=False, encoding="utf-8-sig")
        temporal_centroids.to_csv(out_dir / "player_temporal_centroids.csv", encoding="utf-8-sig")

    print("\n[plot] PCA 2D + role 분포 heatmap")
    plot_pca_2d(X, df["cluster"].to_numpy(), persona, out_dir / "_clusters_pca_2d.png")
    plot_cluster_role_heatmap(df, persona, out_dir / "_cluster_role_heatmap.png")

    print("\n[done]")


if __name__ == "__main__":  # pragma: no cover
    main()

