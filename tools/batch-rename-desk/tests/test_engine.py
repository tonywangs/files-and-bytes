import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from engine import Desk, Refused, fingerprint, transform

ROOT = Path(__file__).resolve().parents[1]


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        for name, data in [('a.txt', b'alpha'), ('b.txt', b'beta'), ('c.txt', b'gamma')]:
            (self.folder/name).write_bytes(data)
        self.desk = Desk(self.folder)

    def tearDown(self):
        self.desk.close()
        self.temp.cleanup()

    def plan(self, dests):
        rows, _ = self.desk.scan()
        return [dict(row, dest=dest) for row, dest in zip(rows, dests)]

    def contents(self):
        return {p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()}

    def test_cycles_and_undo(self):
        original = self.contents()
        with self.desk.locked():
            j = self.desk.apply(self.plan(['b.txt','c.txt','a.txt']))
            self.assertEqual(self.contents(), {'b.txt':b'alpha','c.txt':b'beta','a.txt':b'gamma'})
            self.desk.undo(j['id'])
        self.assertEqual(original, self.contents())

    def test_collision_invalid_stale_and_occupied(self):
        for dests in [['x','X','z'], ['../escape','b','c'], ['.rename-desk','b','c'], ['nul.txt','b','c'], ['é','e\u0301','c']]:
            with self.subTest(dests=dests), self.assertRaises(Refused):
                self.desk.apply(self.plan(dests))
        (self.folder/'occupied').mkdir()
        with self.assertRaisesRegex(Refused, 'Occupied'):
            self.desk.apply(self.plan(['occupied','b.txt','c.txt']))
        rows = self.plan(['x','y','z'])
        (self.folder/'a.txt').write_bytes(b'changed')
        with self.assertRaisesRegex(Refused, 'Stale'):
            self.desk.apply(rows)
        self.assertFalse(self.desk.journals())

    def test_symlink_hardlink_and_special_excluded(self):
        (self.folder/'link').symlink_to(self.folder/'a.txt')
        os.link(self.folder/'b.txt', self.folder/'hard')
        os.mkfifo(self.folder/'pipe')
        rows, skipped = self.desk.scan()
        self.assertEqual([r['source'] for r in rows], ['a.txt','c.txt'])
        self.assertEqual({r['name'] for r in skipped}, {'b.txt','hard','link','pipe'})

    def test_undo_conflict_and_changed_file_are_nonmutating(self):
        j = self.desk.apply(self.plan(['x','y','z']))
        (self.folder/'a.txt').write_bytes(b'unrelated')
        before = self.contents()
        with self.assertRaisesRegex(Refused, 'occupied'):
            self.desk.undo(j['id'])
        self.assertEqual(before, self.contents())
        (self.folder/'a.txt').unlink()
        (self.folder/'x').write_bytes(b'changed')
        before = self.contents()
        with self.assertRaisesRegex(Refused, 'Changed'):
            self.desk.undo(j['id'])
        self.assertEqual(before, self.contents())

    def test_replaced_inode_refused(self):
        j = self.desk.apply(self.plan(['x','y','z']))
        (self.folder/'replacement').write_bytes(b'alpha')
        os.replace(self.folder/'replacement', self.folder/'x')
        with self.assertRaisesRegex(Refused, 'Missing'):
            self.desk.undo(j['id'])

    def test_no_replace_at_actual_move(self):
        rows = self.plan(['x','y','z'])
        real_move = self.desk.move
        def racing_move(srcfd, src, dstfd, dst, expected):
            if dst == 'x':
                (self.folder/'x').write_bytes(b'unrelated')
            real_move(srcfd, src, dstfd, dst, expected)
        with patch.object(self.desk, 'move', racing_move), self.assertRaisesRegex(Refused, 'File exists'):
            self.desk.apply(rows)
        self.assertEqual((self.folder/'x').read_bytes(), b'unrelated')
        self.desk.undo(self.desk.journals()[0]['id'])
        self.assertEqual((self.folder/'a.txt').read_bytes(), b'alpha')
        self.assertEqual((self.folder/'x').read_bytes(), b'unrelated')

    def test_control_symlink_refused(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td)/'.rename-desk').symlink_to(self.folder, target_is_directory=True)
            with self.assertRaises(OSError):
                Desk(td)

    def test_renamed_folder_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)/'root'; root.mkdir()
            d = Desk(root)
            root.rename(Path(td)/'moved'); root.mkdir()
            try:
                with self.assertRaisesRegex(Refused, 'replaced'), d.locked():
                    pass
            finally:
                d.close()

    def test_transform_extension_and_literal_order(self):
        names = ['a.b.svg','.env','z.svg']
        self.assertEqual(transform(names, dict(find='.',replace='_',prefix='p-',suffix='-s',number=True,start=8,width=2)), ['p-08-a_b-s.svg','p-09-_env-s','p-10-z-s.svg'])
        self.assertEqual(transform(['a.svg'], dict(find='.svg',replace='.txt',preserve_extension=False)), ['a.txt'])

    def test_crash_every_move_apply_and_undo(self):
        # Separate processes exit without final journal status updates.
        for action in ['apply','undo']:
            for stop in range(1, 7):
                with self.subTest(action=action, stop=stop), tempfile.TemporaryDirectory() as td:
                    p = Path(td)
                    original = {'a': b'A', 'b': b'B', 'c': b'C'}
                    for name, data in original.items(): (p/name).write_bytes(data)
                    code = """
import sys
from engine import Desk
d = Desk(sys.argv[1])
with d.locked():
 if sys.argv[2] == 'apply':
  rows,_=d.scan()
  d.apply([dict(r,dest=n) for r,n in zip(rows,['b','c','a'])])
 else:
  d.undo(d.journals()[0]['id'])
"""
                    if action == 'undo':
                        subprocess.run([sys.executable,'-c',code,td,'apply'],cwd=ROOT,check=True)
                    result = subprocess.run([sys.executable,'-c',code,td,action],cwd=ROOT,env={**os.environ,'RENAME_DESK_TEST_CRASH_AFTER':str(stop)})
                    self.assertEqual(result.returncode,86)
                    d = Desk(td)
                    try:
                        with d.locked(): d.undo(d.journals()[0]['id'])
                        self.assertEqual({f.name:f.read_bytes() for f in p.iterdir() if f.is_file()}, original)
                    finally: d.close()


if __name__ == '__main__':
    unittest.main()
