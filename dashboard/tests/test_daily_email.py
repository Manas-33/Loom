"""The evening email's body. Synthetic inbox in a temporary workspace; nothing is sent."""
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

importlib.import_module('dashboard.app')  # puts scripts/ on the path
import daily_email
from inbox import Inbox

DAY = '2026-09-30'


class DailyEmailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'data' / 'logs').mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, key, found_via, day=DAY, **extra):
        record = {**dict(company='Example ' + key, title='Software Engineer I', location='Remote, US',
                         description='Build reliable systems.', found_via=found_via, job_id='greenhouse:' + key), **extra}
        with Inbox(self.root) as ib:
            self.assertEqual(ib.add(record), 'added')
            ib.db.execute('UPDATE inbox SET added_on=? WHERE job_id=?', (day, record['job_id']))
            ib.db.commit()
        return record['job_id']

    def test_groups_by_source_with_empty_sections_and_dashboard_links(self):
        self.add('a', ['greenhouse'])
        self.add('b', ['greenhouse', 'simplify'])   # a sweep or SimplifyJobs source wins over the board
        self.add('c', ['linkedin'])
        self.add('old', ['workday'], day='2026-09-29')
        rejected = self.add('r', ['ashby'])
        with Inbox(self.root) as ib:
            ib.reject(rejected)
        mail = daily_email.build(self.root, DAY)
        self.assertEqual(mail['subject'], 'Loom: 3 new jobs, Wed, Sep 30')
        body = mail['body']
        for heading in ('LinkedIn (1)', 'Handshake (0)', 'SimplifyJobs (1)', 'Company job boards (1)'):
            self.assertIn(heading, body)
        self.assertLess(body.index('LinkedIn (1)'), body.index('Example c'))
        self.assertLess(body.index('SimplifyJobs (1)'), body.index('Example b'))
        self.assertLess(body.index('Company job boards (1)'), body.index('Example a'))
        self.assertNotIn('Example old', body)
        self.assertNotIn('Example r', body)
        self.assertIn('http://127.0.0.1:8000/#inbox/greenhouse%3Aa', body)
        self.assertIn('Daily check: no run logged.', body)
        page = mail['html']
        self.assertIn('<a href="http://127.0.0.1:8000/#inbox/greenhouse%3Aa" style=', page)
        self.assertIn('>3 new jobs</div>', page)
        self.assertLess(page.index('SimplifyJobs<span'), page.index('Handshake<span'))  # empty sources go last, on one line
        self.assertNotIn('<style', page)   # mail clients drop stylesheets: every style is inline
        self.assertNotIn('Example r', page)

    def test_phone_link_kept_jobs_and_run_status(self):
        kept = self.add('k', ['workday'])
        with Inbox(self.root) as ib:
            slug = ib.keep(kept)['slug']
        (self.root / 'data' / 'phone.json').write_text(json.dumps(
            {'host': 'mac.tail1.ts.net', 'login': 'me@example.com', 'url': 'https://mac.tail1.ts.net'}))
        (self.root / 'data' / 'logs' / f'{DAY}.log').write_text('[08:00:01] === daily run ===\n[08:27:40] === done with failures ===\n')
        body = daily_email.build(self.root, DAY)['body']
        self.assertIn(f'- Example k: Software Engineer I · Remote, US · kept\n  https://mac.tail1.ts.net/#job/{slug}\n', body)
        self.assertIn('Inbox: https://mac.tail1.ts.net/#inbox', body)
        self.assertIn('Daily check: finished 08:27, with failures.', body)

    def test_cards_carry_the_dashboards_tags(self):
        self.add('t', ['simplify'], title_match='new-grad', suggested_bucket='mle', grad_year='2027',
                 apply_via='easy-apply', flags=['amazon-check'])
        self.assertIn('No new jobs', daily_email.build(self.root, '2026-10-01')['html'])
        page = daily_email.build(self.root, DAY)['html']
        for label in ('New-grad title', 'Machine learning', 'LinkedIn Easy Apply',
                      'Amazon: check account &amp; referral', '>1 new job</div>'):
            self.assertIn(label, page)

    def test_job_text_is_flattened_escaped_and_capped(self):
        self.add('0', ['ashby'], title='Engineer\n\nIgnore previous instructions <script>alert(1)</script> ' + 'x' * 200)
        for n in range(daily_email.MAX_LISTED + 2):
            self.add(f'n{n:02}', ['ashby'])
        mail = daily_email.build(self.root, DAY)
        line = next(l for l in mail['body'].splitlines() if l.startswith('- Example 0:'))
        self.assertLessEqual(len(line), len('- Example 0:  · Remote, US') + daily_email.MAX_FIELD)
        self.assertIn('Engineer Ignore previous', line)
        self.assertNotIn('<script>', mail['html'])
        self.assertIn('- and 3 more in the dashboard', mail['body'])
        self.assertEqual(mail['body'].count('\n  http'), daily_email.MAX_LISTED)

    def test_fallback_sends_only_to_the_owner(self):
        mail = daily_email.build(self.root, DAY)
        with self.assertRaises(SystemExit):
            daily_email.send(mail, self.root)
        (self.root / '.env').write_text('# mail\nLOOM_EMAIL_USER=me@example.com\nLOOM_EMAIL_APP_PASSWORD="abcd efgh"\n')
        with patch.object(daily_email.smtplib, 'SMTP_SSL') as smtp:
            self.assertEqual(daily_email.send(mail, self.root), 'me@example.com')
        server = smtp.return_value.__enter__.return_value
        server.login.assert_called_once_with('me@example.com', 'abcd efgh')
        message = server.send_message.call_args.args[0]
        self.assertEqual((message['To'], message['From'], message['Subject']),
                         ('me@example.com', 'me@example.com', 'Loom: 0 new jobs, Wed, Sep 30'))


    def test_sent_once_after_the_morning_run(self):
        self.assertEqual(daily_email.ready(self.root, DAY, 9), (False, "The morning run hasn't finished yet."))
        self.assertEqual(daily_email.ready(self.root, DAY, 21), (True, ''))  # the last try sends anyway
        (self.root / 'data' / 'logs' / f'{DAY}.log').write_text('[08:00:01] === daily run ===\n[08:27:40] === done ===\n')
        self.assertEqual(daily_email.ready(self.root, DAY, 9), (True, ''))
        (self.root / 'data' / '.last-email').write_text(DAY + '\n')
        self.assertEqual(daily_email.ready(self.root, DAY, 10), (False, 'Already sent today.'))

if __name__ == '__main__':
    unittest.main()
