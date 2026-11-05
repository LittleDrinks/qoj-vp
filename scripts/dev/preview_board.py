#!/usr/bin/env python3
"""Serve the actual Board component with a historical SRK, without a native host."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = {
    '/': ('scripts/dev/board-preview.html', 'text/html'),
    '/history.json': ('tests/browser/rankland-fixtures/reference-srk.json', 'application/json'),
    '/engine.js': ('src/firefox/board/generated/engine.js', 'text/javascript'),
    '/view.js': ('src/firefox/board/generated/view.js', 'text/javascript'),
    '/view.css': ('src/firefox/board/generated/view.css', 'text/css'),
    '/bootstrap.css': ('src/firefox/assets/bootstrap/bootstrap.min.css', 'text/css'),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        entry = FILES.get(self.path.split('?', 1)[0])
        if entry is None:
            self.send_error(404); return
        data = (ROOT/entry[0]).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', entry[1]+'; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_): pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
        print(f'Board 预览：http://localhost:{server.server_port}  （Ctrl+C 停止）', flush=True)
        try: server.serve_forever()
        except KeyboardInterrupt: pass


if __name__ == '__main__': main()
