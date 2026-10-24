"""Loopback-only browser server. No third-party runtime Python packages."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import threading
import urllib.parse
from .core import Engine, ROOT, DeskError, inventory, read_file, require, safe_name

class App:
    def __init__(self, engine):
        self.engine = engine
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.job = {'state': 'idle'}

    def start(self, action, args):
        require(self.lock.acquire(blocking=False), 'Another operation is running; wait or cancel it')
        self.engine.cancel.clear()
        self.engine.published = False
        self.job = {'state': 'running', 'action': action}
        def execute():
            try:
                calls = {
                    'create': lambda: self.engine.create(args.get('names'), args.get('redundancy'), args.get('block_size')),
                    'import': lambda: self.engine.import_package(args.get('directory', '')),
                    'verify': lambda: self.engine.evaluate(args.get('package_id'), args.get('candidate', ''), False, args.get('recovery_folder')),
                    'repair': lambda: self.engine.evaluate(args.get('package_id'), args.get('candidate', ''), True, args.get('recovery_folder')),
                    'demo': lambda: self.engine.damage_demo(args.get('package_id'), args.get('scenario')),
                }
                require(action in calls, 'Unknown action')
                result = calls[action]()
                self.job = {'state': 'done', 'action': action, 'result': result}
            except Exception as e:
                self.job = {'state': 'error', 'action': action, 'error': str(e)}
            finally:
                self.lock.release()
        threading.Thread(target=execute, daemon=True).start()
        return {'state': 'running'}

def make_server(engine, port=8765):
    app = App(engine)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def respond(self, body, content='application/json', code=200, extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header('Content-Type', content)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            for k,v in (extra or {}).items():
                self.send_header(k,v)
            self.end_headers()
            self.wfile.write(body)
        def guard(self, mutation=False):
            require(self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}', 'Open using the printed 127.0.0.1 URL')
            origin = self.headers.get('Origin')
            require(not origin or origin == f'http://127.0.0.1:{self.server.server_port}', 'Cross-origin request rejected')
            require(self.headers.get('Sec-Fetch-Site') not in {'cross-site'}, 'Cross-site request rejected')
            if mutation:
                require(secrets.compare_digest(self.headers.get('X-Desk-Token', ''), app.token), 'Missing local session token')
                require(self.headers.get('Content-Type') == 'application/json', 'Expected JSON')
        def do_GET(self):
            try:
                self.guard()
                url = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(url.query)
                if url.path == '/api/state':
                    packages = []
                    for f in sorted(engine.workspace.glob('package-*/manifest.json'), key=lambda f:f.stat().st_mtime, reverse=True):
                        m = json.loads(f.read_text())
                        packages.append(m)
                    self.respond(dict(token=app.token, source=str(engine.source), tool_version=engine.tool_version,
                                      files=inventory(engine.source), packages=packages, job=app.job))
                elif url.path == '/api/job':
                    self.respond(app.job)
                elif url.path == '/download':
                    kind = query.get('kind', [''])[0]
                    ident = query.get('id', [''])[0]
                    name = safe_name(query.get('name', [''])[0])
                    if kind == 'package':
                        p, _ = engine.package(ident)
                        path = p / 'recovery' / name
                        require(name.endswith('.par2'), 'Not a recovery file')
                        content = 'application/octet-stream'
                    else:
                        import re
                        require(re.fullmatch(r'(verify|repair)-[0-9a-f]{32}', ident) is not None, 'Invalid report ID')
                        p = engine.workspace / ident
                        report = json.loads((p / 'report.json').read_text())
                        if kind == 'report':
                            require(name in {'report.json','report.html'}, 'Invalid report name')
                            path = p / name
                            content = 'text/html; charset=utf-8' if name.endswith('.html') else 'application/json'
                        elif kind == 'restored':
                            require(report['status'] == 'verified-restored' and name in {r['name'] for r in report['output_files']}, 'No verified restored file')
                            path = p / 'restored' / name
                            content = 'application/octet-stream'
                        else:
                            raise DeskError('Invalid download kind')
                    self.respond(read_file(path, 64 * 1024**2), content, extra={'Content-Disposition': f'attachment; filename="{name}"'})
                elif url.path.startswith('/art/'):
                    name = safe_name(url.path[5:])
                    require(name in {r['name'] for r in inventory(ROOT / 'data/twemoji')}, 'Unknown artwork')
                    self.respond(read_file(ROOT / 'data/twemoji' / name), 'image/svg+xml')
                elif url.path in {'/', '/app.js', '/style.css'}:
                    path = ROOT / 'static' / ('index.html' if url.path == '/' else url.path[1:])
                    self.respond(path.read_bytes(), {'/':'text/html; charset=utf-8','/app.js':'text/javascript','/style.css':'text/css'}[url.path])
                else:
                    self.respond({'error':'Not found'}, code=404)
            except Exception as e:
                self.respond({'error':str(e)}, code=400)
        def do_POST(self):
            try:
                self.guard(True)
                size = int(self.headers.get('Content-Length', '0'))
                require(0 <= size <= 16384, 'Request too large')
                args = json.loads(self.rfile.read(size))
                require(isinstance(args, dict), 'Expected object')
                action = self.path.removeprefix('/api/')
                if self.path == '/api/cancel':
                    accepted = engine.request_cancel()
                    self.respond({'cancel_requested':accepted, 'message':'Cancellation requested' if accepted else 'Operation already committed; verified output is retained'})
                else:
                    self.respond(app.start(action, args), code=202)
            except Exception as e:
                self.respond({'error':str(e)}, code=400)
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.app = app
    return server

def main():
    parser = argparse.ArgumentParser(description='Local-only PAR2 recovery desk')
    parser.add_argument('--source', default=str(ROOT / 'data/twemoji'))
    parser.add_argument('--workspace', default=str(ROOT / '.runtime'))
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    engine = Engine(args.workspace, args.source)
    server = make_server(engine, args.port)
    print(f'Parity Recovery Desk: http://127.0.0.1:{server.server_port}\nSource: {engine.source}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        engine.cancel.set()
    finally:
        server.server_close()
if __name__ == '__main__':
    main()
