"""키·계정·원본 데이터 없이 재현하는 작은 합성 CSV·Excel 입력."""

from __future__ import annotations

import json
from pathlib import Path


def create_demo_inputs(directory: str | Path, games_per_patch: int = 32) -> Path:
    import pandas as pd

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    roles = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY']
    champions = ['Garen', 'LeeSin', 'Ahri', 'Jinx', 'Lulu', 'Darius', 'Viego', 'Orianna', 'Ezreal', 'Thresh']
    names = ['가렌', '리 신', '아리', '징크스', '룰루', '다리우스', '비에고', '오리아나', '이즈리얼', '쓰레쉬']
    for patch in ('15.1', '15.3'):
        rows = []
        for game in range(1, games_per_patch + 1):
            for player in range(10):
                win = int((player < 5) == (game % 2 == 0))
                rows.append(
                    {
                        'game_id': game,
                        'participant_id': player + 1,
                        'champion_name': champions[player],
                        'game_version': patch + '.1.1',
                        'win': win,
                        'kills': 3 + 2 * win,
                        'deaths': 5 - 2 * win,
                        'assists': 5,
                        'gold_earned': 10000 + 2000 * win,
                        'vision_score': 20,
                        'solo_tier': 'EMERALD',
                        **(
                            {
                                'duration': 1800,
                                'position': roles[player % 5],
                                'damage_to_champ': 20000,
                                'damage_taken': 15000,
                            }
                            if patch == '15.3'
                            else {
                                'game_duration': 1800,
                                'team_position': roles[player % 5],
                                'team_id': 100 if player < 5 else 200,
                                'queue_id': 420,
                                'total_damage_dealt_to_champions': 20000,
                                'total_damage_taken': 15000,
                            }
                        ),
                    }
                )
        frame = pd.DataFrame(rows)
        if patch == '15.3':
            frame.to_csv(directory / '2025.csv', index=False)
        else:
            frame.to_excel(directory / '2024.xlsx', sheet_name='league_data.csv', index=False)
    (directory / 'catalogue.json').write_text(
        json.dumps(
            {
                'version': '16.19.1',
                'is_synthetic': True,
                'champions': [{'id': c, 'name': n} for c, n in zip(champions, names, strict=True)],
            },
            ensure_ascii=False,
        )
        + '\n',
        encoding='utf-8',
    )
    return directory
