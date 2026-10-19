import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from desk.core import DeskError, Engine, ROOT, digest, identity, inventory, parse_par2, read_file, safe_name

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / 'source'
        shutil.copytree(ROOT / 'data/twemoji', self.source)
        self.engine = Engine(self.base / 'work', self.source)
        self.names = sorted(p.name for p in self.source.iterdir())
    def tearDown(self):
        self.temp.cleanup()
    def package(self):
        return self.engine.create(self.names)

    def test_real_collection_provenance(self):
        manifest = json.loads((ROOT / 'data/sources.json').read_text())
        for f in manifest['files']:
            p = ROOT / 'data' / ('twemoji/' + f['name'] if f['name'].endswith('.svg') else f['name'])
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), f['sha256'])
            self.assertIn(manifest['revision'], f['url'])

    def test_real_damage_matrix_and_independent_bytes(self):
        p = self.package()
        before = {n: (self.source / n).read_bytes() for n in self.names}
        self.assertEqual(self.engine.evaluate(p['id'], self.source)['status'], 'verified-intact')
        # Predictions are fixed before running each damage evaluation.
        for scenario, expected in [('byte-corruption', True), ('truncation', True), ('missing-file', True),
                                   ('insufficient-recovery', False), ('damaged-recovery', False)]:
            with self.subTest(scenario=scenario):
                d = self.engine.damage_demo(p['id'], scenario)
                v = self.engine.evaluate(p['id'], d['candidate'], recovery_folder=d['recovery_folder'])
                self.assertEqual(v['status'], 'repair-possible' if expected else 'insufficient-recovery')
                r = self.engine.evaluate(p['id'], d['candidate'], True, d['recovery_folder'])
                self.assertEqual(r['status'], 'verified-restored' if expected else 'insufficient-recovery')
                self.assertTrue(r['inputs_unchanged'] and r['recovery_inputs_unchanged'] and r['preserved_originals_unchanged'])
                self.assertEqual(set(x['name'] for x in r['output_files']), set(self.names))
                if expected:
                    for n, raw in before.items():
                        restored = Path(r['output_directory']) / n
                        self.assertEqual(restored.read_bytes(), raw)
                        self.assertEqual(hashlib.sha256(restored.read_bytes()).digest(), hashlib.sha256(raw).digest())
                else:
                    self.assertIsNone(r['output_directory'])
                    self.assertFalse((self.engine.workspace / r['id'] / 'restored').exists())
        self.assertEqual({n:(self.source/n).read_bytes() for n in self.names}, before)

    def test_input_validation_and_complete_accounting(self):
        for names in [[], [self.names[0]] * 2, ['../escape'], ['-option'], ['unicode-🦊']]:
            with self.assertRaises(DeskError): self.engine.create(names)
        for redundancy, block in [(0,256),(101,256),(True,256),(30,65),(30,0)]:
            with self.assertRaises(DeskError): self.engine.create(self.names,redundancy,block)
        (self.source/'empty').touch()
        (self.source/'link').symlink_to(self.source/self.names[0])
        os.link(self.source/self.names[1],self.source/'hardlink')
        os.mkfifo(self.source/'pipe')
        for name in ['empty','link','hardlink','pipe']:
            with self.assertRaises((DeskError,OSError)): self.engine.create([name])
        rows={r['name']:r for r in inventory(self.source)}
        self.assertTrue(all(not rows[n]['supported'] for n in ['empty','link','hardlink','pipe']))
        for name in ['CON.txt','LPT1','file.','foo/bar','a\\b']:
            with self.assertRaises(DeskError):safe_name(name)

    def test_source_change_and_process_failure_leave_no_ready_package(self):
        real_run=self.engine.run
        def mutate(*args,**kwargs):
            r=real_run(*args,**kwargs)
            (self.source/self.names[0]).write_bytes(b'changed')
            return r
        with patch.object(self.engine,'run',side_effect=mutate):
            with self.assertRaisesRegex(DeskError,'changed'):self.package()
        self.assertFalse(list(self.engine.workspace.glob('*/manifest.json')))
        with patch.object(self.engine,'run',return_value={'exit_code':3,'interrupted':None}):
            with self.assertRaisesRegex(DeskError,'Creation failed'):self.package()
        self.assertFalse(list(self.engine.workspace.glob('*/manifest.json')))

    def test_cancel_and_timeout_kill_engine(self):
        slow=self.base/'slow-engine'
        slow.write_text('#!/bin/sh\nsleep 30\n')
        slow.chmod(0o700)
        self.engine.binary=str(slow)
        cwd=self.base/'execution';cwd.mkdir()
        r=self.engine.run([],cwd,timeout=.1)
        self.assertIsNotNone(r['interrupted'])
        timer=threading.Timer(.1,self.engine.cancel.set);timer.start()
        r=self.engine.run([],cwd)
        timer.join()
        self.assertEqual(r['interrupted'],'cancelled')
        self.assertLess(r['elapsed_seconds'],3)

    def test_cancel_after_engine_success_prevents_publication(self):
        real_run=self.engine.run
        def cancel_after(*args,**kwargs):
            result=real_run(*args,**kwargs)
            self.engine.cancel.set()
            return result
        with patch.object(self.engine,'run',side_effect=cancel_after):
            with self.assertRaisesRegex(DeskError,'cancelled'):
                self.package()
        self.assertFalse(list(self.engine.workspace.glob('*/manifest.json')))
        self.engine.cancel.clear()
        p=self.package()
        self.assertFalse(self.engine.request_cancel())  # already committed
        d=self.engine.damage_demo(p['id'],'missing-file')
        with patch.object(self.engine,'run',side_effect=cancel_after):
            with self.assertRaisesRegex(DeskError,'cancelled'):
                self.engine.evaluate(p['id'],d['candidate'],True)
        self.assertFalse(list(self.engine.workspace.glob('repair-*/restored')))
        self.assertFalse(list(self.engine.workspace.glob('repair-*/report.json')))

    def test_imported_basis_and_repeated_repair_never_overwrite(self):
        p=self.package()
        imported=self.engine.import_package(self.engine.workspace/p['id']/'recovery')
        self.assertEqual(imported['basis'],'imported-par2-md5-only')
        d=self.engine.damage_demo(p['id'],'missing-file')
        a=self.engine.evaluate(imported['id'],d['candidate'],True)
        b=self.engine.evaluate(imported['id'],d['candidate'],True)
        self.assertEqual(a['status'],'verified-restored')
        self.assertNotEqual(a['output_directory'],b['output_directory'])
        self.assertTrue(all(r['byte_for_byte_original_match'] is None for r in a['output_files']))
        self.assertNotIn('independent-original-sha256',(self.engine.workspace/a['id']/'report.html').read_text())

    def test_malicious_par2_embedded_path_is_rejected(self):
        p=self.package()
        folder=self.engine.workspace/p['id']/'recovery'
        # Recompute packet checksum after altering a filename; valid checksum must
        # never bypass traversal protection.
        source=next(folder.glob('*.par2')).read_bytes()
        offset=0
        while offset < len(source):
            size=struct.unpack_from('<Q',source,offset+8)[0]
            if source[offset+48:offset+64] == b'PAR 2.0\0FileDesc':
                packet=bytearray(source[offset:offset+size]); old=packet[120:]
                packet[120:]=b'../'+b'x'*(len(old)-3)
                packet[16:32]=hashlib.md5(packet[32:]).digest()
                malicious=self.base/'malicious';malicious.mkdir()
                (malicious/'bad.par2').write_bytes(source[:offset]+packet+source[offset+size:])
                with self.assertRaises(DeskError):self.engine.import_package(malicious)
                return
            offset+=size
        self.fail('No file descriptor found')

    def test_false_success_exit_is_not_verified(self):
        p=self.package();d=self.engine.damage_demo(p['id'],'byte-corruption')
        with patch.object(self.engine,'run',return_value={'exit_code':0,'interrupted':None,'output':'pretend','command':[]}):
            r=self.engine.evaluate(p['id'],d['candidate'],True)
        self.assertEqual(r['status'],'failed-or-unverified')
        self.assertIsNone(r['output_directory'])

    def test_final_copy_mismatch_never_publishes(self):
        p=self.package();d=self.engine.damage_demo(p['id'],'missing-file')
        original_check=self.engine.check_file
        def fail_final(path,*args):
            if path.parent.name == 'unverified-output':
                path.write_bytes(b'copy failed')
            return original_check(path,*args)
        with patch.object(self.engine,'check_file',side_effect=fail_final):
            with self.assertRaisesRegex(DeskError,'Final output verification failed'):
                self.engine.evaluate(p['id'],d['candidate'],True)
        self.assertFalse(list(self.engine.workspace.glob('repair-*/restored')))
        self.assertFalse(list(self.engine.workspace.glob('repair-*/report.json')))

    def test_limits_and_recovery_set_mismatch(self):
        huge=self.source/'large';huge.write_bytes(b'X'*(4*1024**2+1))
        with self.assertRaisesRegex(DeskError,'exceeds'):self.engine.create(['large'])
        p=self.package()
        (self.source/self.names[0]).write_bytes(b'different source')
        other=self.package()
        with self.assertRaisesRegex(DeskError,'differ'):
            self.engine.evaluate(p['id'],self.source,True,self.engine.workspace/other['id']/'recovery')
        self.assertFalse(list(self.engine.workspace.glob('repair-*/restored')))

if __name__ == '__main__':unittest.main()
