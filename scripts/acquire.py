"""Reproduce the bounded, unmodified CPython real-input collection."""
import hashlib, json, pathlib, tarfile, urllib.request
URL='https://codeload.github.com/python/cpython/tar.gz/refs/tags/v3.13.0'
def acquire(archive='/tmp/cpython.tar.gz'):
    p=pathlib.Path(archive)
    if not p.exists(): urllib.request.urlretrieve(URL,p)
    if hashlib.sha256(p.read_bytes()).hexdigest()!='d2c5dbd73111a80ee654489eb0f52b663b38ef9ce9e9323312515d941d0dfaa2': raise ValueError('Archive hash mismatch; refusing unpinned input')
    out=pathlib.Path('demo'); out.mkdir(exist_ok=True)
    records=[]
    with tarfile.open(p) as t:
        members=sorted([m for m in t.getmembers() if m.isfile() and '/Lib/test/' in m.name and m.size<=16000],key=lambda m:m.name)[:450]
        members += [t.getmember('cpython-3.13.0/LICENSE')]
        for m in members:
            rel=m.name.split('/',1)[1]; data=t.extractfile(m).read()
            dest=out/rel; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(data)
            records.append({'path':rel,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'url':'https://github.com/python/cpython/blob/v3.13.0/'+rel})
    (out/'provenance.json').write_text(json.dumps({'source':URL,'revision':'v3.13.0','archive_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'license':'LICENSE (PSF license and included notices)','selection':'First 450 lexicographically sorted regular Lib/test files <=16000 bytes; unchanged, no added controls','files':records},indent=2)+'\n')
if __name__=='__main__': acquire()
