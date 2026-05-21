"""segment.py 의 PCA 산점도·역할 분포 heatmap PNG 만 재생성하는 보조 스크립트.

SQLite DB 없이 outputs/player_segments.csv 만으로 두 PNG 를 다시 그린다.
페르소나 라벨 텍스트 변경 같은 비-수치 수정 후 PNG 라벨만 빠르게 갱신할 때 사용.
(클러스터 자체를 다시 적합하는 건 아니며, 기존 cluster 컬럼을 그대로 사용한다.)

실행:
    python src/replot_personas.py
"""
from __future__ import annotations
from pathlib import Path
import sys

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

from sklearn.decomposition import PCA

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"
FEATURES = ["gpm", "dpm_champ", "vision_score", "kill_participation"]
RNG = 42


def main() -> None:
    df = pd.read_csv(OUT / "player_segments.csv", encoding="utf-8-sig")
    print(f"[load] player_segments.csv rows={len(df):,}")

    z_cols: list[str] = []
    for f in FEATURES:
        mean = df.groupby("role")[f].transform("mean")
        std = df.groupby("role")[f].transform("std").replace(0, np.nan)
        df[f"z_{f}"] = (df[f] - mean) / std
        z_cols.append(f"z_{f}")
    df = df.dropna(subset=z_cols).reset_index(drop=True)

    persona_map = (df.drop_duplicates("cluster")
                     .set_index("cluster")["persona"].to_dict())
    print(f"[persona] {persona_map}")

    # 1) PCA 2D
    X = df[z_cols].to_numpy()
    pca = PCA(n_components=2, random_state=RNG).fit(X)
    coords = pca.transform(X)
    labels = df["cluster"].to_numpy()
    rs = np.random.RandomState(RNG)
    if X.shape[0] > 8000:
        idx = rs.choice(X.shape[0], size=8000, replace=False)
        coords, labels = coords[idx], labels[idx]

    fig, ax = plt.subplots(figsize=(11, 8))
    cmap = plt.get_cmap("tab10")
    for cid in sorted(np.unique(labels)):
        m = labels == cid
        ax.scatter(coords[m, 0], coords[m, 1], s=8, alpha=0.45,
                   color=cmap(cid), label=f"C{cid}: {persona_map[cid]}")
    ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]:.1%})")
    ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]:.1%})")
    ax.set_title("플레이 스타일 클러스터 (PCA 2D)")
    ax.legend(loc="best", fontsize=9, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(OUT / "_clusters_pca_2d.png", dpi=130)
    plt.close(fig)
    print("[plot] _clusters_pca_2d.png")

    # 2) 클러스터 × 역할 heatmap
    pv = df.groupby(["cluster", "role"]).size().unstack(fill_value=0)
    pct = pv.div(pv.sum(axis=1), axis=0) * 100
    pct = pct[["TOP", "JUNGLE", "MID", "BOT", "SUPPORT"]]

    fig, ax = plt.subplots(figsize=(8, max(4, len(pct) * 0.7)))
    im = ax.imshow(pct.values, aspect="auto", cmap="Blues", vmin=0, vmax=100)
    ax.set_xticks(range(pct.shape[1])); ax.set_xticklabels(pct.columns)
    ax.set_yticks(range(pct.shape[0]))
    ax.set_yticklabels([f"C{c}: {persona_map[c]}" for c in pct.index])
    for i in range(pct.shape[0]):
        for j in range(pct.shape[1]):
            v = pct.values[i, j]
            ax.text(j, i, f"{v:.0f}%", ha="center", va="center",
                    color="white" if v > 50 else "black", fontsize=10)
    ax.set_title("클러스터 × 역할 비율 (행 합 100%)")
    fig.colorbar(im, ax=ax, label="% within cluster")
    fig.tight_layout()
    fig.savefig(OUT / "_cluster_role_heatmap.png", dpi=130)
    plt.close(fig)
    print("[plot] _cluster_role_heatmap.png")

    print("\n[done]")


if __name__ == "__main__":
    main()
