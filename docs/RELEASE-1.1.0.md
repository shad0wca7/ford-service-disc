# 1.1.0 — POD BAY v1 mixed-file recovery

Issue #2's type survey now restores GIF, HTM, PDF, EPL (workunit), WCF,
SWF and XML extensions from v1 records. Unidentified a865/83dc types remain
under their hexadecimal extensions unless a clear content signature is found.

Extraction rejects duplicate archive filenames, including with --force.
An existing file is unchanged only when its bytes match; differing files
require an explicit --force. Re-extract old extensionless output into a fresh
folder to remove ambiguity.

Unknown book layouts and manuals split across multiple archives now produce
an archive browser containing every book and file. Local HTML image/link
references resolve case-insensitively to the recovered names. Modern single-book
layouts retain their existing viewer. The fallback is a file browser, not a
reconstruction of the old Ford navigation application. Flash files are preserved,
not made playable in modern browsers.

Verified with 51 synthetic tests, CLI startup and Ruff. No Ford content included.
The reporter's physical disc is not available locally: full-disc validation is
still requested before marking February 2004 discs fully supported.
