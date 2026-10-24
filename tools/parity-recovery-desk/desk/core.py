"""Bounded local PAR2 workflows. All engine writes happen in fresh owned directories."""
from __future__ import annotations
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import struct
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE = 4 * 1024**2
MAX_TOTAL = 16 * 1024**2
MAX_RECOVERY = 48 * 1024**2
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_. +\-]{0,119}\Z')

class DeskError(ValueError):
    pass

def require(ok, message):
    if not ok:
        raise DeskError(message)

def safe_name(name):
    require(isinstance(name, str) and NAME.fullmatch(name) and not name.endswith(('.', ' ')),
            f'Unsupported flat ASCII filename: {name!r}')
    require(name.split('.')[0].upper() not in {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(10)], *[f'LPT{i}' for i in range(10)]}, 'Reserved filename')
    return name

def directory(path):
    p = Path(os.path.abspath(path))
    for item in [p, *p.parents]:
        require(not item.is_symlink(), f'Links are unsupported: {item}')
    require(p.is_dir(), f'Not a directory: {p}')
    return p

def read_file(path, limit=MAX_FILE):
    """Reject links/special files and detect concurrent mutation while reading."""
    path = Path(path)
    directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, f'Not a plain unlinked regular file: {path.name}')
        require(before.st_size <= limit, f'File exceeds {limit} bytes: {path.name}')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(limit + 1)
        after = os.fstat(fd)
        current = path.lstat()
        key = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(key(before) == key(after) == key(current) and len(raw) == before.st_size,
                f'Source changed during read: {path.name}')
        return raw
    finally:
        os.close(fd)

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def identity(path, limit=MAX_FILE):
    raw = read_file(path, limit)
    return dict(name=Path(path).name, bytes=len(raw), sha256=digest(raw))

def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)

def inventory(folder):
    folder = directory(folder)
    entries = list(folder.iterdir())
    require(len(entries) <= 256, 'Source directory has more than 256 entries; choose a smaller flat directory')
    rows = []
    for p in sorted(entries):
        row = dict(name=p.name, bytes=p.lstat().st_size, supported=True)
        try:
            safe_name(p.name)
            require(not p.name.lower().endswith('.par2'), 'Recovery inputs cannot be selected as source files')
            raw = read_file(p)
            require(raw, 'Empty files are unsupported; keep them separately')
        except (DeskError, OSError) as e:
            row.update(supported=False, reason=str(e))
        rows.append(row)
    return rows

def parse_par2(folder):
    """Strict supported PAR2 subset; never hand unsafe embedded paths to the engine.

    Invalid packets are skipped (damaged recovery data), valid unknown packet types
    are rejected to avoid alternate filename semantics. Require complete metadata.
    """
    files = sorted(folder.glob('*.par2'))
    require(0 < len(files) <= 32, 'Expected 1–32 .par2 files')
    total = 0
    sets, mains, descriptions, recovery = set(), {}, {}, set()
    allowed = {b'PAR 2.0\0Main\0\0\0\0', b'PAR 2.0\0FileDesc', b'PAR 2.0\0IFSC\0\0\0\0', b'PAR 2.0\0RecvSlic', b'PAR 2.0\0Creator\0'}
    for path in files:
        safe_name(path.name)
        raw = read_file(path, MAX_RECOVERY)
        total += len(raw)
        require(total <= MAX_RECOVERY, 'Recovery input size exceeds 48 MiB')
        offset = 0
        while True:
            offset = raw.find(b'PAR2\0PKT', offset)
            if offset < 0:
                break
            if offset + 64 > len(raw):
                break
            size = struct.unpack_from('<Q', raw, offset + 8)[0]
            if size < 64 or size % 4 or offset + size > len(raw):
                offset += 8
                continue
            packet = raw[offset:offset + size]
            if hashlib.md5(packet[32:]).digest() != packet[16:32]:
                offset += 8
                continue
            offset += size
            sets.add(packet[32:48])
            kind, body = packet[48:64], packet[64:]
            require(kind in allowed, f'Unsupported PAR2 packet type: {kind!r}')
            if kind == b'PAR 2.0\0Main\0\0\0\0':
                require(len(body) >= 12 and (len(body) - 12) % 16 == 0, 'Malformed main packet')
                mains[body] = True
            elif kind == b'PAR 2.0\0FileDesc':
                require(len(body) >= 60, 'Malformed file description')
                name = body[56:].rstrip(b'\0').decode('ascii', errors='strict')
                safe_name(name)
                require(not name.lower().endswith('.par2'), 'Source/recovery filename collision')
                record = dict(name=name, bytes=struct.unpack_from('<Q', body, 48)[0], md5=body[16:32].hex())
                require(0 < record['bytes'] <= MAX_FILE, 'Empty or oversized package member')
                fid = body[:16]
                require(fid not in descriptions or descriptions[fid] == record, 'Conflicting file description')
                descriptions[fid] = record
            elif kind == b'PAR 2.0\0RecvSlic':
                require(len(body) >= 4, 'Malformed recovery packet')
                recovery.add(struct.unpack_from('<I', body)[0])
    require(len(sets) == len(mains) == 1, 'Require one recovery set and intact main metadata')
    body = next(iter(mains))
    block, count = struct.unpack_from('<QI', body)
    ids = [body[i:i+16] for i in range(12, len(body), 16)]
    require(1 <= count <= 64 and len(ids) == count == len(set(ids)), 'Non-recovery members or duplicate IDs unsupported')
    require(64 <= block <= 1024**2 and block % 4 == 0, 'Unsupported block size')
    require(set(ids) == set(descriptions), 'Missing or extra file descriptions')
    rows = [descriptions[i] for i in ids]
    require(len({r['name'].casefold() for r in rows}) == count, 'Duplicate or case-colliding filenames')
    require(sum(r['bytes'] for r in rows) <= MAX_TOTAL, 'Package exceeds 16 MiB source limit')
    require(sum(math.ceil(r['bytes'] / block) for r in rows) <= 8192, 'Package exceeds 8192 data blocks')
    require(len(recovery) <= 8192, 'Too many recovery blocks')
    return dict(files=rows, block_size=block, recovery_blocks=len(recovery), set_id=next(iter(sets)).hex())

class Engine:
    def __init__(self, workspace, source, binary=None):
        self.workspace = Path(workspace).absolute()
        self.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory(self.workspace)
        self.source = directory(source)
        self.binary = str(Path(binary or os.environ.get('PAR2', ROOT / '.tools/installed/bin/par2')).resolve())
        require(Path(self.binary).is_file(), 'PAR2 engine missing. Run ./launch.sh to build it.')
        self.cancel = threading.Event()
        self.publication_lock = threading.Lock()
        self.published = False
        self.tool_version = subprocess.run([self.binary, '-V'], capture_output=True, text=True, timeout=5, check=True).stdout.strip()

    def request_cancel(self):
        # Publication is an atomic commit boundary. A late cancellation cannot
        # retract a completed batch, and is explicitly reported as too late.
        with self.publication_lock:
            if self.published:
                return False
            self.cancel.set()
            return True

    def fresh(self, prefix):
        size = sum(p.stat().st_size for p in self.workspace.rglob('*') if p.is_file())
        require(size < 384 * 1024**2, 'Workspace limit reached (384 MiB); archive/remove old .runtime jobs before continuing')
        p = self.workspace / (prefix + '-' + uuid.uuid4().hex)
        p.mkdir(mode=0o700)
        return p

    def run(self, args, cwd, timeout=120):
        require(not self.cancel.is_set(), 'Operation cancelled')
        cmd = [self.binary, *args]
        output = cwd / ('engine-' + uuid.uuid4().hex + '.txt')
        start = time.monotonic()
        with output.open('wb') as log:
            process = subprocess.Popen([sys.executable, str(ROOT / 'desk/limits.py'), *cmd], cwd=cwd,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                       env={**os.environ, 'OMP_NUM_THREADS': '2', 'LC_ALL': 'C'})
            reason = None
            while process.poll() is None:
                if self.cancel.is_set() or time.monotonic() - start > timeout or output.stat().st_size > 1024**2:
                    reason = 'cancelled' if self.cancel.is_set() else 'time/output resource limit'
                    os.killpg(process.pid, signal.SIGKILL)
                    break
                time.sleep(.03)
            code = process.wait()
        text = output.read_bytes()[:1024**2].decode('utf-8', errors='replace')
        output.unlink()
        return dict(command=[Path(self.binary).name, *args], exit_code=code, output=text,
                    interrupted=reason, elapsed_seconds=round(time.monotonic() - start, 3))

    def package(self, package_id):
        require(re.fullmatch(r'package-[0-9a-f]{32}', package_id or '') is not None, 'Invalid package ID')
        p = self.workspace / package_id
        manifest = json.loads((p / 'manifest.json').read_text())
        require(manifest['status'] == 'ready', 'Package is incomplete')
        return p, manifest

    def create(self, names, redundancy=30, block_size=256):
        self.published = False
        require(isinstance(names, list) and 1 <= len(names) <= 64, 'Select 1–64 files')
        for n in names:
            safe_name(n)
            require(not n.lower().endswith('.par2'), 'Cannot select recovery files')
        require(len(set(n.casefold() for n in names)) == len(names), 'Duplicate/case-colliding selected paths')
        require(type(redundancy) is int and 1 <= redundancy <= 100, 'Redundancy must be an integer from 1 to 100')
        require(type(block_size) is int and 64 <= block_size <= 1024**2 and block_size % 4 == 0, 'Block size must be a multiple of 4, from 64 to 1048576')
        p = self.fresh('package')
        originals = p / 'originals'
        originals.mkdir()
        work = p / 'creation'
        work.mkdir()
        records, total = [], 0
        try:
            for name in names:
                require(not self.cancel.is_set(), 'Operation cancelled')
                raw = read_file(self.source / name)
                require(raw, f'Empty file unsupported: {name}')
                total += len(raw)
                require(total <= MAX_TOTAL, 'Selection exceeds 16 MiB')
                (originals / name).write_bytes(raw)
                (work / name).write_bytes(raw)
                records.append(dict(name=name, bytes=len(raw), sha256=digest(raw), source=str(self.source / name)))
            blocks = sum(math.ceil(r['bytes'] / block_size) for r in records)
            require(blocks <= 8192, 'More than 8192 data blocks; increase block size')
            result = self.run(['c', '-t2', '-m64', f'-s{block_size}', f'-r{redundancy}', '--', 'recovery.par2', *names], work)
            require(result['exit_code'] == 0 and not result['interrupted'], f'Creation failed: {result}')
            for r in records:
                require(identity(self.source / r['name'])['sha256'] == r['sha256'], 'Source changed during package creation')
            parity = parse_par2(work)
            require({r['name'] for r in parity['files']} == set(names), 'PAR2 did not account for every selected file')
            recovery = p / 'recovery'
            recovery.mkdir()
            for f in work.glob('*.par2'):
                f.rename(recovery / f.name)
            source_info = json.loads((ROOT / 'data/sources.json').read_text()) if self.source == ROOT / 'data/twemoji' else {'collection': 'User-selected local files'}
            manifest = dict(id=p.name, status='ready', basis='independent-original-sha256', files=records,
                            source_identity=source_info, tool_version=self.tool_version, settings=dict(redundancy_percent=redundancy,
                            block_size=block_size, data_blocks=blocks, recovery_blocks=parity['recovery_blocks']),
                            recovery_files=[identity(f, MAX_RECOVERY) for f in sorted(recovery.iterdir())], creation=result)
            with self.publication_lock:
                require(not self.cancel.is_set(), 'Operation cancelled before package publication')
                save(p / 'manifest.json', manifest)
                self.published = True
            shutil.rmtree(work)
            return manifest
        except Exception as e:
            save(p / 'failure.json', {'status': 'incomplete', 'error': str(e)})
            raise

    def import_package(self, folder):
        self.published = False
        source = directory(folder)
        p = self.fresh('package')
        recovery = p / 'recovery'
        recovery.mkdir()
        files = sorted(source.glob('*.par2'))
        require(0 < len(files) <= 32, 'Import requires 1–32 .par2 files')
        total = 0
        for f in files:
            safe_name(f.name)
            raw = read_file(f, MAX_RECOVERY)
            total += len(raw)
            require(total <= MAX_RECOVERY, 'Recovery inputs exceed 48 MiB')
            (recovery / f.name).write_bytes(raw)
        parity = parse_par2(recovery)
        for f in files:
            require(digest(read_file(f, MAX_RECOVERY)) == digest(read_file(recovery / f.name, MAX_RECOVERY)), 'Import source changed')
        manifest = dict(id=p.name, status='ready', basis='imported-par2-md5-only', files=parity['files'],
                        source_identity={'imported_directory': str(source), 'set_id': parity['set_id']},
                        tool_version=self.tool_version, settings=parity | {'files': None},
                        recovery_files=[identity(f, MAX_RECOVERY) for f in sorted(recovery.iterdir())])
        with self.publication_lock:
            require(not self.cancel.is_set(), 'Operation cancelled before package publication')
            save(p / 'manifest.json', manifest)
            self.published = True
        return manifest

    def evaluate(self, package_id, candidate, repair=False, recovery_folder=None):
        self.published = False
        p, manifest = self.package(package_id)
        candidate = directory(candidate)
        recovery_folder = directory(recovery_folder) if recovery_folder else p / 'recovery'
        job = self.fresh('repair' if repair else 'verify')
        stage = job / 'staging'
        stage.mkdir()
        before, recovery_before = [], []
        total = 0
        for f in sorted(recovery_folder.glob('*.par2')):
            safe_name(f.name)
            raw = read_file(f, MAX_RECOVERY)
            total += len(raw)
            require(total <= MAX_RECOVERY and len(recovery_before) < 32, 'Recovery input limits exceeded')
            (stage / f.name).write_bytes(raw)
            recovery_before.append(dict(name=f.name, sha256=digest(raw), bytes=len(raw)))
        metadata = parse_par2(stage)
        expected = {r['name']: r for r in manifest['files']}
        require({r['name']: r['bytes'] for r in metadata['files']} == {n:r['bytes'] for n,r in expected.items()}, 'Recovery package members differ')
        # Match trusted metadata to the package, not just the selected names.
        trusted = parse_par2(p / 'recovery')
        require(metadata['set_id'] == trusted['set_id'] and metadata['files'] == trusted['files'], 'Recovery set differs from the selected package')
        rows = []
        candidate_bytes = 0
        for name, record in expected.items():
            path = candidate / name
            if path.exists() or path.is_symlink():
                raw = read_file(path)
                candidate_bytes += len(raw)
                require(candidate_bytes <= MAX_TOTAL, 'Candidate inputs exceed 16 MiB')
                (stage / name).write_bytes(raw)
                before.append(dict(name=name, sha256=digest(raw), bytes=len(raw)))
            else:
                before.append(dict(name=name, missing=True))
            rows.append(self.check_file(stage / name, record, p, manifest['basis']))
        result = self.run(['r' if repair else 'v', '-t2', '-m64', '--', sorted(f.name for f in stage.glob('*.par2'))[0]], stage)
        after = [self.check_file(stage / name, record, p, manifest['basis']) for name, record in expected.items()]
        unchanged = all((not (candidate / r['name']).exists() and not (candidate / r['name']).is_symlink()) if r.get('missing') else identity(candidate / r['name']) == r for r in before)
        recovery_unchanged = all(identity(recovery_folder / r['name'], MAX_RECOVERY) == r for r in recovery_before)
        original_snapshots_unchanged = all(identity(p / 'originals' / r['name'])['sha256'] == r['sha256'] for r in manifest['files']) if manifest['basis'] == 'independent-original-sha256' else None
        all_match = all(r['match'] for r in after)
        verified = all_match and unchanged and recovery_unchanged and original_snapshots_unchanged is not False and not result['interrupted'] and result['exit_code'] == 0
        if result['interrupted']:
            status = 'cancelled-or-resource-limited'
        elif verified:
            status = 'verified-restored' if repair else 'verified-intact'
        elif result['exit_code'] == 2:
            status = 'insufficient-recovery'
        elif result['exit_code'] == 1 and not repair:
            status = 'repair-possible'
        else:
            status = 'failed-or-unverified'
        report = dict(id=job.name, package_id=package_id, status=status, repair_requested=repair,
                      basis=manifest['basis'], tool_version=self.tool_version, source_identity=manifest['source_identity'],
                      settings=manifest['settings'], package_files=manifest['files'], recovery_inputs=recovery_before,
                      candidate_directory=str(candidate), inspected_files=rows, output_files=after,
                      inputs_unchanged=unchanged, recovery_inputs_unchanged=recovery_unchanged,
                      preserved_originals_unchanged=original_snapshots_unchanged, engine=result,
                      output_directory=str(job / 'restored') if repair and verified else None,
                      warning='Recovery data is neither an independent backup nor proof of authenticity. Block redundancy is not a percentage-of-damage guarantee.')
        with self.publication_lock:
            require(not self.cancel.is_set(), 'Operation cancelled before result publication; staging remains unverified')
            if repair and verified:
                restored = job / 'unverified-output'
                restored.mkdir()  # exclusive creation; never accept caller destination paths
                for name in expected:
                    with (restored / name).open('xb') as target:
                        target.write(read_file(stage / name))
                report['output_files'] = [self.check_file(restored / name, r, p, manifest['basis']) for name, r in expected.items()]
                require(all(r['match'] for r in report['output_files']), 'Final output verification failed; copies remain unverified')
                restored.rename(job / 'restored')
            mutation_path = candidate.parent / 'mutation.json'
            if candidate.parent.parent == self.workspace and candidate.parent.name.startswith('demo-') and mutation_path.is_file():
                report['controlled_mutation'] = json.loads(read_file(mutation_path).decode())
            save(job / 'report.json', report)
            (job / 'report.html').write_text(report_html(report))
            self.published = True
        return report

    def check_file(self, path, record, package, basis):
        if not path.exists():
            return dict(name=record['name'], state='missing', match=False, sha256=None)
        raw = read_file(path)
        sha = digest(raw)
        if basis == 'independent-original-sha256':
            equal = raw == read_file(package / 'originals' / record['name'])
            match = len(raw) == record['bytes'] and sha == record['sha256'] and equal
        else:
            equal = None
            match = len(raw) == record['bytes'] and hashlib.md5(raw).hexdigest() == record['md5']
        return dict(name=record['name'], bytes=len(raw), sha256=sha, byte_for_byte_original_match=equal,
                    match=match, state='match' if match else 'damaged', basis=basis)

    def damage_demo(self, package_id, scenario):
        self.published = False
        p, manifest = self.package(package_id)
        require(manifest['basis'] == 'independent-original-sha256', 'Demo requires a locally created package')
        require(scenario in {'byte-corruption', 'truncation', 'missing-file', 'insufficient-recovery', 'damaged-recovery'}, 'Unknown demo scenario')
        demo = self.fresh('demo')
        data, recovery = demo / 'files', demo / 'recovery'
        shutil.copytree(p / 'originals', data)
        shutil.copytree(p / 'recovery', recovery)
        # Smallest file makes the missing-file case useful at moderate redundancy.
        record = min(manifest['files'], key=lambda r:r['bytes'])
        f = data / record['name']
        raw = f.read_bytes()
        mutation = dict(scenario=scenario, target=f.name, original_sha256=digest(raw))
        if scenario in {'byte-corruption', 'damaged-recovery'}:
            f.write_bytes(bytes([raw[0] ^ 255]) + raw[1:])
            mutation.update(offset=0, operation='XOR 0xff at byte 0')
        elif scenario == 'truncation':
            f.write_bytes(raw[:-min(64, len(raw))])
            mutation.update(operation='remove last up to 64 bytes', removed_bytes=min(64, len(raw)))
        elif scenario == 'missing-file':
            f.unlink()
            mutation.update(operation='delete smallest selected file')
        else:
            for item in data.iterdir():
                item.unlink()
            mutation.update(operation='delete all selected files and all recovery-volume files')
            for item in recovery.glob('*.vol*.par2'):
                item.unlink()
        if scenario == 'damaged-recovery':
            damaged = []
            for item in recovery.glob('*.vol*.par2'):
                original = identity(item, MAX_RECOVERY)
                item.write_bytes(b'CORRUPTED RECOVERY VOLUME\n')
                damaged.append(original)
            mutation.update(recovery_operation='replace every recovery volume with literal CORRUPTED RECOVERY VOLUME newline', damaged_volumes=damaged)
        save(demo / 'mutation.json', mutation)
        return dict(candidate=str(data), recovery_folder=str(recovery), mutation=mutation)

def report_html(report):
    rows = ''.join('<tr><td>' + html.escape(str(r['name'])) + '</td><td>' + html.escape(r['state']) + '</td><td><code>' + html.escape(r.get('sha256') or '—') + '</code></td></tr>' for r in report['output_files'])
    return '<!doctype html><meta charset="utf-8"><title>Parity Recovery report</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:20px}td,th{padding:12px;border-bottom:1px solid #ccc;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}code{font-size:12px}</style><h1>Parity Recovery Desk</h1><h2>' + html.escape(report['status']) + '</h2><p>Verification basis: ' + html.escape(report['basis']) + '</p><p>' + html.escape(report['warning']) + '</p><table><tr><th>File</th><th>Result</th><th>Output SHA-256</th></tr>' + rows + '</table><h2>Complete portable record</h2><pre>' + html.escape(json.dumps(report, indent=2)) + '</pre>'
