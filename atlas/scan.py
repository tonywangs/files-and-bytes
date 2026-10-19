"""Bounded, descriptor-relative metadata scanner. Never reads file contents."""
import os
import stat
import time
import threading
from datetime import datetime, timezone

RULES = {
    'apparent': 'st_size for regular files and symlinks; directories and special files contribute zero.',
    'allocated': 'st_blocks * 512 including directory overhead; null when unavailable. Never reclaimable bytes.',
    'hard_links': 'Each non-directory (device,inode) counted once, at first encounter in filesystem enumeration order; aliases retain raw metadata and an owner reference.',
    'symlinks': 'Link metadata only; never traverse targets. Root path components must not be symlinks.',
    'boundaries': 'Stay on root st_dev; other-device entries skipped, no contribution.',
    'snapshot': 'Historical non-atomic observation. Concurrent changes may cause omissions or mixed metadata. Reading directories may update access times.',
}

def stamp():
    return datetime.now(timezone.utc).isoformat()


def open_root(path):
    """Reject symlinks in every root component, not only the final component."""
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in os.path.abspath(path).split('/')[1:]:
            if not part:
                continue
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def scan(root, *, max_entries=20000, max_depth=64, max_seconds=30, exclude=(), cancel=None):
    if not 1 <= max_entries <= 50000 or not 0 <= max_depth <= 128 or not 0 < max_seconds <= 300:
        raise ValueError('Limits: entries 1..50000, depth 0..128, seconds >0..300')
    cancel = cancel or threading.Event()
    root = os.path.abspath(root)
    start = time.monotonic()
    report = dict(schema='folder-space-atlas/1', root=root, started=stamp(), finished=None,
                  complete=True, rules=RULES, limits=dict(entries=max_entries, depth=max_depth, seconds=max_seconds),
                  exclusions=list(exclude), entries=[], errors=[])
    entries = report['entries']
    owners = {}

    def issue(e, message, state='failed'):
        e['status'] = state
        e['reason'] = message
        report['complete'] = False
        report['errors'].append(dict(entry=e['id'], path=e['path'], message=message))

    def stopped():
        if cancel.is_set():
            return 'Cancelled; unenumerated descendants remain unknown'
        if time.monotonic() - start >= max_seconds:
            return 'Time limit; unenumerated descendants remain unknown'
        return None

    def entry(path, parent):
        e = dict(id=len(entries), parent=parent, path=path, name=os.path.basename(path) if path != '.' else os.path.basename(root) or '/',
                 kind='unknown', status='measured', reason='', raw_apparent=None, raw_allocated=None,
                 own_apparent=0, own_allocated=0, apparent=0, allocated=0, allocation_unknown=0, owner=None)
        entries.append(e)
        return e

    def measure(e, st):
        mode = st.st_mode
        e['kind'] = 'directory' if stat.S_ISDIR(mode) else 'file' if stat.S_ISREG(mode) else 'symlink' if stat.S_ISLNK(mode) else 'special'
        e.update(device=str(st.st_dev), inode=str(st.st_ino), links=st.st_nlink, mtime_ns=str(st.st_mtime_ns), stat_size=st.st_size)
        e['raw_apparent'] = st.st_size if e['kind'] in ('file', 'symlink') else 0
        blocks = getattr(st, 'st_blocks', None)
        e['raw_allocated'] = blocks * 512 if blocks is not None and blocks >= 0 else None
        key = (st.st_dev, st.st_ino)
        if e['kind'] != 'directory' and key in owners:
            e['owner'] = owners[key]
        else:
            if e['kind'] != 'directory':
                owners[key] = e['id']
            e['own_apparent'] = e['raw_apparent']
            e['own_allocated'] = e['raw_allocated']
            e['allocation_unknown'] = int(e['raw_allocated'] is None)

    def walk(fd, e, depth, device):
        reason = stopped()
        if reason:
            issue(e, reason)
            return
        if depth >= max_depth:
            issue(e, 'Depth limit; descendants not enumerated', 'skipped')
            return
        try:
            with os.scandir(fd) as iterator:
                while True:
                    reason = stopped()
                    if reason:
                        issue(e, reason)
                        break
                    # At the bound, do not consume another directory entry.
                    if len(entries) >= max_entries:
                        issue(e, 'Entry limit; remaining entries not enumerated')
                        break
                    item = next(iterator, None)
                    if item is None:
                        break
                    path = item.name if e['path'] == '.' else e['path'] + '/' + item.name
                    child = entry(path, e['id'])
                    if item.name in exclude:
                        issue(child, 'Excluded basename; metadata and descendants not read', 'skipped')
                        continue
                    try:
                        st = os.stat(item.name, dir_fd=fd, follow_symlinks=False)
                        if st.st_dev != device:
                            issue(child, 'Filesystem boundary; metadata not included', 'skipped')
                            continue
                        measure(child, st)
                        if child['kind'] == 'directory':
                            sub = os.open(item.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                            try:
                                actual = os.fstat(sub)
                                if (actual.st_dev, actual.st_ino) != (st.st_dev, st.st_ino):
                                    raise OSError('Directory changed before opening')
                                walk(sub, child, depth + 1, device)
                            finally:
                                os.close(sub)
                    except OSError as exc:
                        issue(child, str(exc))
        except OSError as exc:
            issue(e, str(exc))

    e = entry('.', None)
    try:
        fd = open_root(root)
        try:
            st = os.fstat(fd)
            measure(e, st)
            walk(fd, e, 0, st.st_dev)
        finally:
            os.close(fd)
    except OSError as exc:
        issue(e, str(exc))
    for e in entries:
        e['apparent'] = e['own_apparent']
        e['allocated'] = e['own_allocated'] or 0
    for e in reversed(entries[1:]):
        parent = entries[e['parent']]
        for key in ('apparent', 'allocated', 'allocation_unknown'):
            parent[key] += e[key]
    report['totals'] = {key: entries[0][key] for key in ('apparent', 'allocated', 'allocation_unknown')}
    report['counts'] = {state: sum(e['status'] == state for e in entries) for state in ('measured', 'skipped', 'failed')}
    report['counts']['discovered'] = len(entries)
    report['counts']['files'] = sum(e['kind'] == 'file' for e in entries)
    report['finished'] = stamp()
    return report
