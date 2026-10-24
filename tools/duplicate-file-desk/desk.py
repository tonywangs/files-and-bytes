"""Local read-only duplicate inspection. Python standard library only."""
import argparse, collections, datetime, hashlib, html, json, os, pathlib, secrets, stat
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
CHUNK=1024*1024
MAX_ENTRIES=20000
MAX_BYTES=4*1024**3

def identity(s): return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def checked(path, expected):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    f=os.fdopen(fd,'rb')
    if not stat.S_ISREG(os.fstat(fd).st_mode) or identity(os.fstat(fd))!=expected:
        f.close(); raise ValueError('Source identity changed')
    return f

def digest(e):
    h=hashlib.sha256()
    with checked(e['path'],e['identity']) as f:
        while b:=f.read(CHUNK): h.update(b)
        if identity(os.fstat(f.fileno()))!=e['identity']: raise ValueError('Changed while hashing')
    return h.hexdigest()

def equal(a,b):
    with checked(a['path'],a['identity']) as x, checked(b['path'],b['identity']) as y:
        while True:
            p=x.read(CHUNK); q=y.read(CHUNK)
            if p!=q: return False
            if not p: break
        if identity(os.fstat(x.fileno()))!=a['identity'] or identity(os.fstat(y.fileno()))!=b['identity']: raise ValueError('Changed while comparing')
    return True

def scan(roots):
    if not roots or len(roots)>32: raise ValueError('Select 1–32 folders')
    roots=list(dict.fromkeys(os.path.abspath(os.path.expanduser(r)) for r in roots))
    entries=[]; seen=set(); total=0; stopped=False; dirs=[]
    def walk(p):
        nonlocal total,stopped
        if p in seen:return
        seen.add(p)
        if len(entries)>=MAX_ENTRIES:
            stopped=True; return
        e={'path':p}; entries.append(e)
        try:
            s=os.lstat(p); e['identity']=identity(s)
            if stat.S_ISLNK(s.st_mode): e.update(status='skipped',reason='Symbolic link not followed');return
            if stat.S_ISDIR(s.st_mode):
                e.update(status='skipped',reason='Directory');dirs.append(e)
                with os.scandir(p) as it:
                    for child in it:
                        walk(child.path)
                        if stopped:break
            elif stat.S_ISREG(s.st_mode):
                if total+s.st_size>MAX_BYTES: e.update(status='failed',reason='4 GiB scan budget exceeded');return
                total+=s.st_size;e.update(status='pending',size=s.st_size,links=s.st_nlink)
            else:e.update(status='skipped',reason='Not a regular file')
        except (OSError,ValueError) as ex:e.update(status='failed',reason=str(ex))
    for root in roots:
        if not os.path.isdir(root) or os.path.islink(root): raise ValueError('Roots must be real directories: '+root)
        walk(root)
    sizes=collections.defaultdict(list)
    for e in entries:
        if e['status']=='pending':sizes[e['size']].append(e)
    groups=[]
    for candidates in sizes.values():
        hashes=collections.defaultdict(list)
        for e in candidates:
            try:e['sha256']=digest(e); hashes[e['sha256']].append(e);e['status']='unique'
            except (OSError,ValueError) as ex:e.update(status='failed',reason=str(ex))
        for bucket in hashes.values():
            partitions=[]
            for e in bucket:
                try:
                    for part in partitions:
                        if equal(part[0],e):part.append(e);break
                    else:partitions.append([e])
                except (OSError,ValueError) as ex:e.update(status='failed',reason=str(ex))
            for part in partitions:
                if len(part)>1:
                    for e in part:e['status']='duplicate'
                    key=hashlib.sha256(json.dumps([(e['path'],e['identity'],e['sha256']) for e in sorted(part,key=lambda e:e['path'])]).encode()).hexdigest()
                    groups.append({'id':key,'sha256':part[0]['sha256'],'size':part[0]['size'],'paths':[e['path'] for e in part],'logical_duplicate_bytes':(len(part)-1)*part[0]['size'],'distinct_inodes':len({tuple(e['identity'][:2]) for e in part}),'verification':'SHA-256 candidates confirmed byte for byte'})
    for e in entries:
        if e['status'] in ('unique','duplicate') or e in dirs:
            try:
                if identity(os.lstat(e['path']))!=e['identity']:raise ValueError('Changed before scan completed')
            except (OSError,ValueError) as ex:e.update(status='failed',reason=str(ex))
    invalid={e['path'] for e in entries if e['status']=='failed'}
    groups=[g for g in groups if not invalid.intersection(g['paths'])]
    valid={p for g in groups for p in g['paths']}
    for e in entries:
        if e['status']=='duplicate' and e['path'] not in valid:e.update(status='failed',reason='Group invalidated by changing member')
    return {'schema':1,'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'roots':roots,'complete':not stopped and not any(e['status']=='failed' for e in entries),'limit_reached':stopped,'entries':entries,'groups':groups,'decisions':{},'consistency':'Best effort, not an atomic snapshot. Re-scan before acting. No source writes.','storage':'Logical duplicate bytes are not recoverable physical storage; hard links, compression, sparse files and snapshots affect allocation.'}

def restore(report,decisions):
    report['decisions']={g['id']:decisions[g['id']] for g in report['groups'] if decisions.get(g['id']) in g['paths']}
    return report

def offline(r):
    payload=json.dumps(r,ensure_ascii=True).replace('<','\\u003c')
    return '<!doctype html><meta charset="utf-8"><title>Duplicate review</title><h1>Duplicate file review</h1><p>'+html.escape(r['consistency'])+'</p><p>Status: '+('COMPLETE' if r['complete'] else 'INCOMPLETE')+'</p><p>'+html.escape(r['storage'])+'</p>'+''.join('<section><h2>'+str(g['size'])+' bytes · '+html.escape(g['sha256'])+'</h2><ul>'+''.join('<li>'+html.escape(p)+(' — RETAIN' if r['decisions'].get(g['id'])==p else '')+'</li>' for p in g['paths'])+'</ul></section>' for g in r['groups'])+'<h2>Full traceable report</h2><pre>'+html.escape(json.dumps(r,indent=2))+'</pre><script type="application/json" id="report">'+payload+'</script>'

def serve(port):
    token=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,data,kind='application/json',code=200):
            if not isinstance(data,bytes):data=data.encode()
            self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
        def trusted(self):
            allowed={f'127.0.0.1:{port}',f'localhost:{port}'}
            return self.headers.get('Host') in allowed and self.headers.get('Origin',f'http://127.0.0.1:{port}') in {f'http://{h}' for h in allowed}
        def do_GET(self):
            if not self.trusted():self.send('{}',code=403);return
            if self.path!='/':self.send('{}',code=404);return
            self.send(pathlib.Path(__file__).with_name('index.html').read_text().replace('__TOKEN__',token),'text/html; charset=utf-8')
        def do_POST(self):
            if not self.trusted() or self.headers.get('X-Desk-Token')!=token:self.send('{}',code=403);return
            try:
                n=int(self.headers.get('Content-Length','0'))
                if n>16*1024**2:raise ValueError('Request too large')
                data=json.loads(self.rfile.read(n))
                if self.path=='/scan':
                    r=restore(scan(data['roots']),data.get('decisions',{}))
                    # Source metadata is optional and explicit, never silently read from user folders.
                    if r['roots']==[str(pathlib.Path('demo/Lib/test').absolute())]:
                        provenance=json.loads(pathlib.Path('demo/provenance.json').read_text())
                        hashes={e['path']:e.get('sha256') for e in r['entries']}
                        if all(hashes.get(str((pathlib.Path('demo')/f['path']).absolute()))==f['sha256'] for f in provenance['files'] if f['path'].startswith('Lib/test/')):
                            r['provenance']=provenance
                    self.send(json.dumps(r))
                elif self.path=='/html':self.send(offline(data),'text/html; charset=utf-8')
                else:self.send('{}',code=404)
            except Exception as ex:self.send(json.dumps({'error':str(ex)}),code=400)
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'Open http://127.0.0.1:{port}',flush=True)
    server.serve_forever()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8765);a=p.parse_args();serve(a.port)
