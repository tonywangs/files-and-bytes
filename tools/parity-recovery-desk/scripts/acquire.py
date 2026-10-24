#!/usr/bin/env python3
"""Fetch a fixed, unmodified real artwork subset; fail on upstream byte changes."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
ROOT = Path(__file__).resolve().parents[1]
REV = '7a3dad4a4da30497093dab22eafba135f02308e1'
NAMES = ['1f600.svg', '1f680.svg', '1f308.svg', '1f333.svg', '1f419.svg', '1f30d.svg', '1f984.svg', '1f4be.svg']
BASE = f'https://raw.githubusercontent.com/twitter/twemoji/{REV}/'
def main():
    target = ROOT / 'data/twemoji'
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = ROOT / 'data/sources.json'
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    records = []
    for name in [*NAMES, 'LICENSE-GRAPHICS']:
        url = BASE + ('assets/svg/' + name if name.endswith('.svg') else name)
        with urlopen(url, timeout=30) as response:
            raw = response.read(1_000_001)
        assert len(raw) <= 1_000_000
        record = dict(name=name, url=url, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        if previous:
            assert record == next(x for x in previous['files'] if x['name'] == name), name
        (target / name if name.endswith('.svg') else ROOT / 'data' / name).write_bytes(raw)
        records.append(record)
    manifest = dict(collection='Twemoji artwork subset', revision=REV, release='v14.0.2',
                    license='CC-BY-4.0', attribution='Copyright Twitter, Inc and other contributors; graphics by Twitter and contributors.',
                    changes='None. Test mutations are made only on disposable copies.', files=records)
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Acquired and hash-checked {len(NAMES)} SVG artworks and license evidence')
if __name__ == '__main__':
    main()
