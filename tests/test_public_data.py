import csv
import json
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from service.main import app
from service.public_data import PHASES, build_flow, gold_bucket, read_phase, public_flow

FIELDS = ['matchID','fullTimeMS','timePercent','blueTotalGold','redTotalGold','blueWin','redWin']


def row(match='synthetic-1',phase=20,**updates):
    data=dict(matchID=match,fullTimeMS=1800000,timePercent=30*phase/100,
              blueTotalGold=10000*phase/20,redTotalGold=10000*phase/20-1000,
              blueWin='True',redWin='False')
    return {**data,**updates}


def write(path,rows):
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=FIELDS); writer.writeheader(); writer.writerows(rows)


class PublicDataTests(unittest.TestCase):
    def test_time_field_is_minutes_and_missing_invalid_values_are_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'phase.csv'
            write(path,[row(),row('bad-time',timePercent=20),row('missing',blueTotalGold=''),
                        row('nan',blueTotalGold='nan'),row('bad-win',redWin='True'),row('remake',fullTimeMS=120000)])
            records,audit=read_phase(path,20)
            self.assertEqual(list(records),['synthetic-1'])
            self.assertEqual(records['synthetic-1'][1],6)
            self.assertEqual(audit['invalid_rows'],5)
            self.assertEqual(audit['invalid_reasons']['frame_time_mismatch'],1)

    def test_identical_duplicate_is_coalesced_and_conflict_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'phase.csv'
            write(path,[row(),row(),row('conflict'),row('conflict',blueTotalGold=11000)])
            records,audit=read_phase(path,20)
            self.assertEqual(len(records),1)
            self.assertEqual(audit['duplicate_rows'],2)
            self.assertEqual(audit['conflicting_matches'],1)

    def test_frames_are_joined_by_match_and_not_counted_as_separate_games(self):
        with tempfile.TemporaryDirectory() as directory:
            files={}
            for phase in PHASES:
                path=Path(directory)/f'{phase}.csv'; files[phase]=path
                rows=[row(f'synthetic-{i}',phase,blueWin='True' if i%2 else 'False',redWin='False' if i%2 else 'True') for i in range(30)]
                # 누락 프레임·반대 결과·비단조 골드는 경기 전체를 제외한다.
                rows += [row('inconsistent',phase,redWin='True' if phase==100 else 'False',blueWin='False' if phase==100 else 'True'),
                         row('gold-decrease',phase,blueTotalGold=0 if phase==100 else 10000*phase/20)]
                if phase!=80:rows.append(row('missing-phase',phase))
                write(path,rows)
            result=build_flow(files)
            self.assertEqual(result['audit']['included_matches'],30)
            self.assertEqual(result['audit']['inconsistent_matches'],2)
            self.assertEqual([item['phase'] for item in result['phases']],[20,40,60,80])
            self.assertEqual(result['phases'][0]['buckets'][3]['n'],30)
            self.assertEqual(result['phases'][0]['buckets'][3]['blue_win_pct'],50)
            self.assertIsNone(result['phases'][0]['buckets'][0]['blue_win_pct'])
            self.assertNotIn('synthetic-',json.dumps(result))
            self.assertFalse(result['personal_comparison_eligible'])

    def test_bucket_boundaries_and_missing_schema(self):
        self.assertEqual([gold_bucket(v) for v in [-2001,-2000,-501,-500,500,501,2000,2001]],
                         ['large_deficit','deficit','deficit','balanced','balanced','lead','lead','large_lead'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad.csv'; path.write_text('value\n1\n',encoding='utf-8')
            with self.assertRaises(ValueError):read_phase(path,20)

    def test_shipped_aggregate_and_api_have_provenance_without_personal_identifiers(self):
        response=TestClient(app).get('/api/public-data')
        self.assertEqual(response.status_code,200)
        data=response.json(); flow=data['flow']
        self.assertEqual(flow,public_flow())
        self.assertEqual(flow['source']['license'],'CC BY 4.0')
        self.assertTrue(flow['source']['authors'])
        self.assertEqual(len(flow['source']['files']),5)
        self.assertFalse(flow['is_current_match_data'])
        self.assertFalse(flow['personal_comparison_eligible'])
        n=flow['audit']['included_matches']
        self.assertGreater(n,0)
        for phase in flow['phases']:
            self.assertLess(phase['phase'],100)
            self.assertEqual(phase['n'],n)
            self.assertEqual(sum(b['n'] for b in phase['buckets']),n)
        def keys(value):
            if isinstance(value,dict):
                for key,child in value.items():
                    yield key
                    yield from keys(child)
            elif isinstance(value,list):
                for child in value:
                    yield from keys(child)
        output_keys=set(keys(data))
        for forbidden in ['puuid','summonerName','riotIdGameName','matchID']:
            self.assertNotIn(forbidden,output_keys)
        # 제공자 출처·판단을 소실하지 않는다.
        self.assertEqual(len(data['sources']['items']),13)
        self.assertTrue(any(item['license']=='CC BY-NC 4.0' and '보류' in item['status'] for item in data['sources']['items']))
