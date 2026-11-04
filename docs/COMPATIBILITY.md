# Disc compatibility

Ford sold service information on disc under the generic "Technical Service
Publications" name for many years and across most of the range. This tool was
developed against **one** of those discs. Nothing in it is specific to that
title, but only tested discs can be listed as tested.

**Please report yours** — whether it worked or not, using the
[disc report template](../../issues/new?template=disc-report.yml). A success
is as useful as a failure: it is the only way this table grows.

Do not attach disc content, images or extracted files to a report. The output
of `fsd probe` is all that is needed.

## Confirmed

| Disc | Volume | Books | Result |
|---|---|---|---|
| 2020 Mustang Service Information | `20SLB` | SLB (SERVICE), ELB (EVTM), VL2 (PCED) | Full — 10,230/10,230 entries decode; site builds with 0 broken references |

## `POD BAY` version 1 evidence

Public MIT-licensed archive tools document the distinct v1 record table,
packed-name encoding, absolute offsets and IDICOMP payloads. This reader has
synthetic coverage for those behaviors. That is public-source archive-format
evidence, not a successful full-disc run of this implementation.

Issue #2 reports that a February 2004, 2000–2004 Service Information disc uses
the `POD BAY` version 1 signature. Its first full-disc probe ran against the
draft parser that incorrectly reused the v2 table layout; the resulting
truncated headers, garbage names and short reads exposed that mistake. The
reporter has not yet rerun the disc with the corrected v1 parser, so it is not
listed as confirmed.

## Why other discs are likely to work

The tool does not hardcode anything from the disc above:

- **Archives are found by scanning** for `*.ARC`, not by expecting
  `CONTENT/USENI4/`. Other locales and layouts are fine.
- **Version 2 books identify themselves.** Each `BAY POD` version 2 archive
  carries a `<CODE>.epl` manifest giving its type, code and the vehicles it
  covers, and that is what the tool reads. A version 2 disc using different
  codes needs no changes.
- **Filename patterns are derived** from each book's own code, with a fallback
  that detects the shared prefix from the files if the manifest and filenames
  disagree.
- **Missing books are tolerated.** A disc with only a workshop manual, or only
  wiring, builds fine.
- **The book type can be guessed** from the files if a `.epl` is missing.
- **Sector layouts are detected**, so plain ISOs, MODE1/2352 raw dumps,
  MODE2/FORM1 and 2448-byte dumps with subchannel data all read.

The strongest circumstantial evidence is the PCED volume on the tested disc:
it is a shared book that Ford ships for 23 different vehicles, which means the
same container is in use right across the range.

## Known limits

- **Only SERVICE, EVTM and PCED books get a layout.** Any other book type
  extracts to files normally, but the viewer skips it and says so. If you hit
  one, please report the type — that is exactly the information needed to add
  support.
- **Only `BAY POD` version 2 has full-disc validation.** `POD BAY` version 1
  is implemented from the public-source evidence above and synthetic
  regression tests, but still needs a complete `probe` and site build on a
  real disc with this parser.
- **Non-English discs are untested.** Nothing should depend on language, but
  the encoding fallback assumes Windows-1252 where UTF-8 fails, which may be
  wrong for other locales.
- **Rock Ridge and Joliet are not read** from images. These discs use plain
  8.3 uppercase names, so this has not mattered; a disc relying on long
  filenames would need it.

## If your disc does not work

Run the deep check, which decodes every entry rather than a sample:

```bash
python3 -m fsd probe /path/to/disc --deep
```

Then open an issue with that output. Useful extras:

- `ls /Volumes/YOURDISC` (or `dir D:\`) if no archives were found at all
- the exact error and traceback if extraction or the build failed

If `probe` is clean but the **build** produces an empty or odd-looking site,
that usually means the book uses a structure the layout code does not expect.
Extraction still gives you every file, so nothing is lost in the meantime:

```bash
python3 -m fsd extract /path/to/disc -o extracted
```
