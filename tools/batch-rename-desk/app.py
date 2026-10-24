#!/usr/bin/env python3
"""Local browser server, using only the Python standard library."""
import argparse
import copy
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import tempfile
import webbrowser

from engine import Desk, Refused, transform

HERE = Path(__file__).resolve().parent


def demo_copy():
    folder = Path(tempfile.mkdtemp(prefix='rename-desk-demo-'))
    for source in (HERE / 'demo/source').glob('*.svg'):
        shutil.copy2(source, folder / source.name)
    return folder


def serve(folder, port=0, open_browser=False):
    desk = Desk(folder)
    token = secrets.token_urlsafe(32)
    snapshots, plans = {}, {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not log the bearer URL.

        def send(self, status, data, content_type='application/json'):
            body = json.dumps(data).encode() if content_type == 'application/json' else data
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def safe_request(self):
            host = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != host:
                raise Refused('Invalid Host')
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + host:
                raise Refused('Cross-origin requests refused')

        def do_GET(self):
            try:
                self.safe_request()
                asset = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}.get(self.path)
                if not asset:
                    self.send(404, {'error': 'Not found'})
                else:
                    self.send(200, (HERE/'web'/asset[0]).read_bytes(), asset[1])
            except Refused as exc:
                self.send(403, {'error': str(exc)})

        def do_POST(self):
            try:
                self.safe_request()
                if not secrets.compare_digest(self.headers.get('X-Desk-Token', ''), token):
                    raise Refused('Open the full local launch URL to authorize this browser')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024 * 1024:
                    raise Refused('Invalid request size')
                body = json.loads(self.rfile.read(length))
                with desk.locked():
                    if self.path == '/api/state':
                        rows, skipped = desk.scan()
                        ident = secrets.token_hex(16)
                        snapshots.clear()
                        plans.clear()
                        snapshots[ident] = rows
                        result = dict(folder=desk.path, snapshot=ident, files=rows, skipped=skipped, journals=desk.journals())
                    elif self.path == '/api/preview':
                        rows = copy.deepcopy(snapshots.get(body.get('snapshot')))
                        if rows is None:
                            raise Refused('Folder snapshot expired; refresh the folder')
                        edits = body.get('edits')
                        names = edits if edits is not None else transform([r['source'] for r in rows], body.get('rules', {}))
                        if not isinstance(names, list) or len(names) != len(rows):
                            raise Refused('Every source needs one destination')
                        for row, name in zip(rows, names):
                            row['dest'] = name
                        errors = []
                        try:
                            desk.validate(rows)
                        except (OSError, ValueError) as exc:
                            errors.append(str(exc))
                        ident = secrets.token_hex(16)
                        plans.clear()
                        if not errors:
                            plans[ident] = rows
                        result = dict(rows=rows, errors=errors, plan=ident if not errors else None)
                    elif self.path == '/api/apply':
                        rows = plans.pop(body.get('plan'), None)
                        if rows is None:
                            raise Refused('Validate the displayed preview before applying')
                        result = desk.apply(rows)
                    elif self.path == '/api/undo':
                        result = desk.undo(body.get('id'))
                    else:
                        self.send(404, {'error': 'Not found'})
                        return
                self.send(200, result)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.send(409, {'error': str(exc)})

    server = HTTPServer(('127.0.0.1', port), Handler)
    server.timeout = 30
    url = f'http://127.0.0.1:{server.server_port}/#{token}'
    print(f'Folder: {desk.path}', flush=True)
    print(f'Open {url}', flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        desk.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Inspect, rename, and undo files in one local folder')
    parser.add_argument('--folder', type=Path, help='Existing folder; omit for a fresh disposable real-file demo')
    parser.add_argument('--port', type=int, default=0, help='Loopback port; default chooses a free port')
    parser.add_argument('--open', action='store_true', help='Open the browser automatically')
    args = parser.parse_args()
    serve(args.folder if args.folder is not None else demo_copy(), args.port, args.open)
