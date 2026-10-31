#!/usr/bin/env python3
"""Bounded guest-only X11 input, without activating any Windows host window.

Only use after observing the current guest screen. No daemon or root access.
"""
import argparse
import base64
import ctypes as C
import ctypes.util
import json
import os
from pathlib import Path
import re
import subprocess
import time

root = Path(__file__).resolve().parents[1]
out = root / 'results/live-session'
out.mkdir(parents=True, exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument('action', choices=('inspect', 'key', 'type', 'type64', 'click'))
parser.add_argument('value', nargs='?', default='')
args = parser.parse_args()
if args.action == 'type64':
    args.value = base64.b64decode(args.value, validate=True).decode('ascii')
    args.action = 'type'
status = json.loads((out / 'status.json').read_text())
live = next(x for x in status['firefox'] if not x['headless'])
os.environ.update(live['display'])
x = C.CDLL(ctypes.util.find_library('X11'))
t = C.CDLL(ctypes.util.find_library('Xtst'))
x.XOpenDisplay.argtypes = [C.c_char_p]
x.XOpenDisplay.restype = C.c_void_p
x.XGetInputFocus.argtypes = [C.c_void_p, C.POINTER(C.c_ulong), C.POINTER(C.c_int)]
x.XFetchName.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(C.c_char_p)]
x.XQueryTree.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(C.c_ulong), C.POINTER(C.c_ulong),
                       C.POINTER(C.POINTER(C.c_ulong)), C.POINTER(C.c_uint)]
x.XStringToKeysym.argtypes = [C.c_char_p]
x.XStringToKeysym.restype = C.c_ulong
x.XKeysymToKeycode.argtypes = [C.c_void_p, C.c_ulong]
x.XKeysymToKeycode.restype = C.c_uint
x.XKeycodeToKeysym.argtypes = [C.c_void_p, C.c_uint, C.c_int]
x.XKeycodeToKeysym.restype = C.c_ulong
x.XFlush.argtypes = [C.c_void_p]
x.XFree.argtypes = [C.c_void_p]
x.XCloseDisplay.argtypes = [C.c_void_p]
x.XSetInputFocus.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_ulong]
t.XTestFakeKeyEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
t.XTestFakeButtonEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
t.XTestFakeMotionEvent.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_ulong]
display = x.XOpenDisplay(None)
if not display:
    raise RuntimeError('Guest X11 display unavailable')

try:
    focus, revert = C.c_ulong(), C.c_int()
    x.XGetInputFocus(display, C.byref(focus), C.byref(revert))
    # VMware can leave X input at PointerRoot when its host console is not
    # focused. GNOME still identifies the active guest window; only target that
    # verified Firefox window, without invoking any Windows window operation.
    target = focus.value
    if target <= 1:
        prop = subprocess.run(['xprop', '-root', '_NET_ACTIVE_WINDOW'], env=os.environ,
                              capture_output=True, text=True, timeout=5)
        match = re.search(r'0x[0-9a-fA-F]+', prop.stdout)
        target = int(match.group(0), 16) if match else 0
    titles = []
    props = subprocess.run(['xprop', '-id', hex(target), '_NET_WM_NAME', 'WM_NAME', 'WM_CLASS', '_NET_WM_STATE'],
                           env=os.environ, capture_output=True, text=True, timeout=5)
    client_prop = subprocess.run(['xprop', '-root', '_NET_CLIENT_LIST_STACKING'], env=os.environ,
                                capture_output=True, text=True, timeout=5)
    firefox_clients = []
    for client in re.findall(r'0x[0-9a-fA-F]+', client_prop.stdout):
        info = subprocess.run(['xprop', '-id', client, '_NET_WM_NAME', 'WM_NAME', 'WM_CLASS', '_NET_WM_PID', '_NET_WM_STATE'],
                              env=os.environ, capture_output=True, text=True, timeout=5).stdout
        if re.search(r'WM_CLASS.*firefox', info, re.IGNORECASE):
            firefox_clients.append({'window': int(client, 16), 'properties': info.strip()})
    owned = [client for client in firefox_clients if
             re.search(r'_NET_WM_PID\(CARDINAL\) = ' + str(live['pid']) + r'\b', client['properties'])]
    focused = [client for client in owned if '_NET_WM_STATE_FOCUSED' in client['properties']]
    # GTK file choosers can mark both their parent and the active modal as
    # focused. Prefer the one modal belonging to this same Firefox process.
    # A non-Firefox application or multiple competing dialogs still fail closed.
    focused_modals = [client for client in focused if '_NET_WM_STATE_MODAL' in client['properties']]
    if len(focused) > 1 and len(focused_modals) == 1:
        focused = focused_modals
    if len(focused) == 1:
        target = focused[0]['window']
        props.stdout = focused[0]['properties']
    window = target
    for _ in range(12):
        if window <= 1:
            break
        name = C.c_char_p()
        if x.XFetchName(display, window, C.byref(name)) and name.value:
            titles.append(name.value.decode(errors='replace'))
            x.XFree(name)
        parent, tree_root, children, count = C.c_ulong(), C.c_ulong(), C.POINTER(C.c_ulong)(), C.c_uint()
        if not x.XQueryTree(display, window, C.byref(tree_root), C.byref(parent), C.byref(children), C.byref(count)):
            break
        if children:
            x.XFree(children)
        if parent.value == window:
            break
        window = parent.value
    report = {'action': args.action, 'focusWindow': focus.value, 'focusTitles': titles, 'windowProperties': props.stdout.strip(),
              'targetWindow': target, 'firefoxClients': firefox_clients,
              'clientList': client_prop.stdout.strip(), 'inputSent': False}
    if args.action != 'inspect':
        if len(focused) != 1:
            raise RuntimeError('Firefox is not the focused guest application; no input sent')
        if focus.value != target:
            x.XSetInputFocus(display, target, 2, 0)

        def event(name, down):
            sym = x.XStringToKeysym(name.encode())
            key = x.XKeysymToKeycode(display, sym)
            if not key:
                raise RuntimeError('Unsupported key')
            t.XTestFakeKeyEvent(display, key, int(down), 0)

        if args.action == 'key':
            keys = args.value.split('+')
            for name in keys:
                event(name, True)
            for name in reversed(keys):
                event(name, False)
        elif args.action == 'type':
            if len(args.value) > 2048 or not args.value.isascii() or any(ord(c) < 32 for c in args.value):
                raise ValueError('Only bounded printable ASCII input is supported')
            for char in args.value:
                sym = ord(char)
                key = x.XKeysymToKeycode(display, sym)
                shift = x.XKeycodeToKeysym(display, key, 0) != sym
                if shift and x.XKeycodeToKeysym(display, key, 1) != sym:
                    raise ValueError('Unsupported guest keyboard layout')
                if shift:
                    event('Shift_L', True)
                t.XTestFakeKeyEvent(display, key, 1, 0)
                t.XTestFakeKeyEvent(display, key, 0, 0)
                if shift:
                    event('Shift_L', False)
                x.XFlush(display)
                time.sleep(0.01)
        elif args.action == 'click':
            px, py = (int(v) for v in args.value.split(','))
            t.XTestFakeMotionEvent(display, -1, px, py, 0)
            t.XTestFakeButtonEvent(display, 1, 1, 0)
            t.XTestFakeButtonEvent(display, 1, 0, 0)
        x.XFlush(display)
        report['inputSent'] = True
    (out / 'input-status.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
finally:
    x.XCloseDisplay(display)
