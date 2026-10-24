# Cairn

File organization, integrity checks, and recovery.


Independent utilities collected into one private repository. Each lives under `tools/<name>/`; run its installation and commands from that directory. This is a source consolidation, not a unified application.

Original repositories and server workspaces were retained. Original histories are reachable through merge commits and `history/` tags. Unpublished source was copied from the server; it may be incomplete.

- [batch-rename-desk](tools/batch-rename-desk/README.md): A local batch-renaming application with an editable filename preview, collision checks, explicit application, and recoverable undo.
- [archive-contents-audit](tools/archive-contents-audit/README.md): An offline tool that checks whether a ZIP or TAR backup preserves a source folder’s file contents and produces an inspectable discrepancy report.
- [duplicate-file-desk](tools/duplicate-file-desk/README.md): A local duplicate-file inspection workbench with verified content groups, persistent review decisions, and portable reports.
- [folder-space-atlas](tools/folder-space-atlas/README.md): A local disk-usage explorer with an interactive treemap, inspectable file accounting, and portable offline reports.
- [parity-recovery-desk](tools/parity-recovery-desk/README.md): A local file-recovery workbench for creating PAR2 recovery packages, inspecting damage, and restoring verified copies without modifying originals.
- [text-encoding-desk](tools/text-encoding-desk/README.md): A local workbench for inspecting text under explicit character encodings and exporting verified UTF-8 copies without modifying originals.
