"""Independent oracle: whole bytes as dictionary keys, no scanner hashing/grouping."""
import collections, hashlib, json, pathlib, sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from desk import scan
root=pathlib.Path('demo/Lib/test'); manifest=json.loads(pathlib.Path('demo/provenance.json').read_text())
for item in manifest['files']:
    assert hashlib.sha256((pathlib.Path('demo')/item['path']).read_bytes()).hexdigest()==item['sha256']
buckets=collections.defaultdict(list)
for p in root.rglob('*'):
    if p.is_file():buckets[p.read_bytes()].append(str(p.absolute()))
expected={tuple(sorted(v)) for v in buckets.values() if len(v)>1}
r=scan([str(root)]);actual={tuple(sorted(g['paths'])) for g in r['groups']}
assert r['complete'] and actual==expected
assert len(expected)==7 and sum(map(len,expected))==17
assert sum(e['status'] in ('unique','duplicate') for e in r['entries'])==450
print(json.dumps({'real_files':450,'groups':len(expected),'duplicate_members':sum(map(len,expected)),'complete':r['complete'],'oracle':'Full byte strings, independently grouped; manifest hashes checked'},indent=2))
