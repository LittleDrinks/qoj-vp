#!/usr/bin/env python3
"""Read the actual guest X11 framebuffer, independently of VMware captureScreen."""
import ctypes as C
import ctypes.util
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
out = root / 'results/live-session'
status = json.loads((out / 'status.json').read_text())
os.environ.update(next(x['display'] for x in status['firefox'] if not x['headless']))
x = C.CDLL(ctypes.util.find_library('X11'))
x.XOpenDisplay.argtypes = [C.c_char_p]
x.XOpenDisplay.restype = C.c_void_p
x.XDefaultRootWindow.argtypes = [C.c_void_p]
x.XDefaultRootWindow.restype = C.c_ulong
x.XDisplayWidth.argtypes = x.XDisplayHeight.argtypes = [C.c_void_p, C.c_int]
x.XGetImage.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_ulong, C.c_int]
x.XGetImage.restype = C.c_void_p
x.XDestroyImage.argtypes = [C.c_void_p]
x.XCloseDisplay.argtypes = [C.c_void_p]


class XImage(C.Structure):
    _fields_ = [('width', C.c_int), ('height', C.c_int), ('xoffset', C.c_int), ('format', C.c_int),
                ('data', C.c_void_p), ('byte_order', C.c_int), ('bitmap_unit', C.c_int),
                ('bitmap_bit_order', C.c_int), ('bitmap_pad', C.c_int), ('depth', C.c_int),
                ('bytes_per_line', C.c_int), ('bits_per_pixel', C.c_int),
                ('red_mask', C.c_ulong), ('green_mask', C.c_ulong), ('blue_mask', C.c_ulong)]


report = {'capturedAt': datetime.now(timezone.utc).isoformat(), 'source': 'X11-XGetImage', 'clients': []}
display = x.XOpenDisplay(None)
if not display:
    raise RuntimeError('Guest X11 display unavailable')
image = None
try:
    width, height = x.XDisplayWidth(display, 0), x.XDisplayHeight(display, 0)
    image = x.XGetImage(display, x.XDefaultRootWindow(display), 0, 0, width, height, 0xFFFFFFFF, 2)
    if not image:
        raise RuntimeError('Guest X11 capture failed')
    info = C.cast(image, C.POINTER(XImage)).contents
    if (info.bits_per_pixel, info.byte_order, info.red_mask, info.green_mask, info.blue_mask) != (32, 0, 0xFF0000, 0xFF00, 0xFF):
        raise RuntimeError('Unsupported screenshot pixel layout')
    data = C.string_at(info.data, info.bytes_per_line * height)
    rgb = bytearray(width * height * 3)
    dest = 0
    for row in range(height):
        for pos in range(row * info.bytes_per_line, row * info.bytes_per_line + width * 4, 4):
            rgb[dest:dest + 3] = bytes((data[pos + 2], data[pos + 1], data[pos]))
            dest += 3
    (out / 'current-x11.ppm').write_bytes(f'P6\n{width} {height}\n255\n'.encode() + rgb)
    report.update(width=width, height=height)
    prop = subprocess.run(['xprop', '-root', '_NET_CLIENT_LIST_STACKING', '_NET_ACTIVE_WINDOW'],
                          env=os.environ, capture_output=True, text=True, timeout=5).stdout
    for window in dict.fromkeys(re.findall(r'0x[0-9a-fA-F]+', prop)):
        values = subprocess.run(['xprop', '-id', window, 'WM_CLASS', '_NET_WM_PID', '_NET_WM_STATE'],
                                env=os.environ, capture_output=True, text=True, timeout=5).stdout
        report['clients'].append({'window': window, 'properties': values.strip()})
    report['status'] = 'passed'
finally:
    if image:
        x.XDestroyImage(image)
    x.XCloseDisplay(display)
    (out / 'x11-capture.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
