# Archive Contents Audit

Check whether a ZIP or TAR backup preserves a folder's regular-file contents, without extracting the archive. Python 3.10+ on Linux/macOS; no Python dependencies. SHA-256 and sizes are compared for every file. HTML reports work offline without JavaScript, remote fonts or services.

## Run

```sh
python3 archive_audit.py /path/to/source /path/to/backup.zip --output /path/to/report
# archive has a top-level backup/ directory, source does not:
python3 archive_audit.py /path/to/source /path/to/backup.tar.gz --prefix backup --output /path/to/report
```

Open `report/report.html`; `report.json` contains the same evidence. Keep the output outside the source folder. Exit codes: **0 identical**, **1 different**, **2 incomplete**. An incomplete report is never evidence of preservation, even if individual files matched. Missing/extra labels are provisional when enumeration was interrupted. Errors identify unreadable or unsupported entries; duplicate records retain their original index and name. Source and archive inventories include sizes and SHA-256 values for hashed files.

Paths are case-sensitive and Unicode is not normalized. A leading `./` is accepted; absolute paths, `..`, embedded `.` or empty components, backslashes, NULs and colon-containing components are rejected. `--prefix backup` strips exactly `backup/` from archive names; entries outside that prefix are errors, not ignored. Directory entries are inventoried but empty-directory preservation is outside the regular-file goal.

## One-command real-data demo

Requires Python, GNU/BSD `tar`, and Info-ZIP `unzip` on PATH:

```sh
python3 demo.py
```

This works offline. It checks the vendored, unchanged seven-file subset of zlib 1.3.1 against pinned hashes, creates ZIP using Python's separate zipfile CLI and TAR using the system tar, and audits clean and deliberately altered copies. The alterations remove README, replace zlib.h and add extra.txt. An independent byte oracle uses external `unzip -p` / `tar -xOf`, compares their bytes to the intended folders, then checks every reported comparison. It writes four report pairs and `demo-output/verification.json`. Open `demo-output/changed-zip/report.html`. A prebuilt visible example is [examples/report.html](examples/report.html).

The fixture selection, public release URL and release/per-file SHA-256 hashes are in [fixtures/provenance.json](fixtures/provenance.json); the upstream license is [fixtures/zlib/LICENSE](fixtures/zlib/LICENSE). The fixture is a real source-tree subset, not a fabricated backup or a claim about backup reliability in general.

```sh
python3 -m unittest discover -s tests -v
```

## Limits and interpretation

Defaults: 10,000 source entries and 10,000 archive entries; 64 MiB per file; 512 MiB source bytes and 512 MiB archive file-content bytes; 64 MiB physical archive. TAR additionally caps the decompressed container stream at 512 MiB, including headers and padding. Override with `--max-entries`, `--max-file`, `--max-total`, `--max-archive` (bytes). Exceeding any limit stops the check as incomplete; unvisited entries are not invented. Hashing uses 64 KiB blocks. ZIP central-directory metadata is parsed by Python before the entry-count check, bounded by physical archive size. These are bounded content checks, not a hardened sandbox or a CPU/memory deadline against hostile codecs. Use OS resource isolation for adversarial inputs.

Supported archives: ZIP codecs supported by the running Python, plain TAR and gzip/bzip2/xz TAR. Encryption, sparse TAR files, archive symlinks/hard links and special files are explicitly unsupported and make the check incomplete. Source symlinks and special files are not followed and also make it incomplete. Source hard links are hashed at each pathname; link topology is not verified. Permissions, ownership, timestamps, extended attributes and empty directories are not compared. ZIP CRC checks and parser/read failures become incomplete; this is a content comparison, not validation of every archive-format metadata field. TAR requires two zero terminator blocks and zero-only trailing padding; malformed later headers and concatenated TAR archives are rejected as incomplete.

Files and directories are stat-checked before/after reads and at the end; detected changes invalidate the result. This is not an atomic filesystem snapshot, and a coordinated concurrent writer can evade metadata checks. Audit a quiescent source or filesystem snapshot. Source opening requires POSIX `O_NOFOLLOW`; Windows is not supported. Parent-directory replacement races are not hardened against malicious local writers.

Ctrl-C and SIGTERM during the audit yield an incomplete report where possible. SIGKILL, machine failure, or inability to write the report cannot produce a new report. Check the process exit status and report freshness; do not reuse a previous report as proof of a new run.

## Related work

[diffoscope](https://diffoscope.org/) already supports deep comparisons of files, directories and archives. This tool claims no new comparison algorithm; it offers a small offline regular-file backup check with explicit incomplete outcomes. Implementation uses documented [zipfile](https://docs.python.org/3/library/zipfile.html) member streams and [tarfile](https://docs.python.org/3/library/tarfile.html) streaming reads, never archive extraction.
