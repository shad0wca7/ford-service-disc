"""Identify a disc and report whether this tool can read it.

The point of this command is compatibility reporting. Only a handful of the
many Ford service titles have been tested, so `fsd probe` prints everything
needed to tell whether an untested disc works — and its output is meant to be
pasted straight into a GitHub issue.
"""
import json
import random

from .arc import ArcError
from .disc import KNOWN_TYPES, book_of
from .idicomp import CHUNK, LZError, is_compressed, unwrap

#: Entries sampled per archive when checking decodability.
SAMPLE = 25


def _sample(arc, n, rng):
    if len(arc) <= n:
        return list(arc)
    idx = sorted(rng.sample(range(len(arc)), n))
    return [arc.entries[i] for i in idx]


def probe(source, sample=SAMPLE, deep=False, seed=0):
    """Inspect a disc. Returns a plain dict, ready to serialise."""
    rng = random.Random(seed)
    out = {
        'label': source.label,
        'source': source.kind,
        'origin': source.origin,
        'archives': [],
        'warnings': [],
    }
    if source.kind == 'image':
        out['sector_size'] = source.sector_size
        out['raw_sectors'] = source.raw

    refs = source.archives()
    if not refs:
        out['warnings'].append(
            'No .ARC archives found. If this disc mounts and has a '
            'CONTENT/ folder, please open an issue with its file listing.')

    for ref in refs:
        info = {'code': ref.code, 'path': ref.path, 'size': ref.size}
        try:
            arc = ref.open()
        except ArcError as ex:
            info['error'] = str(ex)
            out['archives'].append(info)
            out['warnings'].append(f'{ref.code}: {ex}')
            continue

        with arc:
            info['version'] = arc.version
            info['entries'] = len(arc)
            info['extensions'] = arc.ext_counts()
            book = book_of(arc)
            if book:
                info['book'] = {
                    'code': book.code, 'type': book.type, 'title': book.title,
                    'years': book.years, 'models': book.models,
                    'vehicles': len(book.vehicles),
                }
                if not book.role:
                    out['warnings'].append(
                        f'{ref.code}: book type {book.type!r} is not one this '
                        f'tool knows how to lay out ({", ".join(sorted(KNOWN_TYPES))}). '
                        'Extraction will still work; browse it in the generated catalog. '
                        'Please report this type.')
            else:
                out['warnings'].append(
                    f'{ref.code}: no .epl manifest, so the book type is '
                    'unknown. Extraction will still work.')

            targets = list(arc) if deep else _sample(arc, sample, rng)
            checked = failed = stored = 0
            errors = []
            for e in targets:
                try:
                    raw = arc.raw(e)
                    if not is_compressed(raw):
                        stored += 1
                        checked += 1
                        continue
                    unwrap(raw, strict=True)
                    checked += 1
                except (LZError, ArcError) as ex:
                    failed += 1
                    if len(errors) < 5:
                        errors.append(f'{e.name}: {ex}')
            info['checked'] = checked
            info['failed'] = failed
            info['stored_uncompressed'] = stored
            if errors:
                info['errors'] = errors
                out['warnings'].append(
                    f'{ref.code}: {failed}/{failed + checked} sampled entries '
                    f'failed to decode. This is the interesting case — please '
                    f'open an issue.')
        out['archives'].append(info)

    out['ok'] = (not any(a.get('failed') for a in out['archives'])
                 and not any('error' in a for a in out['archives'])
                 and bool(refs))
    return out


def report(info, out=print):
    """Human-readable version of `probe()`, formatted to paste into an issue."""
    out(f'Disc label : {info["label"]}')
    out(f'Read as    : {info["source"]}'
        + (f' ({info["sector_size"]}-byte sectors'
           + (', raw dump' if info.get('raw_sectors') else '') + ')'
           if 'sector_size' in info else ''))
    out('')
    if not info['archives']:
        out('No archives found.')
    for a in info['archives']:
        if 'error' in a:
            out(f'  {a["code"]:6s} {a["size"] / 1e6:9.1f} MB   ERROR: {a["error"]}')
            continue
        b = a.get('book')
        desc = '(no .epl manifest)'
        if b:
            who = ', '.join(b['models'][:4])
            if len(b['models']) > 4:
                who += f' +{len(b["models"]) - 4} more'
            desc = f'{b["type"]:8s} {"/".join(b["years"])} {who}'.strip()
            if b['title']:
                desc += f' [{b["title"]}]'
        out(f'  {a["code"]:6s} {a["size"] / 1e6:9.1f} MB  v{a["version"]}  '
            f'{a["entries"]:6d} entries  {desc}')
        exts = ', '.join(f'{k}:{v}' for k, v in list(a['extensions'].items())[:8])
        out(f'         {exts}')
        line = f'         decoded {a["checked"]} sampled'
        if a['stored_uncompressed']:
            line += f' ({a["stored_uncompressed"]} stored uncompressed)'
        if a['failed']:
            line += f', {a["failed"]} FAILED'
        out(line)
        for e in a.get('errors', []):
            out(f'           ! {e}')
    if info['warnings']:
        out('')
        for w in info['warnings']:
            out(f'  warning: {w}')
    out('')
    out(f'Chunk invariant: every compressed chunk expands to {CHUNK} bytes.')
    out('Result: ' + ('this disc looks readable.' if info['ok']
                      else 'something is off — please open an issue with this output.'))


def as_json(info):
    return json.dumps(info, indent=2)
