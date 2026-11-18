import copy
import csv
import gzip
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from scripts.backfill_matches import COLUMNS, Crawler, participant_rows
from scripts.compare_backfill import compare
from service.riot import RiotError

POSITIONS = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY']


def match():
    ps = [
        {
            'participantId': i + 1,
            'puuid': f'p{i}',
            'teamId': 100 if i < 5 else 200,
            'teamPosition': POSITIONS[i % 5],
            'championId': i + 1,
            'championName': f'C{i}',
            'win': i < 5,
            'kills': 2,
            'deaths': 0 if i == 0 else 1,
            'assists': 3,
            'goldEarned': 12000,
            'goldSpent': 11000,
            'totalDamageDealt': 60000,
            'totalDamageDealtToChampions': 18000,
            'totalDamageTaken': 20000,
            'visionScore': 20,
            **{f'item{k}': 1000 + k for k in range(7)},
        }
        for i in range(10)
    ]
    teams = [{'teamId': t, 'objectives': {'champion': {'kills': 10}, 'dragon': {'kills': 2}}} for t in (100, 200)]
    return {
        'metadata': {'participants': [p['puuid'] for p in ps]},
        'info': {
            'gameId': 1,
            'queueId': 420,
            'gameDuration': 1800,
            'gameStartTimestamp': 1740000000000,
            'platformId': 'EUN1',
            'mapId': 11,
            'gameMode': 'CLASSIC',
            'gameVersion': '15.5.662.6652',
            'participants': ps,
            'teams': teams,
        },
    }


class BackfillRowsTest(unittest.TestCase):
    def test_rows_follow_original_schema_and_formulas(self):
        rows = participant_rows(match(), 'salt', 'EUN', 3, 2)
        self.assertEqual(len(rows), 10)
        self.assertEqual(set(rows[0]), set(COLUMNS))
        top = rows[0]
        self.assertEqual(top['kda_ratio'], 5.0)  # 사망 0은 1로 나눈다.
        self.assertEqual(top['kill_participation'], 0.5)  # (2+3) / 팀 킬 10
        self.assertEqual(top['gold_per_min'], 400.0)
        self.assertEqual(top['damage_per_min'], 2000.0)
        self.assertEqual(rows[4]['position'], 'SUPPORT')
        self.assertEqual(top['team_dragonKills'], 2)
        self.assertNotIn('p0', str(rows))  # PUUID 원문을 남기지 않는다.

    def test_rejects_other_queue_remake_and_missing_position(self):
        for mutate in (
            lambda m: m['info'].update(queueId=440),
            lambda m: m['info'].update(gameDuration=200),
            lambda m: m['info']['participants'][3].update(teamPosition=''),
            lambda m: m['info']['participants'][0].update(gameEndedInEarlySurrender=True),
        ):
            m = copy.deepcopy(match())
            mutate(m)
            self.assertIsNone(participant_rows(m, 'salt', 'EUN', 0, 0))


class BackfillResumeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.args = Namespace(
            region='EUN', out_dir=Path(tmp.name), start='2025-01-06', end='2025-03-03', bucket_days=7, rng_seed=25
        )
        crawler = Crawler(self.args)
        crawler.queried.add('previous-query')
        crawler.seen.add('previously-excluded')
        crawler.save()
        self.directory = crawler.dir
        sample = match()
        sample['metadata']['matchId'] = 'EUN1_1'
        with (self.directory / 'participants.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, COLUMNS)
            writer.writeheader()
            writer.writerows(participant_rows(sample, crawler.state['salt'], 'EUN', 3, 1))
        with gzip.open(self.directory / 'raw.jsonl.gz', 'wt', encoding='utf-8') as stream:
            stream.write(json.dumps(sample) + '\n')

    def test_resume_after_data_append_before_checkpoint(self):
        crawler = Crawler(self.args)
        self.assertEqual(crawler.recovered, 1)
        self.assertEqual(crawler.seen, {'EUN1_1', 'previously-excluded'})
        self.assertEqual(crawler.queried, {'previous-query'})
        self.assertEqual(crawler.counts, {'3': 1})
        self.assertEqual(crawler.patches, {'15.5': [1800]})
        crawler.save()
        self.assertEqual(Crawler(self.args).recovered, 0)

    def test_unpaired_or_partial_rows_block_resume(self):
        path = self.directory / 'raw.jsonl.gz'
        previous = path.read_bytes()
        with gzip.open(path, 'wt') as stream:
            stream.write('')
        with self.assertRaises(ValueError):
            Crawler(self.args)

        path.write_bytes(previous)
        csv_path = self.directory / 'participants.csv'
        lines = csv_path.read_bytes().splitlines(keepends=True)
        csv_path.write_bytes(b''.join(lines[:-1]))
        with self.assertRaises(ValueError):
            Crawler(self.args)

    def test_reimport_skips_saved_game_and_rejects_mismatched_response(self):
        crawler = Crawler(self.args)
        sample = match()
        sample['metadata']['matchId'] = 'EUN1_1'
        self.assertFalse(crawler.store_match('EUN1_1', sample, 0))
        with self.assertRaises(ValueError):
            crawler.store_match('EUN1_2', sample, 0)
        self.assertNotIn('EUN1_2', crawler.seen)
        self.assertEqual(crawler.counts, {'3': 1})


class BackfillComparisonTest(unittest.TestCase):
    def test_threshold_is_applied_to_each_region_within_patch_and_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            for region in ('EUN', 'KR'):
                args = Namespace(
                    region=region,
                    out_dir=Path(tmp),
                    start='2025-01-06',
                    end='2025-03-03',
                    bucket_days=7,
                    rng_seed=25,
                    per_bucket=500,
                )
                crawler = Crawler(args)
                for mid in range(1, 32):
                    game = match()
                    match_id = f'{crawler.prefix}_{mid}'
                    game['metadata']['matchId'] = match_id
                    info = game['info']
                    info.update(gameId=mid, platformId=crawler.prefix, gameDuration=1860 if region == 'EUN' else 1800)
                    if mid == 31:
                        info['gameVersion'] = '15.6.0'
                    if region == 'KR' and mid == 30:
                        info['participants'][0].update(championId=99, championName='C99')
                    self.assertTrue(crawler.store_match(match_id, game, 0))
                crawler.save()
            report = compare(Path(tmp))
        self.assertEqual(report['games'], {'EUN': 31, 'KR': 31})
        self.assertEqual(report['paired_patches'], 1)
        self.assertEqual(report['median_patch_difference_eun_minus_kr_seconds'], 60)
        items = report['paired_champion_positions']
        self.assertEqual({item['champion_id'] for item in items}, set(range(2, 11)))
        self.assertTrue(all(item['patch'] == '15.5' and item['KR']['picks'] == 30 for item in items))


class BackfillFailureTest(unittest.IsolatedAsyncioTestCase):
    async def test_until_complete_retries_and_publishes_last_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = Namespace(
                region='EUN',
                out_dir=Path(tmp),
                start='2025-02-17',
                end='2025-02-24',
                bucket_days=7,
                rng_seed=25,
                per_bucket=1,
                per_player=1,
                max_calls=None,
                delay=0,
                seed_ids=['EUN1_1'],
            )
            crawler = Crawler(args)
            game = match()
            game['metadata']['matchId'] = 'EUN1_1'
            replies = AsyncMock(side_effect=[RiotError(502, 'temporary failure'), game])
            with (
                patch.dict('os.environ', {'RIOT_API_KEY': 'test-token'}),
                patch('scripts.backfill_matches.RiotGateway.get', replies),
                patch('scripts.backfill_matches.asyncio.sleep', new_callable=AsyncMock),
            ):
                await crawler.run()
                await Crawler(args).run()
            self.assertEqual(replies.await_count, 2)
            self.assertTrue(Crawler(args).quota_met())
            args.end = '2025-03-03'
            unfinished = Crawler(args)
            unfinished.frontier.clear()
            with self.assertRaisesRegex(SystemExit, '1경기 부족'):
                await unfinished._loop()

    async def test_file_key_renewal_retries_with_updated_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = Namespace(
                region='KR',
                out_dir=Path(tmp),
                start='2025-01-06',
                end='2025-01-13',
                bucket_days=7,
                rng_seed=25,
                max_calls=None,
                delay=0,
            )
            crawler = Crawler(args)
            crawler.uses_file_key = True
            crawler.client = type('Client', (), {'headers': {'X-Riot-Token': 'expired'}})()
            crawler.gateway = AsyncMock()
            crawler.gateway.get.side_effect = [RiotError(403, 'expired'), []]
            with (
                patch(
                    'scripts.backfill_matches.dotenv_values',
                    side_effect=[{'RIOT_API_KEY': 'expired'}, {'RIOT_API_KEY': 'renewed'}],
                ),
                patch('scripts.backfill_matches.asyncio.sleep', new_callable=AsyncMock) as sleep,
            ):
                self.assertEqual(await crawler.fetch('/test'), [])
            sleep.assert_any_await(60)
            self.assertEqual(crawler.client.headers['X-Riot-Token'], 'renewed')

    async def test_interrupted_query_keeps_player_and_match_for_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = Namespace(
                region='KR',
                out_dir=Path(tmp),
                start='2025-01-06',
                end='2025-03-03',
                bucket_days=7,
                rng_seed=25,
                per_bucket=3,
                per_player=1,
                max_calls=5,
                delay=0,
            )
            crawler = Crawler(args)
            crawler.frontier['0'] = [['player', 2]]
            crawler.client = object()
            crawler.gateway = AsyncMock()
            crawler.gateway.get.side_effect = [['KR_1'], RiotError(403, 'forbidden')]
            with self.assertRaises(RiotError):
                await crawler._loop()
            crawler.save()
            resumed = Crawler(args)
            self.assertEqual(resumed.frontier['0'], [['player', 2]])
            self.assertEqual(resumed.queried, set())
            self.assertNotIn('KR_1', resumed.seen)


if __name__ == '__main__':
    unittest.main()
