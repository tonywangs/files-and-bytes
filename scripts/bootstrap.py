#!/usr/bin/env python3
"""Build pinned upstream PAR2 locally without root or global installs."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tarfile
from urllib.request import urlopen
ROOT = Path(__file__).resolve().parents[1]
URL = 'https://github.com/Parchive/par2cmdline/releases/download/v0.8.1/par2cmdline-0.8.1.tar.gz'
SHA256 = '7b2fcc19b54c7080939fc2cbaca33ae40ac33759a526292933c94a85ba850d11'
def main():
    tools = ROOT / '.tools'
    binary = tools / 'installed/bin/par2'
    if binary.exists():
        subprocess.run([str(binary), '-V'], check=True, timeout=5)
        return
    for tool in ['g++', 'make']:
        if not shutil.which(tool):
            raise SystemExit(f'Missing {tool}. Install a C++ compiler and make using your OS package manager.')
    tools.mkdir(exist_ok=True)
    archive = tools / 'par2cmdline-0.8.1.tar.gz'
    with urlopen(URL, timeout=60) as response:
        raw = response.read(5 * 1024**2)
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise SystemExit('Upstream archive hash mismatch; refusing build')
    archive.write_bytes(raw)
    with tarfile.open(archive) as tf:
        # Archive hash is fixed; reject links/traversal independently too.
        for member in tf.getmembers():
            dest = (tools / member.name).resolve()
            if not dest.is_relative_to(tools.resolve()) or not (member.isfile() or member.isdir()):
                raise SystemExit(f'Unexpected archive entry: {member.name}')
        tf.extractall(tools, filter='data')
    source = tools / 'par2cmdline-0.8.1'
    for args in [['./configure', '--prefix=' + str(tools / 'installed')], ['make', '-j2'], ['make', 'install']]:
        subprocess.run(args, cwd=source, check=True, timeout=300)
    subprocess.run([str(binary), '-V'], check=True, timeout=5)
if __name__ == '__main__':
    main()
