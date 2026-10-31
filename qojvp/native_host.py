"""Firefox Native Messaging host: exactly one task, then exit."""
from __future__ import annotations

import contextlib
import json
import os
import struct
import sys
import uuid

from .application import Application, ApplicationError

MAX_INCOMING = 96 * 1024 * 1024
MAX_OUTGOING = 1024 * 1024


class ProtocolError(Exception):
    pass


def read_exact(stream, count, *, eof_ok=False):
    data = bytearray()
    while len(data) < count:
        part = stream.read(count - len(data))
        if not part:
            if not data and eof_ok:
                return None
            raise ProtocolError('Native connection ended inside a message')
        data.extend(part)
    return bytes(data)


def read_frame(stream):
    header = read_exact(stream, 4, eof_ok=True)
    if header is None:
        return None
    length = struct.unpack('<I', header)[0]
    if not 2 <= length <= MAX_INCOMING:
        raise ProtocolError('Native message exceeds the accepted size')
    try:
        value = json.loads(read_exact(stream, length).decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtocolError('Expected a UTF-8 JSON native message') from exc
    if not isinstance(value, dict):
        raise ProtocolError('Expected an object native message')
    return value


def write_frame(stream, message):
    data = json.dumps(message, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(data) > MAX_OUTGOING:
        raise ProtocolError('Result exceeds the Firefox native-message limit')
    stream.write(struct.pack('<I', len(data)))
    stream.write(data)
    stream.flush()


def serve_once(source, sink):
    task_id = None
    app = None
    try:
        message = read_frame(source)
        if message is None:
            return 0
        if (message.get('type') != 'task' or not isinstance(message.get('id'), str)
                or not 0 < len(message['id']) <= 120 or not isinstance(message.get('method'), str)):
            raise ProtocolError('Expected a task envelope')
        task_id = message['id']
        app = Application()

        def exchange(request):
            request_id = str(uuid.uuid4())
            write_frame(sink, {'type': 'http.request', 'id': task_id, 'requestId': request_id, 'request': request})
            reply = read_frame(source)
            if (reply is None or reply.get('type') != 'http.response' or reply.get('id') != task_id
                    or reply.get('requestId') != request_id):
                raise ProtocolError('Native HTTP response did not match the current request')
            return reply

        # Libraries may print human progress. Never let it corrupt native frames.
        with contextlib.redirect_stdout(sys.stderr):
            result = app.dispatch(message['method'], message.get('args', {}), exchange)
        write_frame(sink, {'type': 'result', 'id': task_id, 'ok': True, 'pid': os.getpid(), 'result': result})
        return 0
    except Exception as exc:
        code = exc.code if isinstance(exc, ApplicationError) else 'PROTOCOL_ERROR' if isinstance(exc, ProtocolError) else 'INTERNAL_ERROR'
        # Internal exception text might contain provider HTML or request data.
        public_message = str(exc) if isinstance(exc, (ApplicationError, ProtocolError)) else 'The helper could not complete this task'
        try:
            write_frame(sink, {'type': 'result', 'id': task_id, 'ok': False, 'pid': os.getpid(),
                               'error': {'code': code, 'message': public_message}})
        except (BrokenPipeError, ProtocolError):
            pass
        return 1
    finally:
        if app:
            app.close()


if __name__ == '__main__':
    raise SystemExit(serve_once(sys.stdin.buffer, sys.stdout.buffer))
