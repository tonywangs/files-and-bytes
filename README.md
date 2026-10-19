# Duplicate File Desk

Inspect byte-identical local files in a browser, record which copy you intend to retain, and export a portable review. Source files are never deleted, replaced, or opened for writing.

## Launch

Requires Python 3.10+ on Linux or macOS (uses `O_NOFOLLOW`). From this directory:

```sh
python3 desk.py
```

Open **http://127.0.0.1:8765**. If occupied, use `python3 desk.py --port 8877` and open that port. No application dependencies, accounts, network connection, or installation are required. The server binds only to loopback. Do not expose it through a proxy.

1. Click **Scan real CPython demo**, or enter explicitly selected absolute folder paths, one per line. These are folders on the server's computer.
2. Filter groups by path or hash. Each group lists full paths, size, verification method, and distinct inode identities. Select a retained-copy preference; this records intent only.
3. Reload to recover browser-local preferences. A recovered review is marked historical. Re-scan before relying on it: changed identity or content invalidates affected preferences.
4. Export project JSON or standalone HTML. Importing JSON asks to re-scan its folders and restores only matching preferences. HTML opens offline, includes readable groups and all scan evidence, and embeds the JSON in `#report`.

Exports include absolute local paths. Browser persistence is per origin/profile and can be cleared by browser settings. Export JSON for durable backup. Imported reviews are portable evidence, but restoring preferences requires the same accessible paths and identities; moving files to another machine invalidates them.

## Real input and independent verification

`demo/` contains 450 unmodified files from CPython v3.13.0's `Lib/test`, selected by a deterministic size/path rule, plus the upstream license and provenance manifest. Seven naturally occurring duplicate groups contain 17 files, including empty files. No added duplicate controls are in this collection. The manifest records each source URL, size, and SHA-256, the upstream archive URL/hash, revision tag, and selection rule. See [CPython source](https://github.com/python/cpython/tree/v3.13.0/Lib/test) and [license](demo/LICENSE). Reproduce acquisition:

```sh
python3 scripts/acquire.py
python3 scripts/verify_demo.py
```

The independent verifier groups whole byte strings in a separate implementation, checks every group's membership and completeness, and validates all acquired hashes. This deliberately bounded oracle is not the application's streaming algorithm. The demo screenshot is in `results/browser-demo.png`.

## Consistency and limits

* At most 32 roots, 20,000 discovered entries, and 4 GiB of regular file content per scan. A limit makes the scan visibly incomplete. Entry-limit truncation means the undiscovered remainder cannot be enumerated.
* Sizes partition regular files; SHA-256 is streamed in 1 MiB chunks; matching candidates are compared byte for byte. Empty files participate normally. Every processed entry has a status and failures retain a reason.
* Symbolic links and special files are skipped, directories recorded, and overlapping paths deduplicated. Hard links remain separate paths but share an inode identity. Logical duplicate bytes **are not** a physical storage savings estimate; hard links, sparse files, compression, snapshots, and unselected links matter.
* Identity includes device, inode, size, mtime, and ctime. Files are checked on open, after reading, and at scan completion; directories are checked for changes too. Errors and detected changes make the scan incomplete. This is not an atomic snapshot, a filesystem watcher, or a defense against a hostile process changing parent directories concurrently. Quiesce folders or scan a filesystem snapshot for stronger consistency. Network filesystems may have weaker metadata behavior.
* Scans run synchronously and may take time on slow storage. The size cap bounds content per scan, not wall time, number of reads, or simultaneous clients. Only use on trusted local storage. The app hashes unique-size files too, to preserve content evidence.
* Exported reports describe the scan time, not current filesystem state. Retained-copy choices do not authorize deletion. Partial scans cannot establish global uniqueness or completeness.

## Checks

```sh
python3 -m unittest discover -s tests -v
python3 scripts/verify_demo.py
npm ci
npx playwright install chromium
npm run test:browser
```

Playwright is a development-only dependency. Browser checks start their own server on port 18766 and exercise the bundled real inputs, preferences, recovery, import, both exports, and offline HTML. Unit-test unreadability/change cases are injected controls, separate from the real collection. No claim of Windows support or atomic consistency is made.

Duplicate detection is established work; no algorithmic novelty is claimed. Existing tools include [jdupes](https://github.com/jdlorimer/jdupes) and [Czkawka](https://github.com/qarmin/czkawka). This project's scope is a read-only, inspectable review and export workflow.
