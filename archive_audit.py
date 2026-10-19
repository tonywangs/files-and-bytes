"""Offline regular-file content audit. Python 3.10+, standard library only."""
import argparse
import bz2
import gzip
import hashlib
import html
import json
import lzma
import os
from pathlib import Path
import signal
import stat
import tarfile
import zipfile


class StrictTarInfo(tarfile.TarInfo):
    @classmethod
    def fromtarfile(cls, archive):
        try:
            return super().fromtarfile(archive)
        except (tarfile.InvalidHeaderError, tarfile.TruncatedHeaderError,
                tarfile.EmptyHeaderError) as exc:
            raise tarfile.ReadError(str(exc)) from exc


class LimitError(Exception):
    pass


def signature(s):
    return (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def mapped(name, prefix=''):
    if '\\' in name or '\x00' in name or name.startswith('/'):
        raise ValueError('unsafe path')
    parts = name.rstrip('/').split('/')
    while parts and parts[0] == '.':
        parts.pop(0)
    if any(p in ('', '.', '..') or ':' in p for p in parts):
        raise ValueError('unsafe or ambiguous path')
    path = '/'.join(parts)
    if prefix:
        if path == prefix:
            return ''
        if not path.startswith(prefix + '/'):
            raise ValueError('outside requested prefix')
        path = path[len(prefix) + 1:]
    return path


class Budget:
    def __init__(self, total):
        self.remaining = total

    def read(self, stream, size):
        data = stream.read(min(size, self.remaining + 1))
        self.remaining -= len(data)
        if self.remaining < 0:
            raise LimitError('total byte limit exceeded')
        return data


class BoundedReader:
    def __init__(self, stream, limit):
        self.stream, self.budget = stream, Budget(limit)

    def read(self, size):
        return self.budget.read(self.stream, size)


def digest(stream, expected, budget, max_file):
    if expected > max_file:
        raise LimitError('per-file byte limit exceeded')
    h, count = hashlib.sha256(), 0
    while True:
        block = budget.read(stream, min(65536, max_file - count + 1))
        if not block:
            break
        count += len(block)
        if count > max_file:
            raise LimitError('per-file byte limit exceeded')
        h.update(block)
    if count != expected:
        raise OSError('size changed or truncated data')
    return h.hexdigest()


def audit(source, archive, prefix='', max_entries=10000, max_file=64*1024**2,
          max_total=512*1024**2, max_archive=64*1024**2):
    source, archive = Path(source), Path(archive)
    report = dict(schema_version=1, source=str(source), archive=str(archive), prefix=prefix,
                  status='incomplete', complete=False, source_entries=[], archive_entries=[],
                  comparisons=[], errors=[], limits=dict(max_entries=max_entries, max_file=max_file,
                  max_total=max_total, max_archive=max_archive))
    src, members, snapshots = {}, {}, {}
    errors = report['errors']

    def fail(row, exc):
        row['status'] = 'unverified'
        row['error'] = str(exc)
        errors.append(f"{row.get('path', row.get('name', ''))}: {exc}")

    def walk(folder, relative=''):
        snapshots[folder] = signature(folder.lstat())
        with os.scandir(folder) as it:
            for entry in it:
                if len(report['source_entries']) >= max_entries:
                    raise LimitError('source entry limit exceeded')
                path = relative + entry.name
                row = dict(path=path, status='unverified')
                report['source_entries'].append(row)
                try:
                    s = entry.stat(follow_symlinks=False)
                    snapshots[Path(entry.path)] = signature(s)
                    if stat.S_ISDIR(s.st_mode):
                        row.update(type='directory', status='directory')
                        walk(Path(entry.path), path + '/')
                    elif stat.S_ISREG(s.st_mode):
                        row.update(type='file', size=s.st_size)
                        src[path] = row
                        fd = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                        with os.fdopen(fd, 'rb') as f:
                            if signature(os.fstat(f.fileno())) != signature(s):
                                raise OSError('source changed before reading')
                            row['sha256'] = digest(f, s.st_size, source_budget, max_file)
                            if signature(os.fstat(f.fileno())) != signature(s):
                                raise OSError('source changed during reading')
                        row['status'] = 'hashed'
                    else:
                        row['type'] = 'unsupported'
                        raise ValueError('unsupported source type (symlink or special file)')
                except LimitError:
                    raise
                except (OSError, ValueError) as exc:
                    fail(row, exc)

    def member(name, size, kind, opener, budget):
        row = dict(index=len(report['archive_entries']), name=name, size=size, type=kind,
                   status='unverified')
        report['archive_entries'].append(row)
        try:
            path = mapped(name, prefix)
            row['path'] = path
            if path in members:
                raise ValueError('duplicate member path')
            members[path] = row
            if kind == 'directory':
                if size:
                    raise ValueError('directory entry has a nonempty payload')
                if opener is not None:
                    with opener() as f:
                        digest(f, 0, budget, max_file)
                row['status'] = 'directory'
                return
            if not path or kind != 'file':
                raise ValueError('unsupported archive entry type')
            with opener() as f:
                row['sha256'] = digest(f, size, budget, max_file)
            row['status'] = 'hashed'
        except LimitError as exc:
            fail(row, exc)
            raise
        except (OSError, ValueError, RuntimeError, NotImplementedError, EOFError,
                zipfile.BadZipFile, tarfile.TarError) as exc:
            fail(row, exc)

    source_budget, archive_budget = Budget(max_total), Budget(max_total)
    try:
        if min(max_entries, max_file, max_total, max_archive) <= 0:
            raise ValueError('limits must be positive')
        if prefix and mapped(prefix) != prefix:
            raise ValueError('prefix must be a canonical relative path without trailing slash')
        if not stat.S_ISDIR(source.lstat().st_mode):
            raise ValueError('source must be a real directory, not a symlink')
        walk(source)
        initial = signature(archive.stat())
        if initial[3] > max_archive:
            raise LimitError('physical archive byte limit exceeded')
        with archive.open('rb') as raw:
            if zipfile.is_zipfile(raw):
                with zipfile.ZipFile(raw) as z:
                    for i, info in enumerate(z.infolist()):
                        if i >= max_entries:
                            raise LimitError('archive entry limit exceeded')
                        mode = info.external_attr >> 16
                        kind = 'directory' if info.is_dir() else 'file'
                        if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                            kind = 'unsupported'
                        if info.flag_bits & 1:
                            kind = 'encrypted'
                        member(info.orig_filename, info.file_size, kind,
                               lambda: z.open(info), archive_budget)
            else:
                raw.seek(0)
                magic = raw.read(6)
                raw.seek(0)
                stream = (gzip.GzipFile(fileobj=raw) if magic.startswith(b'\x1f\x8b') else
                          bz2.BZ2File(raw) if magic.startswith(b'BZh') else
                          lzma.LZMAFile(raw) if magic.startswith(b'\xfd7zXZ') else raw)
                try:
                    bounded = BoundedReader(stream, max_total)
                    with tarfile.open(fileobj=bounded, mode='r|', tarinfo=StrictTarInfo) as t:
                        for i, info in enumerate(t):
                            if i >= max_entries:
                                raise LimitError('archive entry limit exceeded')
                            kind = 'directory' if info.isdir() else 'file' if info.isfile() and not info.issparse() else 'unsupported'
                            member(info.name, info.size, kind, None if kind == 'directory' else lambda: t.extractfile(info), archive_budget)
                        # Require the second zero terminator and zero-only padding.
                        padding = 0
                        while True:
                            block = t.fileobj.read(65536)
                            if not block:
                                break
                            padding += len(block)
                            if any(block):
                                raise tarfile.ReadError('nonzero data after TAR terminator')
                        if padding < 512:
                            raise tarfile.ReadError('missing second TAR zero terminator')
                    # Consume compression trailers too: a valid logical TAR is not
                    # enough when its gzip/bzip2/xz container is truncated or corrupt.
                    while bounded.read(65536):
                        pass
                finally:
                    if stream is not raw:
                        stream.close()
            if signature(os.fstat(raw.fileno())) != initial:
                raise OSError('archive changed during reading')
        if signature(archive.stat()) != initial:
            raise OSError('archive replaced during reading')
    except (Exception, KeyboardInterrupt) as exc:
        errors.append(f'{type(exc).__name__}: {exc}')
    for path, old in snapshots.items():
        try:
            if signature(path.lstat()) != old:
                errors.append(f'source changed: {path}')
        except OSError as exc:
            errors.append(f'source unavailable on recheck: {path}: {exc}')
    for path in sorted(set(src) | {p for p, r in members.items() if r['type'] != 'directory'}):
        s, a = src.get(path), members.get(path)
        state = ('extra' if s is None else 'missing' if a is None else
                 'unverified' if s['status'] != 'hashed' or a['status'] != 'hashed' else
                 'match' if (s['size'], s['sha256']) == (a['size'], a['sha256']) else 'changed')
        report['comparisons'].append(dict(path=path, status=state))
    report['complete'] = not errors
    report['status'] = ('incomplete' if errors else 'different' if any(
        c['status'] != 'match' for c in report['comparisons']) else 'identical')
    return report


def write_report(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    def cell(value):
        return html.escape(str(value))
    sections = []
    for title, rows in [('Comparisons', report['comparisons']), ('Source evidence', report['source_entries']),
                        ('Archive evidence', report['archive_entries'])]:
        keys = list(dict.fromkeys(k for r in rows for k in r))
        sections.append('<h2>' + title + '</h2><table><thead><tr>' + ''.join('<th>'+cell(k)+'</th>' for k in keys) +
                        '</tr></thead><tbody>' + ''.join('<tr>'+''.join('<td>'+cell(r.get(k,''))+'</td>' for k in keys)+'</tr>' for r in rows)+'</tbody></table>')
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Archive content audit</title><style>body{font:16px system-ui;margin:2rem;color:#182330;background:#f7f9fc}table{border-collapse:collapse;width:100%;font:13px monospace}td,th{padding:.5rem;border:1px solid #ccd3dc;text-align:left;overflow-wrap:anywhere}th{background:#dce8f5}h1{font-size:2rem}li{color:#922}</style><h1>Archive content audit: '+cell(report['status'])+'</h1><p>Source: '+cell(report['source'])+'<br>Archive: '+cell(report['archive'])+'<br>Prefix: '+cell(report['prefix'] or '(none)')+'</p><p>SHA-256 regular-file content comparison. Metadata and link preservation are not verified. Missing/extra labels are provisional when incomplete.</p><ul>'+''.join('<li>'+cell(e)+'</li>' for e in report['errors'])+'</ul>'+''.join(sections)+'</html>'
    for name, data in [('report.json', json.dumps(report, indent=2, ensure_ascii=True)+'\n'), ('report.html', page)]:
        temp = output / (name + '.tmp')
        temp.write_text(data, encoding='utf-8', errors='xmlcharrefreplace')
        temp.replace(output / name)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source')
    p.add_argument('archive')
    p.add_argument('--prefix', default='')
    p.add_argument('--output', required=True)
    for name, default in [('max-entries',10000), ('max-file',64*1024**2), ('max-total',512*1024**2), ('max-archive',64*1024**2)]:
        p.add_argument('--'+name, type=int, default=default)
    args = vars(p.parse_args())
    output = Path(args.pop('output')).resolve()
    source = Path(args['source']).resolve()
    archive = Path(args['archive']).resolve()
    if output == source or source in output.parents or output == archive or output in archive.parents:
        p.error('report output must be outside the source tree and must not contain the archive')
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    report = audit(**args)
    write_report(report, output)
    print(f"{report['status']}: {output / 'report.html'}")
    return {'identical':0, 'different':1, 'incomplete':2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
