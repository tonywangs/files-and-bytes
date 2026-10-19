#!/usr/bin/env python3
"""Check the prospective publishable tree, excluding ignored files."""
import subprocess
from pathlib import Path
names = subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z']).decode().split('\0')
files = sorted({Path(n) for n in names if n and Path(n).is_file()})
assert len(files) <= 1000
assert all(p.stat().st_size <= 10*1024*1024 for p in files)
assert sum(p.stat().st_size for p in files) <= 32*1024*1024
assert all(p.suffix != '.log' or str(p) == 'results/tests.log' for p in files)
assert not any(part in ('.demo','node_modules','__pycache__') for p in files for part in p.parts)
print(f'{len(files)} files; {sum(p.stat().st_size for p in files)} bytes; publication size limits passed')
