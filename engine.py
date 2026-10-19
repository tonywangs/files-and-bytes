"""Bounded Linux rename engine. No replacing rename or content writes to user files."""
import contextlib
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata
import uuid

CONTROL = '.rename-desk'
MAX_FILES = 500
MAX_BYTES = 64 * 1024 * 1024


class Refused(ValueError):
    pass


def valid_name(name):
    if not isinstance(name, str) or not name or name in ('.', '..', CONTROL):
        raise Refused('Empty or reserved filename')
    if any(c in name for c in '/\\') or any(unicodedata.category(c).startswith('C') for c in name):
        raise Refused('Path separators and control characters are not allowed')
    if len(name.encode('utf-8')) > 255 or name.endswith((' ', '.')):
        raise Refused('Filename too long or ends in a dot/space')
    if any(c in name for c in '<>:"|?*') or name.split('.')[0].upper() in {
        'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}:
        raise Refused('Reserved or nonportable filename')
    return name


def key(name):
    return unicodedata.normalize('NFC', name).casefold()


def fingerprint(fd, name):
    f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        before = os.fstat(f)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise Refused(f'{name}: only regular files with one hard link are supported')
        if before.st_size > MAX_BYTES:
            raise Refused(f'{name}: exceeds 64 MiB file limit')
        digest = hashlib.sha256()
        while chunk := os.read(f, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(f)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise Refused(f'{name}: changed while being read')
        return dict(dev=after.st_dev, ino=after.st_ino, size=after.st_size,
                    mtime=after.st_mtime_ns, sha256=digest.hexdigest())
    finally:
        os.close(f)


def transform(names, rules):
    find = rules.get('find', '')
    replacement = rules.get('replace', '')
    prefix, suffix = rules.get('prefix', ''), rules.get('suffix', '')
    number = bool(rules.get('number', False))
    start, width = int(rules.get('start', 1)), int(rules.get('width', 3))
    if not 0 <= start <= 999999 or not 1 <= width <= 8:
        raise Refused('Number start must be 0–999999 and width 1–8')
    result = []
    for i, name in enumerate(names):
        stem, ext = os.path.splitext(name) if rules.get('preserve_extension', True) else (name, '')
        stem = stem.replace(find, replacement) if find else stem
        result.append(prefix + (str(start+i).zfill(width)+'-' if number else '') + stem + suffix + ext)
    return result


class Desk:
    def __init__(self, folder):
        if sys.platform != 'linux':
            raise Refused('This release requires Linux and renameat2(RENAME_NOREPLACE)')
        self.path = str(Path(folder).absolute())
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                os.mkdir(CONTROL, mode=0o700, dir_fd=self.fd)
                os.fsync(self.fd)
            except FileExistsError:
                pass
            self.control = os.open(CONTROL, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
            self.libc = ctypes.CDLL(None, use_errno=True)
            self.rename = self.libc.renameat2
            self.rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            self.rename.restype = ctypes.c_int
        except BaseException:
            os.close(self.fd)
            raise

    def close(self):
        os.close(self.control)
        os.close(self.fd)

    @contextlib.contextmanager
    def locked(self):
        fcntl.flock(self.control, fcntl.LOCK_EX)
        try:
            # Refuse if someone replaced the pathname for either pinned directory.
            for path, fd in [(self.path, self.fd), (self.path+'/'+CONTROL, self.control)]:
                a, b = os.stat(path, follow_symlinks=False), os.fstat(fd)
                if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
                    raise Refused('Selected directory or journal directory has been replaced')
            yield
        finally:
            fcntl.flock(self.control, fcntl.LOCK_UN)

    def scan(self):
        rows, skipped = [], []
        for name in sorted(os.listdir(self.fd)):
            if name == CONTROL:
                continue
            try:
                valid_name(name)
                info = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise Refused('directory, symlink, special file, or hard link')
                rows.append({'source': name, 'fingerprint': fingerprint(self.fd, name)})
            except (OSError, ValueError) as exc:
                skipped.append({'name': name, 'reason': str(exc)})
            if len(rows) > MAX_FILES:
                raise Refused('At most 500 supported files per folder')
        return rows, skipped

    def journals(self):
        result = []
        for ident in sorted(os.listdir(self.control)):
            if not re.fullmatch('[0-9a-f]{32}', ident):
                raise Refused('Unexpected item in journal directory; inspect it manually')
            op = os.open(ident, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.control)
            try:
                try:
                    f = os.open('journal.json', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=op)
                except FileNotFoundError:
                    # An interruption before journal publication cannot have moved files.
                    if any(n != 'journal.tmp' for n in os.listdir(op)):
                        raise Refused('Missing journal with unexpected staged files')
                    continue
                with os.fdopen(f) as stream:
                    j = json.load(stream)
                if j['id'] != ident or j['version'] != 1:
                    raise Refused('Invalid journal')
                result.append(j)
            finally:
                os.close(op)
        return result

    def validate(self, rows):
        if not rows or len(rows) > MAX_FILES:
            raise Refused('Choose between 1 and 500 files')
        if len({r['source'] for r in rows}) != len(rows):
            raise Refused('Duplicate source')
        sources = {r['source'] for r in rows}
        destinations = set()
        occupied = os.listdir(self.fd)
        for row in rows:
            src, dest = valid_name(row['source']), valid_name(row['dest'])
            if key(dest) in destinations:
                raise Refused(f'Duplicate destination (including case/Unicode aliases): {dest}')
            destinations.add(key(dest))
            for name in occupied:
                if key(name) == key(dest) and name not in sources:
                    raise Refused(f'Occupied destination: {dest}')
            try:
                if fingerprint(self.fd, src) != row['fingerprint']:
                    raise Refused(f'Stale source: {src}; refresh the folder')
            except OSError as exc:
                raise Refused(f'Stale or unsupported source: {src}') from exc
        if any(j['status'] != 'undone' for j in self.journals()):
            raise Refused('Undo or recover the previous operation before starting another')

    def save(self, op, journal):
        f = os.open('journal.tmp', os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600, dir_fd=op)
        with os.fdopen(f, 'w') as stream:
            json.dump(journal, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace('journal.tmp', 'journal.json', src_dir_fd=op, dst_dir_fd=op)
        os.fsync(op)

    def move(self, srcfd, source, dstfd, dest, expected):
        if fingerprint(srcfd, source) != expected:
            raise Refused(f'File changed before move: {source}')
        if self.rename(srcfd, os.fsencode(source), dstfd, os.fsencode(dest), 1):
            err = ctypes.get_errno()
            raise Refused(f'Move refused ({source} → {dest}): {os.strerror(err)}')
        os.fsync(srcfd)
        os.fsync(dstfd)
        # Test-only process-kill injection, never exposed over HTTP.
        crash = os.environ.get('RENAME_DESK_TEST_CRASH_AFTER')
        if crash:
            self._moves = getattr(self, '_moves', 0) + 1
            if self._moves == int(crash):
                os._exit(86)

    def apply(self, rows):
        self.validate(rows)
        rows = [dict(r) for r in rows if r['source'] != r['dest']]
        if not rows:
            raise Refused('The plan does not change any names')
        ident = uuid.uuid4().hex
        os.mkdir(ident, mode=0o700, dir_fd=self.control)
        os.fsync(self.control)
        op = os.open(ident, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.control)
        journal = dict(version=1, id=ident, status='applying', rows=rows)
        try:
            for i, row in enumerate(rows):
                row['temp'] = f'file-{i}'
            self.save(op, journal)
            for row in rows:
                self.move(self.fd, row['source'], op, row['temp'], row['fingerprint'])
            for row in rows:
                self.move(op, row['temp'], self.fd, row['dest'], row['fingerprint'])
            journal['status'] = 'applied'
            self.save(op, journal)
            return journal
        finally:
            os.close(op)

    def undo(self, ident):
        journal = next((j for j in self.journals() if j['id'] == ident), None)
        if journal is None or journal['status'] == 'undone':
            raise Refused('No recoverable operation selected')
        op = os.open(ident, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.control)
        try:
            rows = journal['rows']
            locations = []
            names = {r[k] for r in rows for k in ('source', 'dest')}
            # Identify by inode AND content, never by filename alone.
            for row in rows:
                found = []
                for fd, name in [(self.fd, n) for n in names] + [(op, row['temp'])]:
                    try:
                        st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if (st.st_dev, st.st_ino) == (row['fingerprint']['dev'], row['fingerprint']['ino']):
                        if fingerprint(fd, name) != row['fingerprint']:
                            raise Refused(f'Changed file; refusing recovery: {name}')
                        found.append((fd, name))
                if len(found) != 1:
                    raise Refused(f'Missing or ambiguous file: {row["source"]}')
                locations.append(found[0])
            known = set(locations)
            # Preflight all originals and staging slots before making any move.
            for row in rows:
                for fd, target in [(self.fd, row['source']), (op, row['temp'])]:
                    for existing in os.listdir(fd):
                        if key(existing) == key(target) and (fd, existing) not in known:
                            raise Refused(f'Recovery destination occupied: {target}')
            journal['status'] = 'undoing'
            self.save(op, journal)
            for row, location in zip(rows, locations):
                if location != (op, row['temp']):
                    self.move(*location, op, row['temp'], row['fingerprint'])
            for row in rows:
                self.move(op, row['temp'], self.fd, row['source'], row['fingerprint'])
            journal['status'] = 'undone'
            self.save(op, journal)
            return journal
        finally:
            os.close(op)
