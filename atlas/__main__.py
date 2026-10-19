import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .scan import scan, open_root
from .report import html, web_safe


def main():
    p = argparse.ArgumentParser(description='Scan only an explicitly selected folder; no file contents read.')
    p.add_argument('root', type=Path)
    p.add_argument('--port', type=int, default=4173)
    p.add_argument('--max-entries', type=int, default=20000)
    p.add_argument('--max-depth', type=int, default=64)
    p.add_argument('--max-seconds', type=float, default=30)
    p.add_argument('--exclude', action='append', default=[], help='Exact basename; repeatable')
    p.add_argument('--output', type=Path, help='Write JSON and HTML snapshots then exit; choose outside scan root')
    args = p.parse_args()
    root = str(args.root.absolute())
    options = dict(max_entries=args.max_entries, max_depth=args.max_depth, max_seconds=args.max_seconds, exclude=args.exclude)
    if not 1 <= args.max_entries <= 50000 or not 0 <= args.max_depth <= 128 or not 0 < args.max_seconds <= 300:
        p.error('Limits: entries 1..50000, depth 0..128, seconds >0..300')
    if args.output:
        dest = args.output.absolute()
        if any(dest.with_suffix(suffix).resolve().is_relative_to(args.root.resolve()) for suffix in ('.json', '.html')):
            p.error('Output must be outside selected root')
        if any(dest.with_suffix(suffix).exists() or dest.with_suffix(suffix).is_symlink() for suffix in ('.json', '.html')):
            p.error('Output already exists; choose a new output prefix')
        r = scan(root, **options)
        dest.parent.mkdir(parents=True, exist_ok=True)
        output_fd = open_root(dest.parent)
        try:
            for suffix, data in (('.json', json.dumps(r, indent=2)), ('.html', html(r))):
                fd = os.open(dest.with_suffix(suffix).name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=output_fd)
                with os.fdopen(fd, 'w') as stream:
                    stream.write(data)
        finally:
            os.close(output_fd)
        print(json.dumps(dict(complete=r['complete'], counts=r['counts'], totals=r['totals'])))
        return
    lock = threading.Lock()
    state = dict(running=False, report=None, error=None)
    cancel = threading.Event()

    def worker():
        try:
            r = scan(root, cancel=cancel, **options)
            with lock:
                state.update(report=r, running=False)
        except Exception as exc:
            with lock:
                state.update(error=str(exc), running=False)

    class Handler(BaseHTTPRequestHandler):
        def reply(self, value, code=200, content_type='application/json'):
            data = value.encode() if isinstance(value, str) else json.dumps(web_safe(value)).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type+'; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def allowed(self):
            # Loopback only, strict Host and Origin prevent drive-by requests / DNS rebinding.
            expected = f'127.0.0.1:{self.server.server_port}'
            return self.headers.get('Host') == expected and self.headers.get('Origin', 'http://'+expected) == 'http://'+expected

        def do_GET(self):
            if not self.allowed():
                return self.reply({'error': 'Invalid host or origin'}, 403)
            if self.path == '/':
                return self.reply(html(), content_type='text/html')
            if self.path == '/api/config':
                return self.reply(dict(root=root, **options))
            if self.path == '/api/state':
                with lock:
                    return self.reply(state)
            self.reply({'error': 'Not found'}, 404)

        def do_POST(self):
            if not self.allowed():
                return self.reply({'error': 'Invalid host or origin'}, 403)
            if self.path == '/api/cancel':
                cancel.set()
                return self.reply({'ok': True})
            if self.path == '/api/scan':
                with lock:
                    if state['running']:
                        return self.reply({'error': 'Scan already running'}, 409)
                    state.update(running=True, error=None, report=None)
                    cancel.clear()
                    threading.Thread(target=worker, daemon=True).start()
                return self.reply({'ok': True})
            self.reply({'error': 'Not found'}, 404)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Folder Space Atlas: http://127.0.0.1:{server.server_port}\nSelected root: {root}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        cancel.set()
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
