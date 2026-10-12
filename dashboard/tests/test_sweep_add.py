"""Sweep hand-over (scripts/sweep_add.py). Temporary workspace, no network."""
import contextlib
import importlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

importlib.import_module('dashboard.app')  # puts scripts/ on the path
import sweep_add
from add_job import InvalidJob
from inbox import Inbox

TODAY = date(2026, 9, 30)


def row(**extra):
    return {**dict(source='linkedin', url='https://www.linkedin.com/jobs/view/4432058132/', company='Acme',
                   title='Software Engineer, New Grad', location='Austin, TX', description='Build things.',
                   apply_url='', easy_apply=False, posted='3 days ago'), **extra}


class RecordTests(unittest.TestCase):
    def test_board_apply_link_is_unwrapped_and_names_the_job(self):
        rec = sweep_add.to_record(row(apply_url='https://www.linkedin.com/redir/redirect?url='
                                                'https%3A%2F%2Fjob-boards.greenhouse.io%2Facme%2Fjobs%2F7654321&urlhash=x'), TODAY)
        self.assertEqual(rec['apply_url'], 'https://job-boards.greenhouse.io/acme/jobs/7654321')
        self.assertEqual((rec['job_id'], rec['apply_via'], rec['_board']), ('greenhouse:7654321', 'greenhouse', 'greenhouse:acme'))
        self.assertEqual((rec['found_via'], rec['_posted_days'], rec['posted_time']), (['linkedin'], 3, '2026-09-27'))

    def test_easy_apply_and_handshake_only_are_tagged(self):
        easy = sweep_add.to_record(row(easy_apply=True, apply_url='https://www.linkedin.com/jobs/view/4432058132/apply'), TODAY)
        self.assertEqual((easy['apply_url'], easy['apply_via'], easy['job_id']), ('', 'easy-apply', 'linkedin:4432058132'))
        hs = sweep_add.to_record(row(source='handshake', url='https://app.joinhandshake.com/jobs/9876543', posted=''), TODAY)
        self.assertEqual((hs['apply_via'], hs['job_id'], hs['_posted_days'], hs['posted_time']), ('handshake', 'handshake:9876543', None, ''))
        self.assertEqual(sweep_add.to_record(row(), TODAY)['apply_via'], '')  # LinkedIn, no link recorded: unknown

    def test_rows_must_name_their_site_and_link_to_it(self):
        for bad in (row(source='indeed'), row(url='https://linkedin.com.evil.example/jobs/view/1234567'),
                    row(source='handshake'), 'not a row'):
            with self.assertRaises(InvalidJob):
                sweep_add.to_record(bad, TODAY)


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()
        self.boards = {'boards': {'greenhouse': {'known': {'sources': ['sheet'], 'status': 'ok'}}}}
        self.saved = []
        details = dict(description='The full posting from the board.', locations=['Austin, TX'], countries=[], url='', note='')
        self.patches = [
            patch.multiple(sweep_add, REPO_ROOT=self.root, CANDIDATES_DIR=self.root / 'data' / 'candidates',
                           open_db=lambda: sqlite3.connect(self.root / 'data' / 'loom.db'),
                           load_boards=lambda: self.boards, save_boards=self.saved.append,
                           probe=lambda ats, key: SimpleNamespace(status='ok', jobs=12, detail=''),
                           fetch_details=lambda url, job_id: dict(details)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def run_file(self, rows, *flags):
        path = self.root / 'sweep.jsonl'
        path.write_text('\n'.join(json.dumps(r) for r in rows) + '\nnot json\n')
        out = io.StringIO()
        with patch.object(sys, 'argv', ['sweep_add.py', str(path), *flags]), contextlib.redirect_stdout(out):
            self.assertEqual(sweep_add.main(), 0)
        files = list((self.root / 'data' / 'candidates').glob('*-sweep.jsonl')) if (self.root / 'data' / 'candidates').exists() else []
        return out.getvalue(), [json.loads(l) for f in files for l in f.read_text().splitlines()]

    def test_filters_merges_and_writes_candidates(self):
        with Inbox(self.root) as ib:
            ib.add(dict(company='Known Co', title='Software Engineer I', location='Remote, US', description='x',
                        found_via=['greenhouse'], job_id='greenhouse:111', url='https://job-boards.greenhouse.io/known/jobs/111'))
        rows = [
            row(easy_apply=True),
            row(url='https://www.linkedin.com/jobs/view/5000000001/', company='Newboard', title='Software Engineer I',
                apply_url='https://job-boards.greenhouse.io/newboard/jobs/222', description='copied text'),
            row(url='https://www.linkedin.com/jobs/view/5000000002/', company='Known Co', title='Software Engineer I',
                location='Remote, US', apply_url='https://job-boards.greenhouse.io/known/jobs/111'),
            row(url='https://www.linkedin.com/jobs/view/5000000003/', title='Senior Staff Software Engineer'),
            row(url='https://www.linkedin.com/jobs/view/5000000004/', location='Berlin, Germany'),
            row(url='https://www.linkedin.com/jobs/view/5000000005/', company='TikTok'),
            row(url='https://www.linkedin.com/jobs/view/5000000006/', posted='3 months ago'),
            row(easy_apply=True),  # the first row again
            row(source='glassdoor'),
        ]
        out, candidates = self.run_file(rows)
        self.assertEqual([c['job_id'] for c in candidates], ['linkedin:4432058132', 'greenhouse:222'])
        easy, board = candidates
        self.assertEqual((easy['apply_via'], easy['description'], easy['_title_class']), ('easy-apply', 'Build things.', 'clear'))
        self.assertEqual((board['description'], board['_board'], board['found_via']),
                         ('The full posting from the board.', 'greenhouse:newboard', ['linkedin']))
        with Inbox(self.root) as ib:
            self.assertEqual(ib.pending()[0]['record']['found_via'], ['greenhouse', 'linkedin'])
        self.assertEqual(self.boards['boards']['greenhouse']['newboard']['status'], 'ok')
        self.assertEqual(self.boards['boards']['greenhouse']['newboard']['sources'], ['sweep'])
        self.assertEqual(len(self.saved), 1)
        for line in ('already in the inbox', 'not in the US', 'TikTok/ByteDance', 'too old', 'twice in this sweep',
                     'invalid: source must be linkedin or handshake', "invalid: row isn't a JSON object",
                     'new company boards: greenhouse:newboard', '1 Easy Apply'):
            self.assertIn(line, out)

    def test_dry_run_saves_nothing(self):
        with Inbox(self.root) as ib:
            ib.add(dict(company='Known Co', title='Software Engineer I', location='Remote, US', description='x',
                        found_via=['greenhouse'], job_id='greenhouse:111', url='https://job-boards.greenhouse.io/known/jobs/111'))
        out, candidates = self.run_file([
            row(apply_url='https://job-boards.greenhouse.io/newboard/jobs/222'),
            row(url='https://www.linkedin.com/jobs/view/5000000002/', company='Known Co', title='Software Engineer I',
                location='Remote, US', apply_url='https://job-boards.greenhouse.io/known/jobs/111')], '--dry-run')
        self.assertEqual(candidates, [])
        self.assertEqual(self.saved, [])
        self.assertNotIn('newboard', self.boards['boards']['greenhouse'])
        with Inbox(self.root) as ib:
            self.assertEqual(ib.pending()[0]['record']['found_via'], ['greenhouse'])
        self.assertIn('dry run: nothing saved', out)


if __name__ == '__main__':
    unittest.main()
