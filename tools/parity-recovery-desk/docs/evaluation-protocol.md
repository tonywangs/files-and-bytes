# Real-file damage protocol

The inputs are eight unmodified Twemoji SVG artworks, revision
`7a3dad4a4da30497093dab22eafba135f02308e1`, with CC BY 4.0 license evidence,
URLs, sizes and SHA-256 in `data/sources.json`. No generated fixtures substitute
for this collection. The collection is deliberately small; this is not a
throughput benchmark or a claim about large archival workloads.

Fixed settings: 256-byte blocks, 30% block redundancy. These inputs produce
33 data blocks and 10 recovery blocks with par2cmdline 0.8.1. The smallest
file is selected by byte size for the single-file mutations. There is no
random sampling or random seed. Predictions below were specified before the
first damage-matrix execution, and are encoded before execution in both
`scripts/evaluate.py` and `tests/test_core.py`.

| Case | Exact operation on disposable copies | Expected outcome |
| --- | --- | --- |
| Baseline | None; verify original collection | Intact |
| Byte corruption | XOR the first byte of smallest file with 255 | Successful repair |
| Truncation | Remove final 64 bytes of smallest file | Successful repair |
| Missing file | Delete smallest file | Successful repair |
| Insufficient recovery | Delete every data file and all `.vol*.par2` files; retain index | Insufficient recovery |
| Damaged recovery | XOR first byte of smallest file; replace every recovery volume with literal `CORRUPTED RECOVERY VOLUME` plus newline | Insufficient recovery |

The last two deliberately exhaust all recovery blocks to provide an
unambiguous failure boundary. They do not estimate tolerance to random packet
corruption or the exact one-block transition. The single missing file is
smaller than the available ten blocks. Other selections/settings may produce
different outcomes; the UI does not promise all demos are repairable.

Each case begins from fresh copies. Verification and explicit repair run in
separate fresh staging directories. Independent evaluation code reads every
published restored file and compares bytes and SHA-256 with the preserved real
source. It also checks full file accounting, no publication on failure, and
unchanged source hashes. Neither the prediction nor the independent comparison
is derived from PAR2's return code. Reports include exact mutations, engine
commands/outputs, observed exit codes, input/recovery hashes, and output hashes.
Durations are observations of that run, not benchmarks. Temporary paths in
sample reports record where that run occurred; those directories are removed.

Run `python3 scripts/evaluate.py` to regenerate the results and portable sample
reports. Run `node tests/browser.mjs` after installing the documented development
dependencies to reproduce the browser exercise. Browser checks independently
compare downloaded files and reopen each SVG in Chromium.

Additional synthetic negative controls cover unsafe embedded PAR2 paths, links,
empty files, duplicate paths, special files, changing sources, engine errors,
false-success exits, cancellation and timeout. They supplement the real-file
experiment and are not evidence of recovery quality on other datasets.
