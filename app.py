"""Loopback-only, stateless strict text conversion workbench."""
import os
import base64, hashlib, io, json, re, zipfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
CODECS = ['utf-8', 'utf-16-le', 'utf-16-be', 'windows-1252', 'iso-8859-1', 'cp1251', 'koi8-r']
PORT = int(os.environ.get("PORT", "8765"))
LIMIT = 2 * 1024 * 1024
ROOT = Path(__file__).parent

def digest(b): return hashlib.sha256(b).hexdigest()
def unpack(f):
    b = base64.b64decode(f['data'], validate=True)
    if len(b) > LIMIT: raise ValueError('File exceeds 2 MiB')
    if digest(b) != f['hash']: raise ValueError('Source hash mismatch; reconnect the original file')
    return b

def decode(b, codec):
    if codec not in CODECS: raise ValueError('Unsupported codec')
    return b.decode(codec, errors='strict')  # BOM is retained as a Unicode character.

def inspect(f):
    b = unpack(f); previews = {}
    for codec in CODECS:
        try:
            s = decode(b, codec)
            previews[codec] = dict(text=s[:12000], characters=len(s), literal_replacements=s.count('\ufffd'))
        except UnicodeDecodeError as e:
            previews[codec] = dict(error=e.reason, start=e.start, end=e.end)
    offset = max(0, min(int(f.get('offset', 0)), len(b)))
    return dict(hash=digest(b), bytes=len(b), previews=previews, offset=offset,
                hex='\n'.join(f'{i:08x}  '+b[i:i+16].hex(' ') for i in range(offset, min(offset+256,len(b)),16)))

def export(files):
    if not isinstance(files,list) or not 1 <= len(files) <= 32: raise ValueError('Submit 1–32 files')
    if not all(isinstance(f,dict) for f in files): raise ValueError('Invalid file record')
    if sum(len(base64.b64decode(f.get('data',''),validate=True)) for f in files) > 8*1024*1024: raise ValueError('Batch exceeds 8 MiB')
    if sum(len(f.get('data','')) for f in files) > 12*1024*1024: raise ValueError('Batch exceeds 8 MiB encoded allowance')
    buf=io.BytesIO(); records=[]
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        for i,f in enumerate(files):
            r=dict(name=f.get('name',''), source_hash=f.get('hash'), codec=f.get('codec'), bom_policy='retain all decoded code points; no added BOM')
            records.append(r)
            if f.get('excluded'):
                r['status']='excluded'; continue
            if f.get('codec') not in CODECS:
                r.update(status='unsupported',error='Explicit supported encoding decision required'); continue
            try:
                b=unpack(f); s=decode(b,f['codec']); out=s.encode('utf-8','strict')
                assert out.decode('utf-8','strict') == s
                name=f"{i+1:03d}-"+re.sub(r'[^a-zA-Z0-9._-]', '_',str(f.get('name','text')))[:100]+'.utf8.txt'
                z.writestr(name,out)
                r.update(status='converted',output=name,source_bytes=len(b),output_bytes=len(out),output_hash=digest(out),verification='UTF-8 decoded code points equal selected source interpretation')
            except (ValueError,KeyError,TypeError) as e: r.update(status='failed',error=str(e))
        manifest=dict(version=1,complete=all(r['status'] in ('converted','excluded') for r in records),files=records)
        z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=True,indent=2))
    return buf.getvalue()

class Handler(BaseHTTPRequestHandler):
    def send(self,code,data,typ):
        self.send_response(code); self.send_header('Content-Type',typ); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        paths={'/':'static/index.html','/app.js':'static/app.js','/demo/sources.json':'demo/sources.json'}
        for row in json.loads((ROOT/'demo/sources.json').read_text()): paths['/demo/'+row['name']]='demo/'+row['name']
        if self.path not in paths: return self.send(404,b'Not found','text/plain')
        p=ROOT/paths[self.path]
        typ='text/html; charset=utf-8' if self.path=='/' else 'text/javascript; charset=utf-8' if self.path=='/app.js' else 'application/octet-stream'
        self.send(200,p.read_bytes(),typ)
    def do_POST(self):
        try:
            if self.headers.get('Origin') not in (None,f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'): raise ValueError('Foreign origin rejected')
            n=int(self.headers.get('Content-Length','0'))
            if not 0 < n <= 13*1024*1024: raise ValueError('Request exceeds 13 MiB limit')
            f=json.loads(self.rfile.read(n))
            if self.path=='/inspect': self.send(200,json.dumps(inspect(f)).encode(),'application/json')
            elif self.path=='/export': self.send(200,export(f),'application/zip')
            else: self.send(404,b'Not found','text/plain')
        except (ValueError,KeyError,TypeError) as e: self.send(400,str(e).encode(),'text/plain')

if __name__=='__main__':
    print(f'Open http://127.0.0.1:{PORT} — Ctrl+C to stop',flush=True)
    HTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
