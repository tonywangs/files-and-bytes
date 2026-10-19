import io
import json
import os
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from archive_audit import audit, write_report


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root/'source'
        self.src.mkdir()
        (self.src/'a').write_bytes(b'alpha')
        self.z = self.root/'archive.zip'

    def zip(self, entries):
        with zipfile.ZipFile(self.z,'w') as z:
            for name,data in entries:
                z.writestr(name,data)
        return self.z

    def test_clean_and_discrepancies(self):
        self.zip([('a',b'alpha')])
        self.assertEqual(audit(self.src,self.z)['status'],'identical')
        self.zip([('a',b'wrong'),('extra',b'e')])
        r = audit(self.src,self.z)
        self.assertEqual({x['path']:x['status'] for x in r['comparisons']},{'a':'changed','extra':'extra'})
        self.zip([])
        self.assertEqual(audit(self.src,self.z)['comparisons'][0]['status'],'missing')

    def test_duplicates_and_unsafe(self):
        for entries in [[('a',b'alpha'),('a',b'alpha')], [('a',b'alpha'),('../evil',b'x')], [('a',b'alpha'),('C:/evil',b'x')], [('a',b'alpha'),('a\\b',b'x')]]:
            self.zip(entries)
            r = audit(self.src,self.z)
            self.assertEqual(r['status'],'incomplete')
            self.assertEqual(len(r['archive_entries']),2)

    def test_prefix_and_outside(self):
        self.zip([('root/a',b'alpha')])
        self.assertEqual(audit(self.src,self.z,prefix='root')['status'],'identical')
        self.assertEqual(audit(self.src,self.z,prefix='other')['status'],'incomplete')

    def test_crc_corruption(self):
        self.zip([('a',b'alpha')])
        data = bytearray(self.z.read_bytes())
        start = data.index(b'alpha')
        data[start] ^= 1
        self.z.write_bytes(data)
        self.assertEqual(audit(self.src,self.z)['status'],'incomplete')

    def test_limits(self):
        self.zip([('a',b'alpha'),('b',b'x')])
        for limits in [dict(max_entries=1),dict(max_file=4),dict(max_total=4),dict(max_archive=4)]:
            self.assertEqual(audit(self.src,self.z,**limits)['status'],'incomplete')

    def test_tar_types_duplicates_and_truncation(self):
        for kind in ['clean','link','hardlink','duplicate','truncated']:
            path = self.root/'test.tar'
            with tarfile.open(path,'w') as t:
                m = tarfile.TarInfo('a'); m.size=5
                t.addfile(m,io.BytesIO(b'alpha'))
                if kind == 'duplicate':
                    t.addfile(m,io.BytesIO(b'alpha'))
                if kind in ('link','hardlink'):
                    m = tarfile.TarInfo('link'); m.type=tarfile.SYMTYPE if kind=='link' else tarfile.LNKTYPE; m.linkname='a'
                    t.addfile(m)
            if kind=='truncated':
                path.write_bytes(path.read_bytes()[:514])
            self.assertEqual(audit(self.src,path)['status'],'identical' if kind=='clean' else 'incomplete')

    def test_source_symlink_and_fifo(self):
        self.zip([('a',b'alpha')])
        (self.src/'link').symlink_to('a')
        self.assertEqual(audit(self.src,self.z)['status'],'incomplete')
        (self.src/'link').unlink()
        os.mkfifo(self.src/'fifo')
        self.assertEqual(audit(self.src,self.z)['status'],'incomplete')

    def test_unreadable_and_interrupt(self):
        self.zip([('a',b'alpha')])
        with patch('archive_audit.os.open',side_effect=PermissionError('denied')):
            self.assertEqual(audit(self.src,self.z)['status'],'incomplete')
        with patch('archive_audit.digest',side_effect=KeyboardInterrupt):
            self.assertEqual(audit(self.src,self.z)['status'],'incomplete')

    def test_change_during_read(self):
        self.zip([('a',b'alpha')])
        from archive_audit import digest
        def changing(*args):
            answer=digest(*args)
            (self.src/'a').write_bytes(b'changed')
            return answer
        with patch('archive_audit.digest',side_effect=changing):
            self.assertEqual(audit(self.src,self.z)['status'],'incomplete')

    def test_html_escaped(self):
        self.zip([('<script>alert(1)</script>',b'x')])
        r=audit(self.src,self.z)
        write_report(r,self.root/'reports')
        page=(self.root/'reports/report.html').read_text()
        self.assertNotIn('<script>',page)
        self.assertIn('&lt;script&gt;',page)
        self.assertEqual(json.loads((self.root/'reports/report.json').read_text()),r)

    def test_compressed_tar(self):
        for suffix in ('gz','bz2','xz'):
            path=self.root/('archive.tar.'+suffix)
            with tarfile.open(path,'w:'+suffix) as t:
                t.add(self.src/'a',arcname='a')
            self.assertEqual(audit(self.src,path)['status'],'identical')

    def test_compressed_trailer_corruption_and_expansion(self):
        import gzip
        path=self.root/'archive.tar.gz'
        with tarfile.open(path,'w:gz') as t:
            t.add(self.src/'a',arcname='a')
        original=path.read_bytes()
        path.write_bytes(original[:-4])
        self.assertEqual(audit(self.src,path)['status'],'incomplete')
        path.write_bytes(gzip.compress(b'\0'*1000000))
        self.assertEqual(audit(self.src,path,max_total=10000)['status'],'incomplete')

    def test_nonempty_zip_directory(self):
        self.zip([('a',b'alpha'),('dir/',b'hidden')])
        self.assertEqual(audit(self.src,self.z)['status'],'incomplete')

    def test_tar_malformed_later_header_and_terminator(self):
        path=self.root/'archive.tar'
        with tarfile.open(path,'w',format=tarfile.USTAR_FORMAT) as t:
            info=tarfile.TarInfo('a'); info.size=5
            t.addfile(info,io.BytesIO(b'alpha'))
        valid=path.read_bytes()
        for data in [valid[:1024]+b'garbage'*100, valid[:1024], valid[:1536], valid[:2048]+b'garbage']:
            path.write_bytes(data)
            self.assertEqual(audit(self.src,path)['status'],'incomplete')

    def test_empty_zip_directory_corrupt_crc(self):
        self.zip([('a',b'alpha'),('dir/',b'')])
        data=bytearray(self.z.read_bytes())
        positions=[]
        offset=0
        while True:
            offset=data.find(b'PK\x01\x02',offset)
            if offset<0:
                break
            positions.append(offset)
            offset+=4
        struct.pack_into('<I',data,positions[-1]+16,123)
        self.z.write_bytes(data)
        self.assertEqual(audit(self.src,self.z)['status'],'incomplete')


if __name__ == '__main__':
    unittest.main()
