from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import add_kr_names
import build_dashboard_csv
import champion_kr
import load
import run_meta
import run_validate
import segment


def _create_synthetic_raw_files(tmpdir: Path) -> tuple[Path, Path]:
    """Create synthetic P153 CSV and P151 Excel files for end-to-end pipeline testing."""
    roles = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
    champions = ["Ezreal", "Ahri", "LeeSin", "Garen", "Thresh", "Jinx", "Orianna", "Viego", "Darius", "Lulu"]

    p153_rows = []
    for game_idx in range(1, 9):
        for p_idx in range(10):
            win = 1 if p_idx < 5 else 0
            p153_rows.append(
                {
                    "game_id": 1000 + game_idx,
                    "duration": 1800,
                    "game_version": "15.3.656.4086",
                    "participant_id": p_idx + 1,
                    "champion_name": champions[p_idx],
                    "position": roles[p_idx % 5],
                    "win": win,
                    "kills": 6 if win else 2,
                    "deaths": 2 if win else 5,
                    "assists": 8 if win else 3,
                    "gold_earned": 12500 + p_idx * 300 if win else 9500 + p_idx * 200,
                    "damage_to_champ": 22000 + p_idx * 500 if win else 14000 + p_idx * 400,
                    "damage_taken": 18000,
                    "vision_score": 25 + (p_idx % 5) * 8,
                    "solo_tier": "DIAMOND" if game_idx % 2 == 0 else "EMERALD",
                }
            )
    # Add an non-target patch row and invalid role row to verify filtering
    p153_rows.append(
        {
            "game_id": 9999,
            "duration": 1800,
            "game_version": "15.2.100.1",
            "participant_id": 1,
            "champion_name": "Ezreal",
            "position": "BOTTOM",
            "win": 1,
            "kills": 1,
            "deaths": 1,
            "assists": 1,
            "gold_earned": 10000,
            "damage_to_champ": 10000,
            "damage_taken": 10000,
            "vision_score": 10,
            "solo_tier": None,
        }
    )

    p151_rows = []
    for game_idx in range(1, 9):
        for p_idx in range(10):
            win = 1 if p_idx < 5 else 0
            p151_rows.append(
                {
                    "game_id": 2000 + game_idx,
                    "game_duration": 1800,
                    "game_version": "15.1.500.1234",
                    "queue_id": 420,
                    "participant_id": p_idx + 1,
                    "champion_name": champions[p_idx],
                    "team_position": roles[p_idx % 5],
                    "win": win,
                    "team_id": 100 if p_idx < 5 else 200,
                    "kills": 5 if win else 3,
                    "deaths": 3 if win else 6,
                    "assists": 7 if win else 4,
                    "gold_earned": 11800 + p_idx * 250 if win else 9200 + p_idx * 150,
                    "total_damage_dealt_to_champions": 20000 + p_idx * 400 if win else 13500 + p_idx * 350,
                    "total_damage_taken": 17500,
                    "vision_score": 22 + (p_idx % 5) * 7,
                    "solo_tier": "PLATINUM",
                }
            )

    csv_path = tmpdir / "2025.csv"
    xlsx_path = tmpdir / "2024.xlsx"
    pd.DataFrame(p153_rows).to_csv(csv_path, index=False)
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        pd.DataFrame(p151_rows).to_excel(writer, sheet_name="league_data.csv", index=False)
    return csv_path, xlsx_path


class LoadAndSegmentTests(unittest.TestCase):
    def test_patch_from_version_and_derive_metrics(self):
        self.assertEqual(load.patch_from_version("15.3.656.4086"), "15.3")
        self.assertEqual(load.patch_from_version("14.24.1"), "14.24")
        self.assertIsNone(load.patch_from_version(None))
        self.assertIsNone(load.patch_from_version(np.nan))
        self.assertIsNone(load.patch_from_version("invalid"))

        sample_df = pd.DataFrame(
            [
                {
                    "patch": "15.3",
                    "game_id": 1,
                    "team_side": 100,
                    "kills": 5,
                    "deaths": 0,
                    "assists": 5,
                    "duration_sec": 1200,
                    "gold_earned": 10000,
                    "dmg_to_champ": 20000,
                },
                {
                    "patch": "15.3",
                    "game_id": 1,
                    "team_side": 100,
                    "kills": 5,
                    "deaths": 2,
                    "assists": 3,
                    "duration_sec": 1200,
                    "gold_earned": 8000,
                    "dmg_to_champ": 12000,
                },
                {
                    "patch": "15.3",
                    "game_id": 1,
                    "team_side": 200,
                    "kills": 0,
                    "deaths": 5,
                    "assists": 0,
                    "duration_sec": 1200,
                    "gold_earned": 6000,
                    "dmg_to_champ": 8000,
                },
            ]
        )
        derived = load.derive_metrics(sample_df)
        self.assertAlmostEqual(derived.loc[0, "kda"], 10.0)
        self.assertAlmostEqual(derived.loc[0, "gpm"], 500.0)
        self.assertAlmostEqual(derived.loc[0, "dpm_champ"], 1000.0)
        self.assertAlmostEqual(derived.loc[0, "kill_participation"], 1.0)
        self.assertTrue(pd.isna(derived.loc[2, "kill_participation"]))

    def test_os_font_detection_and_headless_fallback(self):
        self.assertEqual(
            segment.configure_matplotlib_font("Linux", {"NanumGothic", "DejaVu Sans"}),
            "NanumGothic",
        )
        self.assertEqual(
            segment.configure_matplotlib_font("Linux", {"Noto Sans CJK KR", "DejaVu Sans"}),
            "Noto Sans CJK KR",
        )
        self.assertEqual(
            segment.configure_matplotlib_font("Windows", {"Malgun Gothic", "DejaVu Sans"}),
            "Malgun Gothic",
        )
        self.assertEqual(
            segment.configure_matplotlib_font("Darwin", {"AppleGothic", "DejaVu Sans"}),
            "AppleGothic",
        )
        self.assertEqual(
            segment.configure_matplotlib_font("Linux", {"DejaVu Sans"}),
            "DejaVu Sans",
        )

    def test_label_personas_and_player_temporal_clustering(self):
        centroids = pd.DataFrame(
            [
                {"z_gpm": 1.2, "z_dpm_champ": 1.1, "z_vision_score": 0.1, "z_kill_participation": 0.5},
                {"z_gpm": -0.8, "z_dpm_champ": -0.9, "z_vision_score": -0.4, "z_kill_participation": -0.7},
                {"z_gpm": 0.0, "z_dpm_champ": 0.1, "z_vision_score": 1.2, "z_kill_participation": 0.2},
                {"z_gpm": 0.0, "z_dpm_champ": 0.0, "z_vision_score": 0.0, "z_kill_participation": 0.6},
                {"z_gpm": 0.4, "z_dpm_champ": 0.6, "z_vision_score": 0.0, "z_kill_participation": 0.1},
                {"z_gpm": 0.5, "z_dpm_champ": -0.1, "z_vision_score": 0.0, "z_kill_participation": -0.1},
                {"z_gpm": 0.05, "z_dpm_champ": -0.05, "z_vision_score": 0.1, "z_kill_participation": 0.0},
                {"z_gpm": -0.6, "z_dpm_champ": 0.5, "z_vision_score": -0.2, "z_kill_participation": 0.1},
            ]
        )
        labels = segment.label_personas(centroids)
        self.assertEqual(labels[0], "주도 캐리형")
        self.assertEqual(labels[1], "부진 위축형")
        self.assertEqual(labels[2], "시야 관리형")
        self.assertEqual(labels[3], "교전 집중형")
        self.assertEqual(labels[4], "솔로 공격형")
        self.assertEqual(labels[5], "자원 안정형")
        self.assertEqual(labels[6], "평균 균형형")
        self.assertTrue(labels[7].endswith("형"))

        # Verify player-level temporal feature engineering & clustering
        match_rows = []
        for player_idx in range(6):
            puuid = f"raw-player-{player_idx}"
            role = "BOT" if player_idx % 2 == 0 else "MID"
            for game_no in range(1, 5):
                match_rows.append(
                    {
                        "puuid": puuid,
                        "game_id": game_no,
                        "role": role,
                        "win": 1 if player_idx < 3 else 0,
                        "gpm": 420 + player_idx * 25 + game_no * 5,
                        "dpm_champ": 650 + player_idx * 40 + game_no * 10,
                        "vision_score": 18 + player_idx * 3 + game_no,
                        "kill_participation": 0.45 + player_idx * 0.04,
                    }
                )
        match_df = pd.DataFrame(match_rows)
        profiles, summary = segment.cluster_player_temporal_profiles(
            match_df,
            n_clusters=3,
            player_col="puuid",
            time_col="game_id",
            min_games=2,
        )
        self.assertEqual(len(profiles), 6)
        self.assertTrue(all(str(pid).startswith("anon_") for pid in profiles["anon_puuid"]))
        self.assertIn("z_gpm_mean", profiles.columns)
        self.assertIn("z_gpm_ewm", profiles.columns)
        self.assertIn("z_gpm_std", profiles.columns)
        self.assertIn("z_gpm_trend", profiles.columns)
        self.assertIn("persona", profiles.columns)
        self.assertEqual(len(summary), 3)

    def test_benjamini_hochberg_fdr_controls_false_positives(self):
        z_stats = np.array([3.8, 3.2, 1.97, 0.8, 0.2, np.nan])
        p_vals = run_meta.two_sided_normal_p_values(z_stats)
        q_vals, sig = run_meta.benjamini_hochberg_fdr(p_vals, alpha=0.05)

        self.assertTrue(sig[0])
        self.assertTrue(sig[1])
        # Nominal p ~ 0.0488 at rank 3 out of 5 tests has BH q-value = 0.0488 * (5/3) ~ 0.081 > 0.05
        self.assertFalse(sig[2])
        self.assertFalse(sig[3])
        self.assertFalse(sig[4])
        self.assertTrue(np.isnan(q_vals[5]))
        self.assertFalse(sig[5])

        drift_df = pd.DataFrame(
            {
                "champion_name": ["Ezreal", "Ahri", "Garen"],
                "pr_z_stat": [4.0, 1.97, 0.5],
                "wr_z_stat": [3.5, 1.2, np.nan],
            }
        )
        processed = run_meta.apply_fdr_postprocessing(drift_df, alpha=0.05)
        self.assertIn("pr_p_value", processed.columns)
        self.assertIn("pr_q_value", processed.columns)
        self.assertIn("pr_fdr_significant", processed.columns)
        self.assertIn("wr_q_value", processed.columns)
        self.assertTrue(processed.loc[0, "pr_fdr_significant"])
        self.assertFalse(processed.loc[1, "pr_fdr_significant"])

    def test_end_to_end_load_segment_meta_and_dashboard_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            csv_path, xlsx_path = _create_synthetic_raw_files(tmpdir)
            db_path = tmpdir / "lol.db"
            out_dir = tmpdir / "outputs"
            out_dir.mkdir(parents=True, exist_ok=True)

            # 1) Run load.main
            load.main(db_path=db_path, p153_path=csv_path, p151_path=xlsx_path)
            self.assertTrue(db_path.exists())

            # 2) Run segment.main
            segment.main(db_path=db_path, out_dir=out_dir, k_range=range(2, 5))
            self.assertTrue((out_dir / "player_segments.csv").exists())
            self.assertTrue((out_dir / "segment_centroids.csv").exists())
            self.assertTrue((out_dir / "player_temporal_segments.csv").exists())
            self.assertTrue((out_dir / "_clusters_pca_2d.png").exists())

            # 3) Run SQL meta queries + FDR post-processing
            with closing(sqlite3.connect(db_path)) as con, patch.object(run_meta, "OUT_DIR", out_dir):
                run_meta.run_sql_file(con, ROOT / "sql" / "05_views.sql")
                flag_res = run_meta.run_sql_file(
                    con,
                    ROOT / "sql" / "12_flagging.sql",
                    csv_map={"1": "12_flagging_cohort.csv", "2": "12_flagging_summary.csv"},
                )
                self.assertIn("wr_q_value", flag_res["1"].columns)
                drift_res = run_meta.run_sql_file(
                    con,
                    ROOT / "sql" / "13_patch_drift.sql",
                    csv_map={"1": "13_rising_champs_cohort.csv"},
                )
                self.assertIn("5", drift_res)

                # 4) Run build_dashboard_csv functions
                with patch.object(build_dashboard_csv, "OUT", out_dir):
                    build_dashboard_csv.ensure_views(con)
                    meta_df = build_dashboard_csv.build_champion_meta(con)
                    div_df = build_dashboard_csv.build_diversity(con)
                    pdrift_df = build_dashboard_csv.build_patch_drift(con)
                    self.assertFalse(meta_df.empty)
                    self.assertFalse(div_df.empty)
                    self.assertIn("pr_q_value", pdrift_df.columns)
                    build_dashboard_csv.clean_player_segments()
                    summary_df = build_dashboard_csv.build_segment_summary()
                    self.assertFalse(summary_df.empty)

            # 5) Test champion_kr, add_kr_names, run_validate, inspect_raw, replot_personas, sample_check
            import inspect_raw
            import replot_personas
            import sample_check

            self.assertEqual(champion_kr.to_kr("Ezreal"), "이즈리얼")
            self.assertEqual(champion_kr.to_kr("UnknownChamp"), "UnknownChamp")
            sample_csv = out_dir / "sample_champ.csv"
            pd.DataFrame({"champion_name": ["Ezreal", "Ahri"], "picks": [10, 20]}).to_csv(
                sample_csv, index=False, encoding="utf-8-sig"
            )
            with patch.object(add_kr_names, "OUT", out_dir):
                add_kr_names.main()
            self.assertTrue(add_kr_names.add_kr(sample_csv))

            with patch.object(run_validate, "DB", db_path):
                run_validate.main()

            with (
                patch.object(inspect_raw, "P153_PATH", csv_path),
                patch.object(inspect_raw, "P151_PATH", xlsx_path),
                patch.object(inspect_raw, "OUT_DIR", out_dir),
            ):
                inspect_raw.main()
            self.assertTrue((out_dir / "_inspect_p153.txt").exists())
            self.assertTrue((out_dir / "_inspect_p151.txt").exists())

            with patch.object(replot_personas, "OUT", out_dir):
                replot_personas.main()

            with patch.object(sample_check, "DB", db_path):
                sample_check.main()

            # 6) Test champion_details.abilities and additional service routes
            import asyncio

            from service import champion_details
            from service.main import app

            champion_details.cache.clear()
            unknown_res = asyncio.run(champion_details.abilities("NotAChamp"))
            self.assertFalse(unknown_res["available"])

            fake_dd_payload = {
                "data": {
                    "Ezreal": {
                        "title": "<b>무모한 탐험가</b>",
                        "passive": {
                            "name": "끓어오르는 주문의 힘",
                            "description": "공격 속도 증가",
                            "image": {"full": "Ezreal_Passive.png"},
                        },
                        "spells": [
                            {"name": "신비한 화살", "description": "화살 발사", "image": {"full": "EzrealQ.png"}},
                            {"name": "정수의 흐름", "description": "고리 발사", "image": {"full": "EzrealW.png"}},
                            {"name": "비전 이동", "description": "순간이동", "image": {"full": "EzrealE.png"}},
                            {"name": "정조준 일격", "description": "광역 궁극기", "image": {"full": "EzrealR.png"}},
                        ],
                        "allytips": ["팁1"],
                        "enemytips": ["적팁1"],
                    }
                }
            }

            class FakeResp:
                def raise_for_status(self):
                    return None

                def json(self):
                    return fake_dd_payload

            class FakeAsyncClient:
                def __init__(self, **_kwargs):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return False

                async def get(self, _url):
                    return FakeResp()

            with patch("service.champion_details.httpx.AsyncClient", FakeAsyncClient):
                ab_res = asyncio.run(champion_details.abilities("Ezreal"))
                self.assertTrue(ab_res["available"])
                self.assertEqual(len(ab_res["skills"]), 5)
                cached_res = asyncio.run(champion_details.abilities("Ezreal"))
                self.assertTrue(cached_res["available"])

            import httpx

            from service import evidence

            adapter = evidence.DuckDBAdapter(parquet_dir=tmpdir, sqlite_path=db_path)
            fallback_rows = adapter.query_parquet(
                tmpdir / "nonexistent.parquet",
                "SELECT champion_name, role FROM {parquet} WHERE champion_name = ?",
                ["Ezreal"],
            )
            self.assertTrue(len(fallback_rows) > 0)
            self.assertTrue(len(adapter.query_champion_history("Ezreal")) > 0)

            temp_store = evidence.ReviewSyncStore(db_path=tmpdir / "service_sync.db")
            snap_id = temp_store.persist_meta_snapshot(
                {
                    "scope": {"patch": "26.19", "region": "KR"},
                    "games": 100,
                    "participants": 1000,
                    "items": [
                        {
                            "champion_id": "Ezreal",
                            "role": "BOT",
                            "games": 40,
                            "wins": 22,
                            "win_rate": 55.0,
                            "pick_rate": 8.0,
                            "ban_rate": 4.0,
                            "signal": "observed",
                        }
                    ],
                }
            )
            self.assertTrue(bool(snap_id))
            self.assertEqual(temp_store.latest_meta_snapshot()["patch"], "26.19")

            async def _check_routes():
                transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
                with patch("service.main.review_store", temp_store):
                    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
                        self.assertEqual((await client.get("/")).status_code, 200)
                        self.assertEqual((await client.get("/api/overview")).status_code, 200)
                        self.assertEqual((await client.get("/api/champions?q=Ezreal")).status_code, 200)
                        self.assertEqual((await client.get("/api/champions/Ezreal")).status_code, 200)
                        self.assertEqual((await client.get("/api/riot/status")).status_code, 200)
                        self.assertEqual((await client.get("/api/riot/coach/status")).status_code, 200)
                        self.assertEqual((await client.get("/api/riot/preferences")).status_code, 200)
                        self.assertEqual((await client.get("/api/meta")).status_code, 200)
                        self.assertEqual((await client.get("/api/public-data")).status_code, 200)
                        self.assertEqual(
                            (
                                await client.post(
                                    "/api/review",
                                    json={
                                        "champion_id": "Ezreal",
                                        "role": "BOT",
                                        "duration_minutes": 28,
                                        "gold": 12500,
                                        "damage": 24000,
                                        "vision": 22,
                                        "kills": 8,
                                        "assists": 7,
                                        "team_kills": 25,
                                        "focus": "vision",
                                    },
                                )
                            ).status_code,
                            200,
                        )
                        sync_create = await client.post(
                            "/api/reviews/sync",
                            json={
                                "record_id": "rec_1",
                                "client_id": "c1",
                                "champion_id": "Ezreal",
                                "role": "BOT",
                                "patch": "26.19",
                                "focus": "vision",
                                "scene": "바론 앞 시야",
                                "action": "제어 와드 선설치",
                                "status": "planned",
                                "reflection": "좋았음",
                            },
                        )
                        self.assertEqual(sync_create.status_code, 201)
                        self.assertEqual((await client.get("/api/reviews/sync?client_id=c1")).status_code, 200)
                        self.assertEqual((await client.get("/api/reviews/sync/rec_1")).status_code, 200)
                        self.assertEqual(
                            (
                                await client.put(
                                    "/api/reviews/sync/rec_1",
                                    json={"client_id": "c1", "status": "kept", "reflection": "유지"},
                                )
                            ).status_code,
                            200,
                        )
                        self.assertEqual((await client.delete("/api/reviews/sync/rec_1?client_id=c1")).status_code, 200)
                        self.assertEqual(
                            (await client.post("/api/assistant", json={"question": "군집 유형 성향 알려줘"})).json()[
                                "status"
                            ],
                            "documented",
                        )
                        self.assertEqual(
                            (await client.post("/api/assistant", json={"question": "복기 시야 연습 질문"})).json()[
                                "status"
                            ],
                            "documented",
                        )
                        self.assertEqual(
                            (await client.post("/api/assistant", json={"question": "패치 15.3 메타 변화 요약"})).json()[
                                "status"
                            ],
                            "documented",
                        )
                        self.assertEqual(
                            (
                                await client.post(
                                    "/api/assistant",
                                    json={"question": "Ezreal 챔피언 지표 알려줘", "champion_id": "Ezreal"},
                                )
                            ).json()["status"],
                            "documented",
                        )

            asyncio.run(_check_routes())


if __name__ == "__main__":
    unittest.main()
