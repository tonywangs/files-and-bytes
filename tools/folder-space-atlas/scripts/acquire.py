#!/usr/bin/env python3
"""Acquire hash-pinned zlib 1.3.1. No source build or execution."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

BASE = Path(__file__).resolve().parents[1]
URL = 'https://codeload.github.com/madler/zlib/tar.gz/refs/tags/v1.3.1'
SHA = '17e88863f3600672ab49182f217281b6fc4d3c762bde361935e436a95214d05c'
ROOT = BASE / '.demo/zlib-1.3.1'

def hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.rglob('*')) if p.is_file()}

def main():
    manifest = BASE / 'demo/provenance.json'
    if ROOT.exists():
        expected = json.loads(manifest.read_text())['files']
        assert hashes() == expected, 'Demo was modified; move .demo/zlib-1.3.1 aside and reacquire'
        print(f'Existing verified source: {len(expected)} files')
        return
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    assert hashlib.sha256(data).hexdigest() == SHA, 'Archive hash mismatch'
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        members = archive.getmembers()
        assert len(members) < 1000 and sum(m.size for m in members) < 16 * 1024 * 1024
        assert all((m.isfile() or m.isdir()) and (m.name == 'zlib-1.3.1' or m.name.startswith('zlib-1.3.1/')) and '..' not in Path(m.name).parts and m.size < 10*1024*1024 for m in members)
        ROOT.parent.mkdir(exist_ok=True)
        archive.extractall(ROOT.parent, filter='data')
    result = dict(project='zlib', version='1.3.1', commit='51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf',
                  archive_url=URL, archive_sha256=SHA, source_url='https://github.com/madler/zlib/tree/51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf',
                  license_url='https://github.com/madler/zlib/blob/51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf/LICENSE',
                  license='zlib; individual contrib files may carry additional notices, retained in source', files=hashes())
    if manifest.exists():
        assert result == json.loads(manifest.read_text()), 'Source manifest mismatch'
    else:
        manifest.write_text(json.dumps(result, indent=2)+'\n')
    assert (ROOT / 'LICENSE').read_bytes() == (BASE / 'demo/ZLIB-LICENSE').read_bytes()
    print(f'Acquired {len(result["files"])} hash-verified files at {ROOT}')

if __name__ == '__main__':
    main()
