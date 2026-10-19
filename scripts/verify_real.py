#!/usr/bin/env python3
"""Independent os.walk/lstat and GNU du verification of scanner evidence."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atlas.scan import scan
BASE = Path(__file__).resolve().parents[1]
root = BASE / '.demo/zlib-1.3.1'
manifest = json.loads((BASE / 'demo/provenance.json').read_text())
before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
assert before == manifest['files']
r = scan(root)
assert r['complete']
# No scanner helpers or report totals are used to derive the reference.
reference = {}
for directory, dirs, files in os.walk(root, followlinks=False):
    for path in [Path(directory)] + [Path(directory) / f for f in files]:
        st = os.lstat(path)
        relative = str(path.relative_to(root))
        reference[relative] = dict(apparent=0 if path.is_dir() else st.st_size, allocated=st.st_blocks*512,
                                   device=str(st.st_dev), inode=str(st.st_ino), size=st.st_size)
assert len(reference) == r['counts']['discovered'] == 296
assert len(before) == r['counts']['files'] == 257
assert len({(v['device'], v['inode']) for v in reference.values()}) == len(reference), 'Real corpus should not have hard links'
actual = {e['path']: e for e in r['entries']}
assert set(reference) == set(actual)
for path, ref in reference.items():
    e = actual[path]
    assert e['status'] == 'measured' and e['owner'] is None
    assert (e['raw_apparent'], e['raw_allocated'], e['stat_size'], e['device'], e['inode']) == (ref['apparent'], ref['allocated'], ref['size'], ref['device'], ref['inode']), path
    descendants = [v for p,v in reference.items() if p == path or path == '.' or p.startswith(path+'/')]
    for metric in ('apparent', 'allocated'):
        assert e[metric] == sum(v[metric] for v in descendants), (path, metric)
# GNU du includes directory allocation and counts each inode once; no symlink following.
for metric, flags in [('apparent', ['--apparent-size']), ('allocated', [])]:
    raw = subprocess.check_output(['du', '--all', '--null', '--block-size=1', '--one-file-system', '--no-dereference', *flags, str(root)])
    du = {}
    for line in raw.split(b'\0'):
        if not line:
            continue
        count, path = line.split(b'\t', 1)
        du[str(Path(os.fsdecode(path)).relative_to(root))] = int(count)
    assert set(du) == set(actual)
    assert all(du[p] == e[metric] for p,e in actual.items()), metric
assert before == {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
result = dict(source_commit=manifest['commit'], entries=len(reference), files=len(before), directories=len(reference)-len(before),
              totals=r['totals'], entry_and_aggregate_checks='All entries, both metrics, match independent traversal and GNU du',
              disagreements=[], source_hashes_unchanged=True, platform=sys.platform,
              du_version=subprocess.check_output(['du', '--version'], text=True).splitlines()[0])
(BASE / 'results/real-verification.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result, indent=2))
