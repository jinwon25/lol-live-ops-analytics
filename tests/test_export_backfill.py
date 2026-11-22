import csv
import gzip
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import pandas as pd

from scripts.backfill_matches import COLUMNS, REGIONS
from scripts.export_backfill_pickle import final_export, watch_completion


class FinalExportTest(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.source = Path(tmp.name) / 'backfill'
        self.output = Path(tmp.name) / 'exports' / 'participants.pkl.gz'
        self.output.parent.mkdir()
        self.output.write_bytes(b'previous snapshot')
        for region, (_, _, prefix) in REGIONS.items():
            folder = self.source / region
            folder.mkdir(parents=True)
            mid = f'{prefix}_42'
            state = {'counts': {'0': 1}, 'seen': [mid]}
            (folder / 'state.json').write_text(json.dumps(state), encoding='utf-8')
            with (folder / 'participants.csv').open('w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, COLUMNS)
                writer.writeheader()
                for i in range(1, 11):
                    row = dict.fromkeys(COLUMNS, 0)
                    row.update(game_id=42, participant_id=i, region=region, platform_id=prefix, game_version='15.1.0')
                    writer.writerow(row)
            with gzip.open(folder / 'raw.jsonl.gz', 'wt', encoding='utf-8') as f:
                f.write(json.dumps({'metadata': {'matchId': mid}, 'info': {'gameId': 42}}) + '\n')

    def test_partial_region_or_active_writer_leaves_previous_snapshot(self):
        path = self.source / 'KR' / 'state.json'
        state = path.read_bytes()
        path.write_text('{"counts": {}}', encoding='utf-8')
        self.assertIsNone(final_export(self.source, self.output, weeks=1, per_week=1))
        path.write_bytes(state)
        with closing(sqlite3.connect(self.source / 'KR' / 'writer.sqlite')) as writer:
            writer.execute('BEGIN IMMEDIATE')
            self.assertIsNone(final_export(self.source, self.output, weeks=1, per_week=1))
        self.assertEqual(self.output.read_bytes(), b'previous snapshot')

    def test_corrupt_raw_blocks_publication(self):
        with gzip.open(self.source / 'KR' / 'raw.jsonl.gz', 'wt') as f:
            f.write('')
        with self.assertRaises(ValueError):
            final_export(self.source, self.output, weeks=1, per_week=1)
        self.assertEqual(self.output.read_bytes(), b'previous snapshot')

    def test_watcher_publishes_verified_snapshot_and_receipt(self):
        def publish_fixture(source, output, *, weeks, per_week):
            self.assertEqual((weeks, per_week), (97, 500))
            return final_export(source, output, weeks=1, per_week=1)

        with patch('scripts.export_backfill_pickle.final_export', side_effect=publish_fixture):
            watch_completion(self.source, self.output)
        frame = pd.read_pickle(self.output)
        self.assertEqual(frame.shape, (20, len(COLUMNS)))
        self.assertEqual(frame.groupby('region', observed=True).size().to_dict(), {'EUN': 10, 'KR': 10})
        receipt = json.loads((self.output.parent / 'backfill_export_status.json').read_bytes())
        self.assertEqual(
            (receipt['status'], receipt['rows'], receipt['bytes']), ('complete', 20, self.output.stat().st_size)
        )
