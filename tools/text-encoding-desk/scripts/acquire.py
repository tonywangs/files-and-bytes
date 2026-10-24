"""Reacquire pinned upstream originals and verify before writing."""
import hashlib,json,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1]
for r in json.loads((root/'demo/sources.json').read_text()):
 b=urllib.request.urlopen(r['url'],timeout=30).read()
 assert hashlib.sha256(b).hexdigest()==r['sha256'],r['name']
 (root/'demo'/r['name']).write_bytes(b)
 print(r['name'],len(b),r['sha256'])
