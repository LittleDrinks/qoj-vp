#!/usr/bin/env python3
"""One task per native process. stdout contains only Firefox native frames."""

from __future__ import annotations

import json
import os
import struct
import sys
import uuid

from native_core import ProtocolError, StateStore, dispatch


MAX_INCOMING_BYTES = 96 * 1024 * 1024
MAX_OUTGOING_BYTES = 1024 * 1024


def read_exact(stream, count, clean_eof=False):
    data = bytearray()
    while len(data) < count:
        part = stream.read(count - len(data))
        if not part:
            if clean_eof and not data:
                return None
            raise ProtocolError("Native stream ended inside a frame")
        data.extend(part)
    return bytes(data)


def read_frame(stream):
    header = read_exact(stream, 4, clean_eof=True)
    if header is None:
        return None
    length = struct.unpack("<I", header)[0]
    if length < 2 or length > MAX_INCOMING_BYTES:
        raise ProtocolError("Native frame size is outside the preflight limit")
    try:
        value = json.loads(read_exact(stream, length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Native frame must contain UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("Native message must be an object")
    return value


def write_frame(stream, message):
    encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_OUTGOING_BYTES:
        raise ProtocolError("Outgoing message exceeds Firefox native message limit")
    stream.write(struct.pack("<I", len(encoded)))
    stream.write(encoded)
    stream.flush()


def serve_once(source, sink):
    task_id = None
    store = None
    try:
        task = read_frame(source)
        if task is None:
            return 0
        if task.get("type") != "task" or not isinstance(task.get("id"), str) or not task["id"] or len(task["id"]) > 120:
            raise ProtocolError("Expected a task envelope with a short string id")
        task_id = task["id"]
        method = task.get("method")
        if not isinstance(method, str):
            raise ProtocolError("Task method must be a string")
        store = StateStore()

        def exchange(request):
            request_id = str(uuid.uuid4())
            write_frame(sink, {"type": "http.request", "id": task_id, "requestId": request_id, "request": request})
            reply = read_frame(source)
            if reply is None:
                raise ProtocolError("Browser disconnected during an HTTP request")
            if reply.get("type") != "http.response" or reply.get("id") != task_id or reply.get("requestId") != request_id:
                raise ProtocolError("Unexpected HTTP response envelope")
            return reply

        result = dispatch(method, task.get("args", {}), exchange, store)
        store.trace("task.completed", {"id": task_id, "method": method, "pid": os.getpid()})
        store.close()
        store = None
        write_frame(sink, {"type": "result", "id": task_id, "ok": True, "pid": os.getpid(), "result": result})
        return 0
    except (BrokenPipeError, EOFError):
        return 1
    except Exception as exc:
        # Error text comes from our contracts/QOJ library; never attach raw
        # messages, cookies, HTML, CSRF values, or exception local variables.
        try:
            error = {"code": type(exc).__name__, "message": str(exc)}
            cause = exc
            for _ in range(8):
                if cause is None:
                    break
                details = getattr(cause, "preflight_error", None)
                if isinstance(details, dict):
                    error["details"] = details
                    break
                cause = cause.__cause__
            write_frame(sink, {"type": "result", "id": task_id, "ok": False, "pid": os.getpid(), "error": error})
        except (BrokenPipeError, ProtocolError):
            pass
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(serve_once(sys.stdin.buffer, sys.stdout.buffer))
