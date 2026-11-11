"""Unpack the archives on a disc into a directory tree."""
import json
import os
import re

from .arc import ArcError
from .idicomp import LZError, is_compressed, unwrap

#: Written alongside the unpacked books so a later `build` still knows which
#: disc the files came from.
DISC_JSON = '.fsd-disc.json'


def safe_name(name):
    n = name.replace('\\', '/').split('/')[-1]
    n = n.strip().lstrip('.') or '_'
    return re.sub(r'[\x00-\x1f:*?"<>|]', '_', n)


class Result:
    def __init__(self):
        self.files = 0
        self.bytes = 0
        self.failed = []       # (archive, entry name, reason)
        self.skipped = 0
        self.books = []

    @property
    def ok(self):
        return not self.failed

    def summary(self):
        s = f'{self.files} files, {self.bytes / 1e6:.1f} MB'
        if self.skipped:
            s += f', {self.skipped} unchanged'
        if self.failed:
            s += f', {len(self.failed)} FAILED'
        return s


def extract(source, dest, only=None, validate=True, force=False,
            log=print, on_file=None):
    """Unpack `source` into `dest/<CODE>/`.

    `only` limits extraction to a set of archive codes. `validate` turns on the
    16 KB chunk check in the decoder, which is cheap and catches a misparse
    immediately rather than leaving you with a subtly corrupt file.
    """
    res = Result()
    os.makedirs(dest, exist_ok=True)
    # Remember which disc this came from: the label is the best name for the
    # site when the books themselves don't identify a single vehicle.
    with open(os.path.join(dest, DISC_JSON), 'w', encoding='utf-8') as fh:
        json.dump({'label': source.label, 'source': source.kind}, fh, indent=1)
    refs = source.archives()
    if only:
        want = {c.upper() for c in only}
        refs = [r for r in refs if r.code in want]
    if not refs:
        raise ArcError('no .ARC archives found on this disc')

    # One folder can hold several discs, so the same archive code can appear
    # twice. Give each of those archives its own directory; otherwise the
    # second one collides with the first and every differing file is reported
    # as a failure. Order the refs by path so a re-run resumes the same way.
    refs = sorted(refs, key=lambda r: (r.code, getattr(r, 'path', '')))
    used_codes = {}

    for ref in refs:
        with ref.open() as arc:
            from .disc import book_of
            book = book_of(arc)
            if book:
                res.books.append(book)
            label = book.describe() if book else ref.code
            log(f'  {label}: {len(arc)} entries')
            n = used_codes.get(ref.code, 0)
            used_codes[ref.code] = n + 1
            dirname = ref.code if not n else f'{ref.code}-{n + 1}'
            outdir = os.path.join(dest, dirname)
            os.makedirs(outdir, exist_ok=True)

            seen = set()
            for e in arc:
                name = safe_name(e.name)
                if not name:
                    res.failed.append((ref.code, e.name, 'unusable name'))
                    continue
                try:
                    raw = arc.raw(e)
                    # a few entries are stored uncompressed
                    data = unwrap(raw, strict=validate)[0] \
                        if is_compressed(raw) else raw
                except (LZError, ArcError) as ex:
                    res.failed.append((ref.code, e.name, str(ex)))
                    continue
                # Unknown v1 types keep their code unless a clear signature is known.
                if arc.version == 1 and re.fullmatch(r'[0-9a-f]{4}', e.ext):
                    head = data[:256].lstrip()
                    ext = None
                    for magic, suffix in ((b'GIF8', 'GIF'), (b'\xff\xd8\xff', 'JPG'),
                                          (b'\x89PNG', 'PNG'), (b'%PDF-', 'PDF'),
                                          (b'II*\x00', 'TIF'), (b'MM\x00*', 'TIF')):
                        if head.startswith(magic):
                            ext = suffix
                            break
                    if head.lower().startswith((b'<html', b'<!doctype html')):
                        ext = 'HTM'
                    elif head.startswith(b'<?xml'):
                        ext = 'XML'
                    if ext:
                        name = name.rsplit('.', 1)[0] + '.' + ext
                key = name.casefold()
                if key in seen:
                    res.failed.append((ref.code, name, 'duplicate archive filename'))
                    continue
                seen.add(key)
                path = os.path.join(outdir, name)
                if not force and os.path.exists(path):
                    with open(path, 'rb') as existing:
                        identical = existing.read() == data
                    if identical:
                        res.skipped += 1
                    else:
                        res.failed.append((ref.code, name, 'existing file differs; use --force'))
                    continue
                with open(path, 'wb') as fh:
                    fh.write(data)
                res.files += 1
                res.bytes += len(data)
                if on_file:
                    on_file(ref.code, name, len(data))
    return res
