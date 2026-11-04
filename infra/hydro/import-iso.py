#!/usr/bin/env python3
"""Verify ordered bootstrap chunks and combine once, deleting consumed chunks."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
root=Path(sys.argv[1]);manifest=json.loads((root/'iso.json').read_text())
output=root/'hydro.iso';whole=hashlib.sha256()
with output.open('wb') as target:
    for part in manifest['parts']:
        name=part['name']
        assert Path(name).name==name
        path=root/name;digest=hashlib.sha256();size=0
        with path.open('rb') as source:
            while block:=source.read(4*1024*1024):
                digest.update(block);whole.update(block);target.write(block);size+=len(block)
        assert size==part['bytes'] and digest.hexdigest()==part['sha256'],name
        path.unlink()
assert whole.hexdigest()==manifest['sha256']
print(manifest['sha256'])
