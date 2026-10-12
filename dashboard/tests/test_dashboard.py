"""Dashboard regressions. All mutations use a synthetic temporary workspace."""
import concurrent.futures
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

A = importlib.import_module('dashboard.app')
from add_job import Store, COLUMNS
from inbox import Inbox
import phone


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()
        self.patch = patch.multiple(A, REPO_ROOT=self.root, JOBS_XLSX=self.root/'jobs.xlsx',
                                    JOBS_DIR=self.root/'jobs', OUTPUT_DIR=self.root/'output',
                                    STATUS_FILE=self.root/'dashboard_statuses.json')
        self.patch.start()
        self.limits = patch.object(A, 'codex_limits', return_value={})
        self.limits.start()
        self.client = TestClient(A.app, base_url='http://127.0.0.1:8000')

    def tearDown(self):
        self.client.close()
        self.limits.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def record(self, key='a', **extra):
        return dict(company='Example '+key, title='Software Engineer I', location='Remote, US',
                    description='Build reliable systems.\nNew graduates welcome.', found_via=['workday'],
                    job_id='workday:example|wd5|us:'+key, suggested_bucket='generalist', **extra)

    def pending(self, key='a', **extra):
        rec = self.record(key, **extra)
        with Inbox(self.root) as ib:
            self.assertEqual(ib.add(rec, 'Suitable for new graduates.'), 'added')
        return rec['job_id']

    def action(self, action, ids):
        res = self.client.post('/api/inbox/'+action,json={'ids':ids})
        self.assertEqual(res.status_code,200,res.text)
        return res.json()['results']

    def undo(self, result):
        return self.client.post('/api/inbox/undo',json={'id':result['id'],'token':result['undo_token']})

    def test_keep_idempotent_and_undo_new_row(self):
        jid=self.pending()
        result=self.action('keep',[jid,jid])[0]
        self.assertEqual(result['result'],'added')
        self.assertEqual(len(Store(self.root).rows()),1)
        self.assertEqual(Store(self.root).rows()[0]['status'],'Not Applied')
        self.assertEqual(self.action('keep',[jid])[0]['result'],'already kept')
        self.assertEqual(self.undo(result).status_code,200)
        self.assertEqual(Store(self.root).rows(),[])
        self.assertEqual(len(self.client.get('/api/inbox').json()['items']),1)
        self.assertEqual(self.undo(result).status_code,409)

    def test_keep_title_match_stays_out_of_sheet(self):
        jid=self.pending(title_match='general')
        self.assertEqual(self.client.get('/api/inbox').json()['items'][0]['record']['title_match'],'general')
        self.assertEqual(self.action('keep',[jid])[0]['result'],'added')
        self.assertNotIn('title_match',Store(self.root).rows()[0])

    def test_reject_bulk_and_undo_token(self):
        ids=[self.pending(k) for k in ['a','b','c']]
        results=self.action('reject',ids)
        self.assertFalse((self.root/'jobs.xlsx').exists())
        self.assertEqual(self.client.get('/api/inbox').json()['items'],[])
        for result in results:
            self.assertEqual(self.undo(result).status_code,200)
        latest=self.action('reject',[ids[0]])[0]
        self.assertEqual(self.undo(results[0]).status_code,409)
        self.assertEqual(self.undo(latest).status_code,200)

    def test_merge_undo_preserves_existing_job_and_status(self):
        jid=self.pending()
        original=self.record()
        original['found_via']=['paste']
        original['job_id']=''
        original['suggested_bucket']=''
        original['status']='Applied'
        added=Store(self.root).add(original)
        before=Store(self.root).rows()
        md=self.root/'jobs'/f"{added['slug']}.md"
        before_md=md.read_text()
        result=self.action('keep',[jid])[0]
        self.assertEqual(result['result'],'merged')
        self.assertEqual(Store(self.root).rows()[0]['status'],'Applied')
        self.assertEqual(self.undo(result).status_code,200)
        self.assertEqual(Store(self.root).rows(),before)
        self.assertEqual(md.read_text(),before_md)

    def test_duplicate_undo_does_not_remove_existing_row(self):
        jid=self.pending()
        Store(self.root).add(self.record())
        result=self.action('keep',[jid])[0]
        self.assertEqual(result['result'],'duplicate')
        self.assertEqual(self.undo(result).status_code,200)
        self.assertEqual(len(Store(self.root).rows()),1)

    def test_undo_refuses_subsequent_edits(self):
        jid=self.pending()
        result=self.action('keep',[jid])[0]
        res=self.client.post(f"/api/jobs/{result['slug']}/status",json={'status':'Interview'})
        self.assertEqual(res.status_code,200)
        self.assertEqual(self.undo(result).status_code,409)
        self.assertEqual(Store(self.root).rows()[0]['status'],'Interview')

    def test_undo_refuses_generated_files(self):
        result=self.action('keep',[self.pending()])[0]
        out=self.root/'output'/result['slug'];out.mkdir(parents=True)
        (out/'Manas_Dalvi_Resume.pdf').write_bytes(b'%PDF test')
        self.assertEqual(self.undo(result).status_code,409)
        self.assertTrue((out/'Manas_Dalvi_Resume.pdf').exists())

    def test_concurrent_keep_exactly_once(self):
        jid=self.pending()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _: self.action('keep',[jid])[0],range(4)))
        self.assertEqual(sum(r['result']=='added' for r in results),1)
        self.assertEqual(len(Store(self.root).rows()),1)

    def test_list_uses_sheet_not_orphan_files_and_new_statuses(self):
        result=Store(self.root).add(self.record())
        (self.root/'jobs'/'orphan.md').write_text('# Orphan')
        rows=self.client.get('/api/jobs').json()['jobs']
        self.assertEqual(len(rows),1)
        self.assertNotIn('New',rows[0]['available_statuses'])
        for status in ['OA','Interview','Offer']:
            res=self.client.post(f"/api/jobs/{result['slug']}/status",json={'status':status})
            self.assertEqual(res.status_code,200)
            self.assertEqual(Store(self.root).rows()[0]['status'],status)
            self.assertEqual(json.loads((self.root/'dashboard_statuses.json').read_text())[result['slug']],status)
        self.assertEqual(self.client.post(f"/api/jobs/{result['slug']}/status",json={'status':'New'}).status_code,400)
        self.assertEqual(self.client.post('/api/jobs/missing/status',json={'status':'OA'}).status_code,404)

    def test_detail_reads_markdown_and_documents(self):
        added=Store(self.root).add(self.record(apply_url='https://example.com/apply',flags=['no-sponsorship']))
        out=self.root/'output'/added['slug'];out.mkdir(parents=True)
        (out/'Manas_Dalvi_Resume.pdf').write_bytes(b'%PDF fake')
        detail=self.client.get('/api/jobs/'+added['slug']).json()
        self.assertEqual(detail['description'],self.record()['description'])
        self.assertEqual(detail['apply_url'],'https://example.com/apply')
        self.assertTrue(detail['artifacts']['resume_pdf'])
        self.assertEqual(self.client.get(f"/view/{added['slug']}/Manas_Dalvi_Resume.pdf").status_code,200)

    def test_delete_retains_recovery_copy(self):
        added=Store(self.root).add(self.record())
        res=self.client.delete('/api/jobs/'+added['slug'])
        self.assertEqual(res.status_code,200)
        self.assertEqual(Store(self.root).rows(),[])
        self.assertEqual(len(list((self.root/'data'/'trash').glob('*/record.json'))),1)
        self.assertEqual(self.client.delete('/api/jobs/'+added['slug']).status_code,404)

    def test_filters_and_partial_bulk_failure(self):
        jid=self.pending(flags=['no-sponsorship'])
        for params in [{'q':'EXAMPLE'},{'source':'workday'},{'bucket':'generalist'},{'flag':'no-sponsorship'}]:
            self.assertEqual(len(self.client.get('/api/inbox',params=params).json()['items']),1)
        self.assertEqual(self.client.get('/api/inbox',params={'q':'absent'}).json()['items'],[])
        self.assertEqual(self.client.get('/api/inbox?status=bad').status_code,422)
        results=self.action('keep',[jid,'missing'])
        self.assertEqual([r['result'] for r in results],['added','not found'])
        self.assertEqual(self.client.post('/api/inbox/keep',json={'ids':[]}).status_code,422)

    def test_quick_add_parse_save_duplicate_and_force(self):
        parsed={'record':self.record(), 'warnings':['Check the location'], 'engine':'test','model':'test'}
        with patch.object(A,'extract',return_value=parsed):
            res=self.client.post('/api/quick-add/parse',json={'raw_text':'Synthetic job posting'})
        self.assertEqual(res.status_code,200)
        fields=res.json()['fields'];self.assertEqual(res.json()['warnings'],parsed['warnings'])
        self.assertFalse(self.client.post('/api/quick-add/check-duplicate',json={'fields':fields}).json()['duplicate'])
        res=self.client.post('/api/quick-add/save',json={'fields':fields})
        self.assertEqual(res.status_code,200)
        self.assertEqual(Store(self.root).rows()[0]['status'],'Not Applied')
        self.assertTrue(self.client.post('/api/quick-add/check-duplicate',json={'fields':fields}).json()['duplicate'])
        fields['Location']='Boston, MA'
        self.assertEqual(self.client.post('/api/quick-add/save',json={'fields':fields,'force':True}).status_code,200)
        self.assertEqual(len(Store(self.root).rows()),2)

    def test_inbox_order_newest_day_then_early_career_then_posted(self):
        for key, title, posted, added in [
            ('old', 'Junior Engineer', '2026-09-01', '2026-09-28'),
            ('plain', 'Software Engineer', '2026-09-29', '2026-09-29'),
            ('early-old', 'Junior Software Engineer', '2026-09-20', '2026-09-29'),
            ('early-new', 'Software Engineer I', '2026-09-29', '2026-09-29'),
        ]:
            rec=self.record(key);rec['title']=title;rec['posted_time']=posted
            with Inbox(self.root) as ib:
                ib.add(rec)
                ib.db.execute('UPDATE inbox SET added_on=? WHERE job_id=?',(added,rec['job_id']))
                ib.db.commit()
        items=self.client.get('/api/inbox').json()['items']
        self.assertEqual([i['record']['company'] for i in items],['Example early-new','Example early-old','Example plain','Example old'])

    def test_inbox_simplify_and_sweeps_first_then_newest(self):
        for key, sources, added in [('board-new', ['workday'], '2026-09-29'), ('simplify-old', ['workday', 'simplify'], '2026-09-27'),
                                    ('linkedin', ['linkedin'], '2026-09-28'), ('board-old', ['greenhouse'], '2026-09-26')]:
            rec=self.record(key, title_match='general');rec['found_via']=sources
            with Inbox(self.root) as ib:
                ib.add(rec)
                ib.db.execute('UPDATE inbox SET added_on=? WHERE job_id=?',(added,rec['job_id']))
                ib.db.commit()
        items=self.client.get('/api/inbox').json()['items']
        self.assertEqual([i['record']['company'] for i in items],['Example linkedin','Example simplify-old','Example board-new','Example board-old'])
        self.assertEqual([i['priority'] for i in items],[True,True,False,False])
        newest=sorted(items,key=lambda i:i['newest_rank'])
        self.assertEqual([i['record']['company'] for i in newest],['Example board-new','Example linkedin','Example simplify-old','Example board-old'])

    def test_undo_restores_preexisting_markdown(self):
        rec=self.record()
        from add_job import record_slug
        md=self.root/'jobs'/f'{record_slug(rec)}.md'
        md.parent.mkdir();md.write_text('Existing local notes')
        result=self.action('keep',[self.pending()])[0]
        self.assertEqual(self.undo(result).status_code,200)
        self.assertEqual(md.read_text(),'Existing local notes')

    def test_system_empty_and_legacy_endpoints_absent(self):
        data=self.client.get('/api/system').json()
        self.assertEqual(data['inbox']['pending'],0)
        self.assertEqual(data['limits'],{})
        self.assertNotIn('opencode',data['diagnostics']['commands'])
        for path in ['prepare','claude-resume','claude-cover','opencode-resume','opencode-cover','compile-pdfs','build-cover-docx','pipeline']:
            self.assertEqual(self.client.post('/api/run/'+path,json={}).status_code,404)
        self.assertEqual(self.client.get('/api/runs/old/stream').status_code,404)

    def test_reworded_titles_are_the_same_job_and_the_sheet_shows_on_cards(self):
        Store(self.root).add({**self.record('s'), 'company': 'Authentic', 'title': 'New Grad Software Engineer',
                              'job_id': '', 'url': 'https://www.linkedin.com/jobs/view/4470483355/', 'found_via': ['linkedin']})
        with Inbox(self.root) as ib:
            # the Greenhouse posting of the job already in the sheet (from LinkedIn), worded differently
            self.assertEqual(ib.add({**self.record('g'), 'company': 'Authentic', 'title': 'Software Engineer, 2027 New Grad',
                                     'job_id': 'greenhouse:4114318009'}), 'in sheet')
            self.assertEqual(ib.add({**self.record('b'), 'company': 'Authentic', 'title': 'Software Engineer, Backend'}), 'added')
            self.assertEqual(ib.add({**self.record('c'), 'company': 'Authentic', 'title': 'Backend Software Engineer'}), 'duplicate')
            self.assertEqual(ib.add({**self.record('d'), 'company': 'Authentic', 'title': 'Software Engineer II'}), 'added')
        items = self.client.get('/api/inbox').json()['items']
        self.assertEqual({i['record']['title'] for i in items}, {'Software Engineer, Backend', 'Software Engineer II'})
        self.assertEqual(items[0]['in_sheet'], [{'title': 'New Grad Software Engineer', 'status': 'Not Applied'}])

    def test_same_job_under_another_name_link_or_repost(self):
        store = Store(self.root)
        store.add({**self.record('s1'), 'company': 'Domino Data Lab', 'title': 'Forward Deployed Engineer - New Grad, 2027',
                   'job_id': '', 'url': 'https://app.careerpuck.com/job-board/domino-data-lab/job/7992530',
                   'location': 'New York City, NY'})
        store.add({**self.record('s2'), 'company': 'Noom', 'title': 'Agentic Engineer (New Grad)', 'location': 'Princeton, NJ'})
        store.add({**self.record('s3'), 'company': 'Zip', 'title': 'Software Engineer, New Grad'})
        store.add({**self.record('s4'), 'company': 'Apple', 'title': 'Data Engineer', 'location': 'Cupertino, CA'})
        store.add({**self.record('s5'), 'company': 'Acme', 'title': 'Software Engineer'})
        with Inbox(self.root) as ib:
            add = lambda key, **f: ib.add({**self.record(key), **f})
            self.assertEqual(add('g', company='Domino', title='Forward Deployed Engineer - New Grad, 2027',
                                 location='Austin, TX', job_id='greenhouse:7992530'), 'in sheet')  # only the link agrees
            self.assertEqual(add('n', company='Noom US', title='Agentic Engineer (New Grad)',
                                 location='Princeton, New Jersey, United States'), 'in sheet')
            # Workday reposts one opening as R123 and R123-1, here under the parent and the brand
            self.assertEqual(add('r1', company='RELX', title='Software Engineer 1', job_id='workday:relx:r117973-1'), 'added')
            self.assertEqual(add('r2', company='LexisNexis Risk Solutions', title='Software Engineer New Grad',
                                 job_id='workday:relx:r117973'), 'duplicate')
            self.assertEqual(add('v1', company='Varsitybrands', title='Software Engineer I (.Net)'), 'added')
            self.assertEqual(add('v2', company='Varsity Brands', title='Software Engineer 1 - .Net'), 'duplicate')
            # different companies, places or specialties stay
            self.assertEqual(add('z', company='ZipRecruiter', title='Software Engineer - New Grad'), 'added')
            self.assertEqual(add('a', company='Apple Bank', title='Data Engineer', location='New York, NY'), 'added')
            self.assertEqual(add('p', company='Acme', title='Software Engineer (Agent Platform)'), 'added')

    def test_dedupe_clears_pending_twins_and_undo_restores(self):
        with Inbox(self.root) as ib:
            ib.add({**self.record('d'), 'company': 'Domino', 'title': 'Forward Deployed Engineer', 'job_id': 'greenhouse:1'},
                   'Suitable for new graduates.')
            ib.add({**self.record('e'), 'company': 'Exelixis', 'title': 'AI and Agentic Engineer Associate'})
            ib.add({**self.record('k'), 'company': 'KLA', 'title': 'Software Engineer 1', 'job_id': 'workday:kla:1-1'})
            # twins that got in before the matcher knew them: one rejected as a copy, one rejected by you
            ib.db.execute("INSERT INTO inbox VALUES ('x', '2026-10-01', 'rejected', NULL, ?, ?, NULL)",
                          (json.dumps({**self.record('x'), 'company': 'Exelixis', 'title': 'Associate Engineer - AI and Agentic'}),
                           'Auto-rejected 2026-10-01 (duplicate: same job as "AI and Agentic Engineer Associate" in the inbox)'))
            ib.db.execute("INSERT INTO inbox VALUES ('y', '2099-01-01', 'rejected', NULL, ?, '', NULL)",
                          (json.dumps({**self.record('y'), 'company': 'KLA', 'title': 'Software Engineer 1', 'job_id': 'workday:kla:1'}),))
            ib.db.commit()
        fields = A.columns_from_record({**self.record('q'), 'company': 'Domino Data Lab', 'title': 'Forward Deployed Engineer',
                                        'job_id': '', 'url': 'https://boards.greenhouse.io/domino/jobs/1'})
        self.assertEqual(self.client.post('/api/quick-add/save', json={'fields': fields}).status_code, 200)
        with Inbox(self.root) as ib:
            self.assertEqual(ib.dedupe(), [])
            self.assertEqual([e['record']['company'] for e in ib.pending()], ['Exelixis'])
            gone = {e['job_id']: e for e in ib._rows('rejected')}
            self.assertIn('already in your sheet: Forward Deployed Engineer at Domino Data Lab (Not Applied)',
                          gone['greenhouse:1']['reason'])
            self.assertIn('in the inbox (rejected)', gone['workday:kla:1']['reason'])
            ib.undo('greenhouse:1')
            self.assertEqual(next(e for e in ib.pending() if e['job_id'] == 'greenhouse:1')['reason'],
                             'Suitable for new graduates.')

    def test_only_this_mac_or_the_owners_phone(self):
        get = lambda **headers: self.client.get('/api/jobs', headers=headers).status_code
        via_phone = {'host': 'mac.tail1.ts.net', 'x-forwarded-for': '100.64.0.2', 'tailscale-user-login': 'Me@example.com'}
        self.assertEqual(get(), 200)
        self.assertEqual(get(host='evil.example'), 403)                     # DNS rebinding
        self.assertEqual(get(**{'x-forwarded-for': '203.0.113.9'}), 403)    # some other tunnel
        self.assertEqual(get(**via_phone), 403)                             # phone access is off
        saved = {'host': 'mac.tail1.ts.net', 'login': 'me@example.com', 'url': 'https://mac.tail1.ts.net', 'since': '2026-09-30T09:00:00'}
        (self.root/'data'/'phone.json').write_text(json.dumps(saved))
        self.assertEqual(get(**via_phone), 200)
        self.assertEqual(get(**{**via_phone, 'tailscale-user-login': 'other@example.com'}), 403)
        self.assertEqual(get(**{**via_phone, 'host': 'loom.example.dev'}), 403)  # a forged login through a tunnel
        self.assertEqual(get(host='mac.tail1.ts.net'), 403)                 # no login: Funnel or a tagged device
        self.assertEqual(self.client.get('/api/system').json()['phone'], {'url': saved['url'], 'since': saved['since']})

    def test_phone_on_saves_identity_refuses_funnel_and_off_forgets(self):
        status = {'BackendState': 'Running', 'Self': {'DNSName': 'mac.tail1.ts.net.', 'UserID': 7},
                  'User': {'7': {'LoginName': 'me@example.com'}}}
        serve, calls = {}, []
        def fake(*args, capture=True):
            calls.append(args)
            out = json.dumps(status) if args[0] == 'status' else json.dumps(serve) if args[-1] == '--json' else ''
            return SimpleNamespace(stdout=out, stderr='', returncode=0)
        with patch.object(phone, 'tailscale', fake):
            saved = phone.on(self.root)
            self.assertEqual((saved['host'], saved['login'], saved['url']), ('mac.tail1.ts.net', 'me@example.com', 'https://mac.tail1.ts.net'))
            self.assertEqual(phone.load(self.root), saved)
            self.assertIn(('serve', '--bg', '--https=443', 'http://127.0.0.1:8000'), calls)
            phone.off(self.root)
            self.assertEqual(phone.load(self.root), {})
            serve['AllowFunnel'] = {'mac.tail1.ts.net:443': True}
            with self.assertRaisesRegex(phone.PhoneError, 'Funnel'):
                phone.on(self.root)
            status['BackendState'] = 'NeedsLogin'
            with self.assertRaisesRegex(phone.PhoneError, 'sign in'):
                phone.on(self.root)
        self.assertEqual(phone.load(self.root), {})

if __name__=='__main__':
    unittest.main()
