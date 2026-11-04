# ford-service-disc

**Read your Ford service manual DVD without the original Windows software.**
Extracts the workshop manual, wiring diagrams and PCED off a Ford Technical
Service Publications disc and rebuilds them as a fast, searchable website you
can host on your own machine or home server.

Works on macOS, Linux and Windows. Python 3.9+, no dependencies.
**Ships no Ford content — bring your own disc.**

```bash
git clone https://github.com/shad0wca7/ford-service-disc
cd ford-service-disc
python3 -m fsd all /Volumes/20SLB -o site --serve
```

That reads the disc, unpacks it, builds the site and opens it on
<http://localhost:8848>.

---

## The problem this solves

You own a Ford service disc. It is a Windows application from around 2005 and
it will not install on Windows 10 or 11 — the installer is 32-bit, it wants a
disc volume label it cannot find, and if you do get it running it may tell you:

> Error. This volume has expired and can no longer be used.

The usual workaround is a Windows XP virtual machine. This tool skips all of
that. It reads the content directly off the disc and gives you a static
website — no installer, no VM, no date checks, no DVD drive needed once you
have an image.

The content is stored in two undocumented Ford formats: a POD archive
container with **`BAY POD`** or **`POD BAY`** magic, and an LZ77 variant called
**IDICOMP**. The formats and the evidence behind each supported version are
described in [docs/FORMAT.md](docs/FORMAT.md).

## Quick start

You need Python 3.9 or newer and the disc — mounted, copied to a folder, or as
an image file.

**1. Check the disc can be read.** This is fast and changes nothing:

```bash
python3 -m fsd probe /Volumes/20SLB
```

```
Disc label : 20SLB
Read as    : directory

  ELB         24.6 MB  v2    1882 entries  EVTM     2020 Mustang
         xml:1193, svg:686, csv:1, epl:1, wcf:1
         decoded 25 sampled
  SLB        512.3 MB  v2    7843 entries  SERVICE  2020 Mustang
         jpg:6130, htm:1707, gif:2, pdf:2, epl:1, wcf:1
         decoded 25 sampled
  VL2          4.6 MB  v2     505 entries  PCED     2020 Explorer, Escape, Aviator, Mustang +19 more [Gasoline Engines]
         gif:252, htm:250, epl:1, wcf:1, css:1
         decoded 25 sampled

Result: this disc looks readable.
```

**2. Build and serve it:**

```bash
python3 -m fsd all /Volumes/20SLB -o site --serve
```

To reach it from a phone or tablet in the garage, serve it on your network:

```bash
python3 -m fsd serve site --host 0.0.0.0
```

### No DVD drive?

Image the disc on a machine that has one, then point `fsd` at the image file.
Raw dumps (CloneCD `.img`, Alcohol, 2352-byte sectors) are read **in place** —
no conversion and no mounting, so no root or admin rights either:

```bash
python3 -m fsd all IMAGE.img -o site
```

## Commands

| Command | What it does |
|---|---|
| `fsd probe DISC` | Identify a disc and check every part of it decodes. Start here. |
| `fsd extract DISC -o extracted` | Unpack the archives to plain files and stop. |
| `fsd build extracted -o site` | Build the website from unpacked files. |
| `fsd all DISC -o site` | Extract and build in one step. |
| `fsd serve site` | Serve a built site over HTTP. |
| `fsd iso IMAGE out.iso` | Convert a raw dump to a plain ISO, if you want to mount it. |

`DISC` can be a mount point (`/Volumes/20SLB`, `D:\`), a folder holding a copy
of one, or an image file (`.iso`, `.img`, `.bin`).

Run `python3 -m fsd COMMAND --help` for the options.

## What you get

From the 2020 Mustang disc this was developed against, the site contains:

- **1,542 workshop procedures** — diagnosis and testing, removal and
  installation, specifications and torque values
- **394 wiring sheets** — schematics and component locations as zoomable
  vector graphics, not scans
- **594 connector face views** — pin-by-pin circuit, wire colour, gauge,
  function and terminal part number
- **233 PCED pages** — pinpoint tests, DTC charts and reference values

Everything is cross-searchable, and pages link both ways: each procedure lists
what links *to* it, and each connector lists the sheets it appears on.

The viewer is a static site — plain HTML, CSS and JavaScript with no
framework, no build step and no external requests. Any web server will do, and
it works fine from a subdirectory. It works on a phone, and it renders
documents on a light background on purpose: inverting a wiring diagram would
misrepresent the wire colours.

### It also repairs the disc

Some links were already dead on the original DVD. Those are fixed here:
procedures stored without their filename prefix, "back to index" links
pointing at a server-side URL Ford never shipped, references to location
sheets that were never pressed, and frame-based tables of contents that
rendered as unstyled duplicate navigation.

## Self-hosting it

The built site is static files, so any web server works — but if you want it
running permanently on a home server, there is a Compose setup in
[`docker/`](docker/) that serves it with Caddy (gzip, cache headers, health
check):

```bash
cd docker
cp .env.example .env      # point SITE at your built site
docker compose up -d
```

Build the site on your laptop and copy it over, or let the server unpack the
disc itself — mount the image and run the one-shot builder:

```bash
docker compose --profile build run --rm build
```

**The site is always a bind mount, never baked into an image.** An image with
the content in it would be a copyrighted 600 MB artefact one `docker push`
away from being published by accident.

`fsd serve` is fine for a quick look, but it is a development server. Use
Caddy, nginx or Apache for anything permanent.


## Offline on a tablet

The built site is static, so it runs fully offline on a phone or tablet. For a
diagnostic tablet in the garage, there is a tiny WebView wrapper in
[`viewer/android/`](viewer/android/): it serves the local copy through an HTTP
server bound only to the device's loopback interface, which gives the
fetch-based viewer a real same-origin URL without exposing it to the network.
Android 10 WebView requires the wrapper's app-level cleartext opt-in even for
that local origin; the server socket itself remains loopback-only. No Gradle,
no content included. Build it with the Android SDK command-line tools, copy
the built site to `/sdcard/FordManual/`, install the APK, done.

## Compatibility

**Tested against one disc so far** — 2020 Mustang (`20SLB`), which carries a
SERVICE, an EVTM and a PCED book.

The archive reader also implements the `POD BAY` version 1 layout documented
by public MIT-licensed parsers. Synthetic tests cover its packed names,
absolute offsets, derived payload lengths and IDICOMP decompression. A
reporter's February 2004 disc confirms that the signature occurs in the wild,
but that whole disc has not yet been rerun with the corrected parser.

On the fully validated `BAY POD` version 2 path, nothing in the tool is
specific to that title. It asks each archive's own manifest what book it is
and derives every filename pattern from that, so other version 2 discs in the
same product line should work. Ford sold these under the generic "Technical
Service Publications" name for many years and many models, and the PCED
volume alone covers 23 different vehicles, so that format almost certainly
spans a large part of the range.

But "should work" is not "does work". **If you have a disc, please run
`fsd probe` and [open an issue](../../issues/new?template=disc-report.yml) —
successes are as useful as failures.** See
[docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) for what is confirmed.

Book types other than SERVICE, EVTM and PCED will still extract to files; the
viewer will skip them and tell you it did.

## How it works

```
disc ──► POD archive ──► IDICOMP decompression ──► files ──► static site
         (fsd/arc.py)   (fsd/idicomp.py)                    (fsd/build.py)
```

`fsd/iso.py` reads ISO9660 directly out of an image, handling 2048, 2352 and
2448-byte sectors, so nothing needs mounting.

The `BAY POD` version 2 and IDICOMP write-up was reverse-engineered for this
project; `POD BAY` version 1 support also draws on public MIT-licensed archive
research. [docs/FORMAT.md](docs/FORMAT.md) distinguishes those evidence
sources and is released into the public domain. The test suite synthesises its
own archives and needs no Ford content, so it doubles as an executable spec:

```bash
python3 -m unittest discover -s tests -v
```

## Legal

This repository contains **software only**. It includes no Ford service
content, no disc images and no extracted files, and it never will — CI fails
the build if any appear.

The service content on your disc is copyrighted by Ford Motor Company, who
still sell access to it. This tool is for reading a disc **you own**. Do not
redistribute what comes out of it.

No access control is circumvented. The content is compressed, not encrypted,
and there is no key: the `VOLUME.ENC` file on the disc is a licence token that
plays no part in reading it, and this tool never consults it. The formats were
worked out by inspecting data on media I own, in order to keep using it on
current hardware.

Ford, Lincoln, Mercury and Motorcraft are trademarks of Ford Motor Company,
used here only to say which discs this reads. This project is not affiliated
with, endorsed by, or sponsored by Ford Motor Company.

Software is MIT licensed ([LICENSE](LICENSE)). The format documentation is
CC0 / public domain.

## See also

- [fetch-ford-service-manuals](https://github.com/iamtheyammer/fetch-ford-service-manuals)
  — downloads manuals from Ford's live PTS subscription portal. Different
  source, complementary problem: that one needs a paid subscription and an
  internet connection, this one needs a disc.

<sub>Keywords: Ford service manual DVD, Ford workshop manual CD, Ford service
disc Windows 11, Ford .ARC file, BAY POD, POD BAY, IDICOMP, Technical Service
Publications, TSP, EVTM wiring diagram, PCED, volume has expired, extract Ford
service CD, offline service manual, right to repair.</sub>

### POD BAY v1 recovery (1.1.0)

Mixed-type v1 archives now recover file extensions, reject duplicate filenames,
and retain unknown types. Older/multi-archive manuals get a complete archive
browser when the modern viewer layout does not apply. See
[1.1.0 release notes](docs/RELEASE-1.1.0.md). Please extract into a fresh output
folder when retesting issue #2; full-disc compatibility remains unverified.
