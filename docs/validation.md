# Validation and prior work

## Primary sources and existing implementations

Consulted when defining the scanner:

- [Linux stat(2)](https://man7.org/linux/man-pages/man2/stat.2.html): no-follow metadata, descriptor-relative operations, metadata races and portability limits.
- [Linux inode(7)](https://man7.org/linux/man-pages/man7/inode.7.html): inode identity, size and filesystem blocks.
- [GNU Coreutils du manual](https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html) and [implementation](https://github.com/coreutils/coreutils/blob/master/src/du.c): apparent versus allocated bytes, hard-link accounting, traversal and filesystem options.
- [ncdu 2.8 manual](https://dev.yorhel.nl/ncdu/man/2_8): established interactive disk-usage navigation and export workflows. Atlas does not claim novelty; its scope is inspectable browser evidence and self-contained reports.

## Real source and reproducibility

`python3 scripts/acquire.py` downloads zlib tag v1.3.1, pinned by archive SHA-256 `17e88863f3600672ab49182f217281b6fc4d3c762bde361935e436a95214d05c`, corresponding to commit `51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf`. The full archive is bounded before extraction; all extracted file hashes are checked against `demo/provenance.json`. License evidence and upstream source links are there and in `demo/ZLIB-LICENSE`. The source includes upstream contrib licensing notices unchanged. No synthetic source is substituted for the real demo.

`python3 scripts/verify_real.py` independently traverses the acquired folder with `os.walk` and `lstat` (the scanner uses descriptor-relative `scandir`). It checks the path set, file count, every entry's raw size, allocation, device and inode, and every directory aggregate under both metrics. It invokes GNU `du --all --null --block-size=1 --one-file-system --no-dereference` with and without `--apparent-size` and compares **every entry**, not merely the root total. The corpus has no hard links, verified by inode uniqueness; thus differing first-link attribution cannot hide disagreements. Source hashes before and after must match the acquired manifest.

The observed Linux result: 257 files, 39 directories, 296 discovered entries; 4,398,621 apparent bytes and 5,160,960 allocated bytes. Every independent and GNU du comparison matched; no disagreements were suppressed. Allocation and directory overhead may differ on another filesystem. A previous sample's allocation is not a universal expected value. Generated reports are historical, with scan timestamps and scope.

## Labeled controls

`tests/test_scan.py` covers real temporary empty files, sparse files, hard links, broken and external symlinks, Unicode/HTML-like names, directory aggregates, exact-basename exclusions, entry/depth/time bounds, cancellation during traversal, missing roots, no-follow root components and real permission denial. Root execution explicitly skips the permission-denial control because root can bypass it. Filesystem boundary, unavailable allocation and concurrent directory identity replacement are mocked controls, not observations of those conditions in zlib. The time control uses a mocked monotonic clock; other traversal limits and cancellation exercise the real scanner.

`tests/browser.spec.js` exercises the actual local server with the real zlib source: scan, treemap directory zoom, breadcrumbs, filename filter, exact file evidence, sort, allocation view, JSON and HTML downloads, offline reopening, navigation and inspection. It asserts no HTTP requests on reopening. Additional temporary controls check zero-area and excluded entries, Unicode and inert markup-like filenames. Server controls reject foreign Origin/Host and arbitrary file requests. A labeled large-integer transport control verifies exact decimal evidence above 2^53 through an actual offline browser JSON export. CLI export controls also reject symlink aliases and hard-linked existing destinations to protect source contents. Browser-generated artifacts include a screenshot and a compact verification record.

The project is a local metadata explorer, not a storage-recovery estimator. Validation does not establish atomic snapshots, cross-platform filesystem semantics, or performance at every limit. Tests do not write into the real input tree. Reading source files for independent hash verification can update file access timestamps.
