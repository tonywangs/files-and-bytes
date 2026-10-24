#!/usr/bin/env python3
"""Enforce publication size/count limits without including ignored local tools."""
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
paths=sorted({n for n in names if n})
assert len(paths)<=1000, len(paths)
total=0
for name in paths:
    p=ROOT/name
    assert p.is_file() and not p.is_symlink(),name
    size=p.stat().st_size
    assert size <= 10*1024**2,(name,size)
    assert not name.endswith('.log') or name=='results/tests.log',name
    assert not any(part in {'.runtime','.tools','node_modules','.venv','.agents','.codex'} for part in p.relative_to(ROOT).parts),name
    total+=size
assert total<=32*1024**2,total
print(f'Publication limits passed: {len(paths)} files, {total} bytes')
