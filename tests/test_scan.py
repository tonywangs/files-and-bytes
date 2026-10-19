import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from atlas.scan import scan
from atlas.report import html

class ScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def test_controls_and_aggregates(self):
        (self.root/'empty').touch()
        (self.root/'nested').mkdir()
        (self.root/'nested'/'雪 <img onerror=alert(1)>').write_bytes(b'hello')
        with (self.root/'sparse').open('wb') as f:
            f.truncate(8*1024*1024)
        os.link(self.root/'sparse', self.root/'alias')
        os.symlink('/etc', self.root/'external-link')
        os.symlink('missing', self.root/'broken')
        r = scan(self.root)
        self.assertTrue(r['complete'])
        e = {n['path']:n for n in r['entries']}
        self.assertEqual(r['counts']['discovered'], 8)
        self.assertEqual(e['empty']['apparent'], 0)
        self.assertEqual(e['nested']['apparent'], 5)
        self.assertEqual(e['external-link']['kind'], 'symlink')
        self.assertEqual(e['external-link']['apparent'], len('/etc'))
        self.assertLess(e['sparse']['raw_allocated'], e['sparse']['raw_apparent'])
        self.assertEqual(e['sparse']['apparent']+e['alias']['apparent'], 8*1024*1024)
        alias = next(n for n in r['entries'] if n['owner'] is not None)
        self.assertEqual(r['entries'][alias['owner']]['inode'], alias['inode'])
        self.assertEqual(r['totals']['apparent'], sum(n['own_apparent'] for n in r['entries']))
        self.assertEqual(r['totals']['allocated'], sum(n['own_allocated'] for n in r['entries']))
    def test_excluded_visible_and_incomplete(self):
        (self.root/'secret').mkdir()
        (self.root/'secret'/'hidden').touch()
        r = scan(self.root, exclude=['secret'])
        self.assertFalse(r['complete'])
        self.assertEqual(r['counts']['skipped'], 1)
        self.assertEqual(r['counts']['discovered'], 2)
    def test_entry_limit(self):
        for i in range(10):
            (self.root/str(i)).touch()
        r = scan(self.root, max_entries=3)
        self.assertEqual(len(r['entries']), 3)
        self.assertFalse(r['complete'])
        self.assertIn('Entry limit', r['errors'][0]['message'])
    def test_depth_limit(self):
        (self.root/'a').mkdir()
        (self.root/'a'/'b').touch()
        r = scan(self.root, max_depth=1)
        self.assertFalse(r['complete'])
        self.assertEqual(len(r['entries']), 2)
    def test_cancel_during_scan(self):
        for i in range(10):
            (self.root/str(i)).touch()
        cancel = threading.Event()
        original = os.stat
        def stop(*a, **kw):
            result = original(*a, **kw)
            cancel.set()
            return result
        with patch('atlas.scan.os.stat', side_effect=stop):
            r = scan(self.root, cancel=cancel)
        self.assertFalse(r['complete'])
        self.assertEqual(len(r['entries']), 2)
        self.assertIn('Cancelled', r['errors'][0]['message'])
    def test_time_limit(self):
        with patch('atlas.scan.time.monotonic', side_effect=[0, 100]):
            r = scan(self.root, max_seconds=1)
        self.assertFalse(r['complete'])
        self.assertIn('Time limit', r['errors'][0]['message'])
    def test_permission_error_real(self):
        locked = self.root/'locked'
        locked.mkdir()
        (locked/'hidden').touch()
        locked.chmod(0)
        try:
            r = scan(self.root)
            if os.geteuid() == 0:
                self.skipTest('Root bypasses permission controls')
            self.assertFalse(r['complete'])
            self.assertEqual(r['counts']['failed'], 1)
            self.assertIn('Permission denied', r['errors'][0]['message'])
        finally:
            locked.chmod(0o700)
    def test_missing_root_and_symlink_components(self):
        self.assertFalse(scan(self.root/'missing')['complete'])
        (self.root/'real').mkdir()
        (self.root/'real'/'child').mkdir()
        (self.root/'link').symlink_to('real')
        self.assertFalse(scan(self.root/'link'/'child')['complete'])
    def test_boundary_mock(self):
        (self.root/'other').touch()
        original = os.stat
        def foreign(*a, **kw):
            st=original(*a, **kw)
            return SimpleNamespace(st_dev=st.st_dev+1)
        with patch('atlas.scan.os.stat', side_effect=foreign):
            r=scan(self.root)
        self.assertFalse(r['complete'])
        self.assertEqual(r['counts']['skipped'], 1)
        self.assertEqual(r['totals']['apparent'], 0)
    def test_allocation_unavailable_mock(self):
        (self.root/'file').write_bytes(b'abc')
        original=os.stat
        def no_blocks(*a, **kw):
            st=original(*a, **kw)
            return SimpleNamespace(**{k:getattr(st,k) for k in ('st_dev','st_ino','st_mode','st_size','st_mtime_ns','st_nlink')})
        with patch('atlas.scan.os.stat', side_effect=no_blocks):
            r=scan(self.root)
        self.assertTrue(r['complete'])
        self.assertEqual(r['totals']['allocation_unknown'], 1)
        self.assertIsNone(r['entries'][1]['raw_allocated'])
    def test_directory_replacement_mock(self):
        (self.root/'dir').mkdir()
        original=os.fstat
        calls=0
        def changed(fd):
            nonlocal calls
            st=original(fd);calls+=1
            return st if calls==1 else SimpleNamespace(st_dev=st.st_dev, st_ino=st.st_ino+1)
        with patch('atlas.scan.os.fstat', side_effect=changed):
            r=scan(self.root)
        self.assertFalse(r['complete'])
        self.assertIn('changed', r['errors'][0]['message'])
    def test_html_payload_inert(self):
        r=scan(self.root)
        r['root']='</script><script>alert(1)</script>'
        page=html(r)
        self.assertNotIn(r['root'], page)
        self.assertIn("connect-src 'none'", page)
        payload=page.split('<script id="snapshot" type="application/json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload)['root'], r['root'])
    def test_invalid_limits(self):
        for kwargs in ({'max_entries':0},{'max_depth':129},{'max_seconds':301}):
            with self.assertRaises(ValueError):
                scan(self.root, **kwargs)


class ExportTests(unittest.TestCase):
    def test_large_integer_transport(self):
        from atlas.report import web_safe
        value = 2**53+1
        self.assertEqual(web_safe({'bytes': value, 'complete': True}), {'bytes': str(value), 'complete': True})
        page = html({'bytes': value})
        payload = page.split('<script id="snapshot" type="application/json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload)['bytes'], str(value))

    def test_output_symlink_cannot_write_into_source(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            root=base/'source'
            root.mkdir()
            alias=base/'alias'
            alias.symlink_to(root, target_is_directory=True)
            for dest in (alias/'report', base/'direct'):
                if dest.name == 'direct':
                    dest.with_suffix('.json').symlink_to(root/'victim')
                p=subprocess.run([sys.executable,'-m','atlas',str(root),'--output',str(dest)],capture_output=True,text=True)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn('outside selected root', p.stderr)
            self.assertEqual(list(root.iterdir()), [])

    def test_output_hard_link_cannot_truncate_source(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            root=base/'source'
            root.mkdir()
            original=root/'original'
            original.write_text('untouched')
            os.link(original, base/'report.json')
            p=subprocess.run([sys.executable,'-m','atlas',str(root),'--output',str(base/'report')],capture_output=True,text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('already exists', p.stderr)
            self.assertEqual(original.read_text(), 'untouched')

if __name__ == '__main__':
    unittest.main()
