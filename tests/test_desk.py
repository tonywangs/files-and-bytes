import json, os, pathlib, tempfile, unittest
from unittest.mock import patch
import desk
class DeskTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=pathlib.Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def files(self):
  for n,b in [('a',b'x'),('b',b'x'),('empty',b''),('empty2',b''),('unique',b'y')]: (self.p/n).write_bytes(b)
 def test_accounting_links_overlap_and_empty(self):
  self.files();os.link(self.p/'a',self.p/'hard');os.symlink(self.p/'a',self.p/'sym')
  r=desk.scan([str(self.p),str(self.p)]);self.assertTrue(r['complete']);self.assertEqual(len(r['entries']),8);self.assertEqual(len(r['groups']),2)
  g=next(g for g in r['groups'] if g['size']);self.assertEqual(g['distinct_inodes'],2);self.assertEqual(g['logical_duplicate_bytes'],2)
  self.assertEqual((self.p/'a').read_bytes(),b'x')
 def test_preferences_invalidated(self):
  self.files();r=desk.scan([str(self.p)]);g=next(g for g in r['groups'] if g['size']);d={g['id']:g['paths'][0]}
  self.assertEqual(desk.restore(desk.scan([str(self.p)]),d)['decisions'],d)
  (self.p/'b').write_bytes(b'z');self.assertEqual(desk.restore(desk.scan([str(self.p)]),d)['decisions'],{})
 def test_hash_collision_still_compares(self):
  self.files()
  with patch('desk.digest',return_value='collision'):r=desk.scan([str(self.p)])
  self.assertEqual(sorted(len(g['paths']) for g in r['groups']),[2,2])
 def test_changed_and_unreadable(self):
  self.files();original=desk.digest
  def fail(e):
   if e['path'].endswith('/a'):raise PermissionError('unreadable control')
   if e['path'].endswith('/b'):(self.p/'b').write_bytes(b'changed')
   return original(e)
  with patch('desk.digest',side_effect=fail):r=desk.scan([str(self.p)])
  self.assertFalse(r['complete']);self.assertEqual(sum(e['status']=='failed' for e in r['entries']),2)
 def test_limit(self):
  self.files()
  with patch('desk.MAX_ENTRIES',2):r=desk.scan([str(self.p)])
  self.assertFalse(r['complete']);self.assertTrue(r['limit_reached'])
 def test_html_safe_and_evidence(self):
  (self.p/'<script>').write_bytes(b'a');(self.p/'b').write_bytes(b'a');r=desk.scan([str(self.p)]);out=desk.offline(r)
  self.assertIn('&lt;script&gt;',out);self.assertIn('application/json',out);self.assertNotIn('/<script>',out)
if __name__=='__main__':unittest.main()
