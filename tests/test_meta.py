import copy
import unittest
from service.evidence import catalogue
from service.meta import aggregate, clean_game


def game():
    roles=['TOP','JUNGLE','MIDDLE','BOTTOM','UTILITY']
    champions=[266,64,103,81,12,86,254,7,236,89]
    return {'info':{'queueId':420,'platformId':'KR','gameDuration':1800,'gameEndTimestamp':1791158400000,
                    'gameVersion':'16.19.123.1','participants':[
                        {'puuid':'private-identity','championId':c,'teamId':100 if i<5 else 200,
                         'teamPosition':roles[i%5],'win':i<5} for i,c in enumerate(champions)],
                    'teams':[{'bans':[{'championId':-1} for _ in range(5)]},{'bans':[{'championId':-1} for _ in range(5)]}]}}


class MetaTests(unittest.TestCase):
    def test_clean_removes_identity_and_validates_complete_roles(self):
        clean=clean_game(game(),'16.19',catalogue())
        self.assertEqual(len(clean['rows']),10)
        self.assertNotIn('private',str(clean))
        self.assertTrue(clean['bans_known'])
        for field,value in [('queueId',440),('gameVersion','16.18.1'),('platformId','NA1'),('gameDuration',150)]:
            raw=game();raw['info'][field]=value
            self.assertIsNone(clean_game(raw,'16.19',catalogue()))
        raw=game();raw['info']['participants'][0]['teamPosition']='JUNGLE'
        self.assertIsNone(clean_game(raw,'16.19',catalogue()))
        raw=game();raw['info']['participants'][0]['win']=1
        self.assertIsNone(clean_game(raw,'16.19',catalogue()))

    def test_role_pick_denominator_and_small_sample_guard(self):
        clean=clean_game(game(),'16.19',catalogue())
        result=aggregate([copy.deepcopy(clean) for _ in range(30)],{'patch':'16.19'}, {})
        row=next(r for r in result['items'] if r['champion_id']=='Ezreal')
        self.assertEqual(result['games'],30)
        self.assertEqual(result['role_denominators']['BOT'],60)
        self.assertEqual(row['pick_rate'],50)
        self.assertEqual(row['win_rate'],100)
        self.assertEqual(row['ban_rate'],0)
        self.assertEqual(row['signal'],'positive')
        small=aggregate([clean],{'patch':'16.19'}, {})['items'][0]
        self.assertIsNone(small['win_rate']);self.assertIsNone(small['interval'])

    def test_unknown_bans_are_not_zero_filled(self):
        raw=game();raw['info']['teams']=[]
        result=aggregate([clean_game(raw,'16.19',catalogue())],{}, {})
        self.assertEqual(result['ban_denominator'],0)
        self.assertTrue(all(r['ban_rate'] is None for r in result['items']))
        raw['info']['teams']=None
        self.assertIsNotNone(clean_game(raw,'16.19',catalogue()))

    def test_stratified_seed_allocation_and_endpoints(self):
        import argparse
        import asyncio
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        import scripts.collect_riot_meta as collector
        from scripts.collect_riot_meta import TIERS, allocate_stratified_seeds, build_league_endpoint
        from service.evidence import ReviewSyncStore

        allocation = allocate_stratified_seeds(80, TIERS)
        self.assertEqual(len(allocation), 8)
        self.assertEqual(sum(allocation.values()), 80)
        self.assertTrue(all(count == 10 for count in allocation.values()))
        self.assertIn('/lol/league/v4/masterleagues/by-queue/', build_league_endpoint('RANKED_SOLO_5x5', 'MASTER', 'I'))
        self.assertIn('/lol/league/v4/grandmasterleagues/by-queue/', build_league_endpoint('GRANDMASTER'))
        self.assertIn('/lol/league/v4/challengerleagues/by-queue/', build_league_endpoint('CHALLENGER'))
        self.assertIn('/lol/league/v4/entries/RANKED_SOLO_5x5/GOLD/II', build_league_endpoint('RANKED_SOLO_5x5', 'GOLD', 'II'))

        seed_maps = {
            'IRON': {'puuid-iron-1': 50, 'puuid-iron-2': 30},
            'GOLD': {'puuid-gold-1': 80, 'puuid-gold-2': 40},
            'MASTER': {'puuid-master-1': 120},
        }
        interleaved = allocate_stratified_seeds(seed_maps, 4, ['IRON', 'GOLD', 'MASTER'])
        self.assertEqual(len(interleaved), 4)
        self.assertEqual([t for t, _ in interleaved[:3]], ['IRON', 'GOLD', 'MASTER'])

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            store = ReviewSyncStore(db_path=tmp_path / 'meta_test.db')
            clean = clean_game(game(), '16.19', catalogue())
            agg = aggregate([copy.deepcopy(clean) for _ in range(5)], {'patch': '16.19', 'region': 'KR'}, {'tiers': TIERS})
            snap_id = store.persist_meta_snapshot({**agg, 'generated_at': '2026-10-16T00:00:00+00:00'})
            self.assertTrue(snap_id)
            latest = store.latest_meta_snapshot()
            self.assertIsNotNone(latest)
            self.assertEqual(latest['patch'], '16.19')
            self.assertEqual(latest['games'], 5)

            # Test async collect() end-to-end with mocked RiotGateway.get
            patch_ver = '.'.join(catalogue()['version'].split('.')[:2])
            sample_match = game()
            sample_match['info']['gameVersion'] = f'{patch_ver}.123.1'

            async def fake_get(_self, _client, _host, path, _params=None):
                if 'masterleagues' in path:
                    return {'entries': [{'puuid': 'puuid-master-1', 'wins': 60, 'losses': 40}]}
                if '/lol/league/v4/entries/' in path:
                    return [{'puuid': 'puuid-gold-1', 'wins': 30, 'losses': 20}]
                if '/ids' in path:
                    return ['KR_100001']
                if '/lol/match/v5/matches/KR_100001' in path:
                    return sample_match
                return []

            args = argparse.Namespace(
                seeds=2,
                per_seed=1,
                matches=2,
                max_calls=20,
                days=7,
                delay=0.0,
                pages=1,
                tiers=['GOLD', 'MASTER'],
                fresh=True,
            )
            with (
                patch.object(collector, 'ROOT', tmp_path),
                patch.object(collector, 'review_store', store),
                patch.dict('os.environ', {'RIOT_API_KEY': 'RGAPI-test-key'}),
                patch('service.riot.RiotGateway.get', new=fake_get),
            ):
                report = asyncio.run(collector.collect(args))
                self.assertEqual(report['games'], 1)
                self.assertIn('snapshot_id', report)
                self.assertTrue((tmp_path / 'service/data/current_meta.json').exists())


if __name__ == '__main__':
    unittest.main()


