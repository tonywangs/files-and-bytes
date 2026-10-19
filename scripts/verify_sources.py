#!/usr/bin/env python3
"""Verify vendored real inputs; --fetch reproduces their acquisition exactly."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def verify(fetch=False):
    manifest = json.loads((ROOT/'demo/provenance.json').read_text())
    for item in manifest['files']:
        path = ROOT/'demo/source'/item['file']
        data = urllib.request.urlopen(item['url'], timeout=30).read() if fetch else path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == item['sha256'], item['file']
        if fetch:
            path.write_bytes(data)
    print(f"Verified {len(manifest['files'])} pinned files, including MIT license")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--fetch', action='store_true')
    verify(parser.parse_args().fetch)
