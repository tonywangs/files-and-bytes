"""Rebuild the offline real-input demonstration and independently check outcomes."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent


def run():
    out = ROOT / 'demo-output'
    out.mkdir(exist_ok=True)
    provenance = json.loads((ROOT/'fixtures/provenance.json').read_text())
    source = ROOT/'fixtures/zlib'
    for record in provenance['files']:
        data = (source/record['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == record['sha256']
        assert len(data) == record['size']
    stage = out/'stage'
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(source, stage/'backup')
    # Producers are separate command-line programs, not the audit implementation.
    for name in ('clean.zip','clean.tar'):
        (out/name).unlink(missing_ok=True)
    subprocess.run([sys.executable,'-m','zipfile','-c',str(out/'clean.zip'),'backup'],cwd=stage,check=True)
    subprocess.run(['tar','--format=ustar','-cf',str(out/'clean.tar'),'backup'],cwd=stage,check=True)
    altered = out/'altered'
    if altered.exists():
        shutil.rmtree(altered)
    shutil.copytree(stage, altered)
    (altered/'backup/README').unlink()
    (altered/'backup/zlib.h').write_bytes(b'intentionally changed\n')
    (altered/'backup/extra.txt').write_bytes(b'intentionally extra\n')
    (out/'changed.zip').unlink(missing_ok=True)
    subprocess.run([sys.executable,'-m','zipfile','-c',str(out/'changed.zip'),'backup'],cwd=altered,check=True)
    subprocess.run(['tar','--format=ustar','-cf',str(out/'changed.tar'),'backup'],cwd=altered,check=True)
    expected_changes = {'README':'missing','zlib.h':'changed','extra.txt':'extra'}
    evidence = {}
    for name in ('clean.zip','clean.tar','changed.zip','changed.tar'):
        expected_tree = stage/'backup' if name.startswith('clean') else altered/'backup'
        # External readers provide an oracle without calling the audit code.
        expected = {p.relative_to(expected_tree).as_posix():p.read_bytes() for p in expected_tree.rglob('*') if p.is_file()}
        if name.endswith('.zip'):
            listing = subprocess.check_output(['unzip','-Z1',str(out/name)]).decode().splitlines()
            actual = {p.removeprefix('backup/'):subprocess.check_output(['unzip','-p',str(out/name),p]) for p in listing if not p.endswith('/')}
        else:
            listing = subprocess.check_output(['tar','-tf',str(out/name)]).decode().splitlines()
            actual = {p.removeprefix('backup/'):subprocess.check_output(['tar','-xOf',str(out/name),p]) for p in listing if not p.endswith('/')}
        assert actual == expected, name
        source_bytes = {r['path']:(source/r['path']).read_bytes() for r in provenance['files']}
        oracle = {p:('extra' if p not in source_bytes else 'missing' if p not in actual else 'match' if source_bytes[p]==actual[p] else 'changed') for p in source_bytes.keys() | actual.keys()}
        proc = subprocess.run([sys.executable,str(ROOT/'archive_audit.py'),str(source),str(out/name),'--prefix','backup','--output',str(out/name.replace('.','-'))])
        assert proc.returncode == (0 if name.startswith('clean') else 1)
        report = json.loads((out/name.replace('.','-')/'report.json').read_text())
        assert {r['path']:r['status'] for r in report['comparisons']} == oracle
        assert report['complete']
        assert {p:s for p,s in oracle.items() if s!='match'} == ({} if name.startswith('clean') else expected_changes)
        evidence[name] = {'status':report['status'],'oracle':'external unzip/tar bytes compared directly','file_count':len(actual)}
    (out/'verification.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print('Demo and independent byte oracle passed. Open demo-output/changed-zip/report.html')


if __name__ == '__main__':
    run()
