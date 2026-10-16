import unittest

from service.match_report import match_report
from service.riot import normalize_match
from tests.test_riot import synthetic_match


class MatchReportTests(unittest.TestCase):
    def test_official_metrics_and_optional_unknowns(self):
        item = normalize_match(synthetic_match(), 'synthetic-self')
        report = match_report(item)
        self.assertEqual(report['metrics']['gpm'], 400)
        self.assertEqual(report['metrics']['dpm'], 700)
        self.assertEqual(report['metrics']['kill_participation'], .542)
        self.assertIsNone(report['metrics']['cs_per_minute'])
        self.assertIsNone(report['metrics']['damage_share'])
        self.assertIsNone(report['peer_percentile'])
        self.assertEqual(report['focus']['id'], 'resource')

    def test_cs_damage_share_and_deaths_are_official_not_invented(self):
        data = synthetic_match()
        data['info']['participants'][0].update(totalMinionsKilled=160, neutralMinionsKilled=20, deaths=4)
        data['info']['participants'][1]['totalDamageDealtToChampions'] = 29000
        item = normalize_match(data, 'synthetic-self')
        report = match_report(item)
        self.assertEqual(report['metrics']['cs_per_minute'], 6)
        self.assertEqual(report['metrics']['damage_share'], .42)
        self.assertIn('데스 4회', report['facts'][-1])
        data['info']['participants'][0]['totalMinionsKilled'] = True
        item = normalize_match(data, 'synthetic-self')
        self.assertIsNone(item['cs'])

    def test_zero_denominators_and_support_focus(self):
        item = normalize_match(synthetic_match(), 'synthetic-self')
        item.update(kills=0, assists=0, team_kills=0, team_damage=0, role='SUPPORT')
        report = match_report(item)
        self.assertIsNone(report['metrics']['kill_participation'])
        self.assertIsNone(report['metrics']['damage_share'])
        self.assertEqual(report['focus']['id'], 'vision')
        self.assertTrue(report['questions'])
