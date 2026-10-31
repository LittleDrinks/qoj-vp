#!/usr/bin/env python3
"""Bounded reference-only relay from a WSL private interface to local DOMjudge.

This is QA transport, not a product service. No headers, credentials, query
strings or bodies are logged. The upstream is fixed to the owned reference.
"""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time

parser = argparse.ArgumentParser()
parser.add_argument('--bind', required=True)
parser.add_argument('--port', type=int, default=19082)
parser.add_argument('--max-seconds', type=int, default=1800)
args = parser.parse_args()
HOP = {'connection', 'transfer-encoding', 'keep-alive', 'proxy-authenticate',
       'proxy-authorization', 'te', 'trailers', 'upgrade'}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def relay(self):
        if not self.path.startswith('/') or self.path.startswith('//'):
            self.send_error(400)
            return
        length = int(self.headers.get('Content-Length', 0))
        if length > 16 * 1024 * 1024:
            self.send_error(413)
            return
        connection = http.client.HTTPConnection('127.0.0.1', 19081, timeout=30)
        try:
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            body = self.rfile.read(length) if length else None
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in HOP | {'content-length'}:
                    self.send_header(key, value)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Connection', 'close')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data)
        except (OSError, http.client.HTTPException):
            self.send_error(502, 'Reference relay failed')
        finally:
            connection.close()

    do_GET = do_POST = do_HEAD = relay


server = ThreadingHTTPServer((args.bind, args.port), Handler)
server.timeout = 0.5
deadline = time.monotonic() + args.max_seconds
print(f'Reference relay ready on {args.bind}:{args.port}; bounded lifetime {args.max_seconds}s', flush=True)
try:
    while time.monotonic() < deadline:
        server.handle_request()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
    print('Reference relay stopped', flush=True)
