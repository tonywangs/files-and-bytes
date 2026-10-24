# Text Encoding Desk

A local browser workbench for comparing explicit character encodings and exporting verified UTF-8 copies. No account or service required. Python 3.10+ is the only runtime dependency.

```sh
python3 app.py
```

Open http://127.0.0.1:8765. If occupied, run `PORT=18765 python3 app.py` and open that port instead. The server binds only to loopback; stop it with Ctrl+C. Use on your own computer, not a shared or publicly exposed server.

## Try real files

1. Click **Load real-file demo**. These are substantive, openly licensed Vim menu translations, not synthetic text or locally generated transcodings.
2. Compare both previews using their separate dropdowns. UTF-8 reports the first invalid byte range. Latin-1 and Windows-1252 can both succeed while interpreting bytes differently: success and roundtrip equality are **not** evidence of authorial intent.
3. Select **iso-8859-1** explicitly for German and Spanish; select **koi8-r** for Russian. Upstream filenames and `scriptencoding` declarations support these decisions. Byte inspection uses decimal offsets and displays hexadecimal addresses and bytes.
4. Save the decisions project, reload, then reconnect the originals from `demo/` using the file picker. Decisions also survive reload through browser local storage. Names and SHA-256 must match; changed bytes become a new undecided file and do not inherit old decisions. Use Restore project to transfer decisions to another browser. Projects contain metadata, not original text.
5. Export the ZIP. Open `manifest.json` and the `.utf8.txt` copies in a UTF-8 reader. Included files need explicit choices and reconnected originals. Excluded entries remain accounted for. A manifest with `complete: false` is a partial batch; fix its failed/unsupported entries before treating it as complete.

`demo/exports.zip` is a verified sample export. The `.vim` originals are input text fixtures; exported copies are for text inspection, not installed Vim runtime scripts (their internal scriptencoding declarations are intentionally unchanged).

## Exact behavior and limits

- Supported: UTF-8, UTF-16LE, UTF-16BE, Windows-1252, ISO-8859-1, Windows-1251 (cp1251), KOI8-R. No detection or guessed default. UTF-16 byte order is always explicit.
- Strict Python decoding; invalid byte sequences stop conversion for that file. Preview errors identify the first invalid range, with an exclusive end offset. Other interpretations remain available.
- Every decoded code point is retained, including U+FEFF/BOM and literal U+FFFD. No BOM is added. A source signature interpreted with an incompatible codec becomes that codec's characters; the program does not override the choice. Line endings, combining characters and non-BMP characters are unchanged. Visual rendering may conceal controls, so inspect bytes when relevant.
- Each output is encoded as UTF-8, reopened, and compared with the selected Unicode sequence. This checks preservation, not intended interpretation. The separate test verifier uses system `iconv` to check the demo with an independent implementation.
- 32 files maximum, 2 MiB per original, 8 MiB connected batch; 13 MiB HTTP request cap. Oversized selections are explicitly rejected in the status area. Preview is capped at 12,000 code points; byte view at 256 bytes. Full files are converted. ZIP output uses a numeric prefix and sanitized name to prevent duplicate-name collisions or path traversal.
- Source files are only read through the browser. The stateless server receives bytes in memory and never writes uploaded files. Local storage contains decisions and hashes; clear the desk to remove them. Exported ZIPs and projects go to your browser downloads.
- Local storage availability is required for recovery; private browsing or clearing site data can remove decisions. Save a project JSON for durable recovery. Source files must be retained separately. No directory import, archive input, streaming, or background jobs.

## Reproduce and verify

```sh
python3 scripts/acquire.py
python3 -m unittest discover -s tests -v
python3 scripts/verify_export.py demo/exports.zip
```

Acquisition uses immutable upstream revisions and checks SHA-256 before writing. Offline verification uses the checked-in files. `iconv` is required for tests, not normal use. Demo provenance, licenses, byte counts, source revisions and URLs are recorded in [demo/sources.json](demo/sources.json). Original license texts are [current Vim license](demo/LICENSE) and [Vim 7.4 license](demo/LICENSE-v7.4.txt). All three originals include their translator credits. The Russian source is deliberately from Vim 7.4, before the upstream file was marked as generated from UTF-8.

Browser regression test (Node.js and Playwright, optional developer dependencies):

```sh
npm install --no-save --package-lock=false playwright@1.64.1
npx playwright install chromium
python3 scripts/test_browser.py
```

Set `DESK_URL` if using another port. The browser test imports the three real files, compares errors/previews, chooses codecs, inspects an offset, saves and reloads decisions, rejects a mismatched reconnection, restores the project, exports through the UI, and independently reopens and verifies every output. Temporary test outputs go to `/tmp`. Core controls cover malformed UTF-8/UTF-16, ambiguous single bytes, explicit UTF-16 byte order, mixed line endings, non-BMP, duplicate names, literal replacement characters, hash mismatch, exclusions and limits.

## Prior work and design basis

This is a workflow around existing encoding implementations, not a novel codec. [Python codec documentation](https://docs.python.org/3/library/codecs.html) specifies strict errors and explicit UTF-16 endian codecs. [GNU iconv documentation](https://www.gnu.org/software/libiconv/documentation/libiconv-1.18/iconv.1.html) describes an established command-line converter; this work adds comparison, persistent explicit choices and batch accounting for local browser use. It deliberately does not use browser `TextDecoder` for Latin-1: the [WHATWG encoding standard](https://encoding.spec.whatwg.org/#names-and-labels) maps Latin-1 labels to Windows-1252, while this desk exposes both independently.
