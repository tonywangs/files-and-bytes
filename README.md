# Folder Space Atlas

Understand a selected local folder through a navigable treemap, sortable file table and inspectable accounting evidence. Save interactive, standalone HTML and exact machine-readable JSON snapshots. No file contents are read by the scanner; no delete or cleanup operations exist.

## Try the real demo

Requires Python 3.12+ on Linux (no Python dependencies). From this checkout:

```sh
./launch.sh
```

Open **http://127.0.0.1:4173**, click **Scan selected folder**, open a directory tile, filter its children, and select a file to inspect its metadata. Use breadcrumbs to return. Switch the area metric to allocated bytes. **Save offline HTML** produces an interactive report that works with networking disabled; **Save JSON** preserves the accounting evidence. The table includes zero-size, hard-link aliases and excluded entries even when they have no tile area.

The first launch downloads a hash-pinned zlib 1.3.1 source archive (1.5 MiB). It verifies all 257 source-file hashes on later launches. It never builds or executes the downloaded code. The real scan contains 296 entries and 4,398,621 apparent bytes; allocated bytes depend on the local filesystem. [Provenance](demo/provenance.json) records the upstream commit, URLs and hashes; [the license](demo/ZLIB-LICENSE) is retained. Source stays under ignored `.demo/`.

A ready-to-open historical [sample report](demo/sample.html) and [JSON evidence](demo/sample.json) are included. These describe the acquisition environment, not your current disk. The [browser capture](results/browser-demo.png) shows the tested interface.

## Select your folder explicitly

```sh
./launch.sh /absolute/path/to/folder
# Bound the scan or exclude exact basenames:
./launch.sh /absolute/path/to/folder --max-entries 10000 --max-depth 32 --max-seconds 20 --exclude .git
# Write snapshots without a server (output must be outside the scanned root):
python3 -m atlas /absolute/path/to/folder --output /tmp/my-folder-snapshot
```

CLI exports require a new output prefix: existing files are never overwritten, and symlink output parents are rejected.

Only the CLI-selected root is accessible to the server. It binds IPv4 loopback and validates Host and Origin; use the printed `127.0.0.1` URL. The browser cannot select other paths or read file contents. Stop the server with Ctrl-C. The Cancel button stops traversal cooperatively between filesystem calls and returns visibly incomplete evidence. No authentication is provided against other processes running on your machine.

## Accounting and limits

- Apparent bytes: file and symlink `st_size`; directories and special files contribute zero. Allocation: `st_blocks × 512`, including directories. Sparse files can have far less allocation than apparent size. Missing allocation metadata is marked unknown alongside the known subtotal.
- Non-directory hard links count once by `(device, inode)`, attributed to first encounter in filesystem enumeration order. Every alias retains raw metadata and the owner's entry ID. Directory attribution can change with enumeration order. This is **not reclaimable storage**: links outside the root, compression, shared extents, snapshots and filesystem accounting can all matter.
- Symlinks are measured, never followed, including broken links. Symlinks in root path components are rejected. Directory descent uses no-follow descriptor-relative opens and verifies identity. Entries on another device are skipped; same-device bind mounts cannot be identified by this policy. Depth and entry limits bound such traversal.
- Every discovered entry is measured, skipped or failed. Exclusions and limits make the report incomplete; undiscovered descendants cannot be counted. At exactly the entry cap, the scanner conservatively reports incomplete without fetching another entry. Directory metadata can contribute to partial totals even when its descendants cannot be enumerated. Errors identify their entry IDs.
- Default limits: 20,000 entries, depth 64, 30 seconds. Hard caps: 50,000 entries, depth 128, 300 seconds. Cancellation/time limits cannot interrupt a kernel call blocked on a filesystem. Prefer local disks. Memory and rendering scale with the entry limit; browser responsiveness at the hard cap is not benchmarked.
- Snapshots are **not atomic**. Concurrent modification, rename or deletion can change measurements or cause omissions. Directory access may update access timestamps; source contents are never written. Do not use this as a forensic write-blocking tool.
- Linux is tested. POSIX descriptor APIs are required; Windows is unsupported. macOS is not validated. Browser verification covers Chromium. Browser numbers above JavaScript's safe-integer range may be rounded; JSON preserves exact byte counts: browser/HTML exports use decimal strings for integers above 2^53−1; CLI JSON uses integers. Filenames are rendered as text. Exported reports include paths and metadata: share them deliberately.
- Treemap tiles show immediate children, normalized to the visible positive-byte entries after filtering. The selected directory's own overhead is shown separately. Filtering is per-directory, not recursive. Sorting and evidence inspection remain available offline. Scanning is only available through the local server.

## Reproduce verification

```sh
python3 scripts/acquire.py
python3 -m unittest discover -s tests -v
python3 scripts/verify_real.py
npm ci
npx playwright install chromium
npm run test:browser
python3 scripts/check_tree.py
```

Node.js is only needed for browser tests. [Validation notes](docs/validation.md) explain the independent checks, controls and primary sources. [Real verification](results/real-verification.json) and [browser verification](results/browser-verification.json) contain actual run results. No physical-space recovery claim or novel disk-usage algorithm is made.
