#!/usr/bin/env python3
"""Turn an extracted disc into a static website.

Nothing here is specific to one title. The books present are discovered from
the ``.epl`` manifest inside each archive, and every filename pattern is
derived from the book's own code, so a disc using different codes works
without changes.

Three book types get a purpose-built layout:

    SERVICE -> wsm    workshop manual: groups, sections, procedures
    EVTM    -> elb    wiring: cells, sheets, indexes, connector face views
    PCED    -> pced   powertrain/emissions diagnosis: sections, pinpoint tests

Unknown types and multi-archive manuals get a content-preserving archive browser.
"""
import glob
import html
import json
import os
import re
import shutil
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict, defaultdict

from .disc import books_in_dir

VIEWER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'viewer')

#: Copied verbatim into content/<role>/ for each book.
MEDIA_EXT = ('.jpg', '.jpeg', '.gif', '.png', '.svg', '.pdf', '.bmp')


# ------------------------------------------------------------------- helpers
def rd_text(p):
    """Pages claim UTF-8 but a good number of them are really Windows-1252."""
    d = open(p, 'rb').read()
    if d[:2] == b'\xff\xfe':
        return d.decode('utf-16-le')
    if d[:3] == b'\xef\xbb\xbf':
        d = d[3:]
    try:
        return d.decode('utf-8')
    except UnicodeDecodeError:
        return d.decode('cp1252', 'replace')


def xml_of(p):
    return ET.fromstring(rd_text(p).lstrip('﻿'))


def txt(node, tag, default=''):
    e = node.find(tag)
    return (e.text or default).strip() if e is not None and e.text else default


def slug(name):
    return os.path.splitext(name)[0].lower()


def find_one(d, *names):
    """Case-insensitive lookup of the first of `names` that exists in `d`."""
    try:
        actual = {f.lower(): f for f in os.listdir(d)}
    except OSError:
        return None
    for n in names:
        if n.lower() in actual:
            return os.path.join(d, actual[n.lower()])
    return None


def iglob(d, pattern):
    """Case-insensitive glob within a single directory."""
    rx = re.compile(re.escape(pattern).replace(r'\*', '.*').replace(r'\?', '.')
                    + r'\Z', re.I)
    try:
        return sorted(os.path.join(d, f) for f in os.listdir(d) if rx.match(f))
    except OSError:
        return []


def rmtree(path, attempts=5):
    """shutil.rmtree, but tolerant of an indexer touching the tree mid-delete.

    A site is tens of thousands of small files; on macOS, Spotlight writing
    into a directory while we walk it makes rmtree fail with ENOTEMPTY.
    """
    for i in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if i == attempts - 1:
                raise
            time.sleep(0.25 * (i + 1))


def empty_dir(path):
    """Delete everything inside `path` while keeping `path` itself.

    The output directory is very often a bind mount — a Docker volume, an NFS
    share — and removing the mount point fails with EBUSY. Clearing the
    contents works in both cases.
    """
    for name in os.listdir(path):
        p = os.path.join(path, name)
        if os.path.isdir(p) and not os.path.islink(p):
            rmtree(p)
        else:
            os.remove(p)


def plain(fragment):
    t = re.sub(r'(?s)<[^>]+>', ' ', fragment)
    return ' '.join(html.unescape(t).split())


# ------------------------------------------------------------- HTML rewriting
STRIP = re.compile(r'(?is)<(script|style)\b.*?</\1\s*>')
HEAD = re.compile(r'(?is)^.*?<body[^>]*>')
NOBODY = re.compile(r'(?is)^\s*(?:<\?xml[^>]*\?>\s*)?(?:<!doctype[^>]*>\s*)?'
                    r'<html[^>]*>\s*(?:<head[^>]*>.*?</head>\s*)?')
TAIL = re.compile(r'(?is)</body\s*>.*$')
#: The DVD's frame shells are pure navigation scaffolding. The router sends
#: these pages to the book's home instead, so drop the frames rather than
#: leave <frame src=...> pointing at .htm files the build never writes.
FRAMES = re.compile(r'(?is)<noframes\b.*?</noframes\s*>|</?(?:frameset|frame)\b[^>]*>')


def strip_shell(raw):
    s = HEAD.sub('', raw, count=1) if re.search(r'(?i)<body[^>]*>', raw) \
        else NOBODY.sub('', raw, count=1)
    return TAIL.sub('', s, count=1)


def clean_fragment(raw, role):
    s = STRIP.sub('', raw)
    s = strip_shell(s)
    s = FRAMES.sub('', s)
    s = re.sub(r'(?is)</?(?:html|head|meta|title|body)\b[^>]*>', '', s)

    def fix_src(m):
        q, v = m.group(1), m.group(2)
        if v.lower().startswith(('http:', 'https:', 'data:')):
            return m.group(0)
        # relative to the page, so the site works from any subdirectory
        return f'src={q}content/{role}/{os.path.basename(v).lower()}{q}'
    s = re.sub(r'(?i)src=(["\'])([^"\']+)\1', fix_src, s)
    # some procedures carry hundreds of images; don't fetch them all up front
    s = re.sub(r'(?i)<img\b(?![^>]*\bloading=)',
               '<img loading="lazy" decoding="async"', s)

    def fix_href(m):
        q, v = m.group(1), m.group(2)
        low = v.lower()
        # PCED "back to section index" links point at Ford's old ASP renderer,
        # which was already dead on the disc itself.
        asp = re.search(r'pced_2colframeset\.asp\?leftside=([\w.]+?)(?:\.htm)?(?:&|$)', low)
        if asp:
            return f'href={q}#/pced/{asp.group(1)}{q}'
        if low.startswith(('http:', 'https:', 'mailto:')):
            return f'href={q}{v}{q} target="_blank" rel="noopener"'
        if low.startswith('#'):
            return m.group(0)
        frag = ''
        if '#' in v:
            v, frag = v.split('#', 1)
            frag = '#' + frag
        if low.endswith('.pdf'):
            return (f'href={q}content/{role}/{os.path.basename(v).lower()}{q} '
                    'target="_blank"')
        return f'href={q}#/{role}/{slug(os.path.basename(v))}{frag}{q}'
    s = re.sub(r'(?i)href=(["\'])([^"\']+)\1', fix_href, s)
    s = re.sub(r'(?i)\s+target=(["\']?)(rightside|leftside)\1', '', s)
    return s.strip()


# --------------------------------------------------------------------- search
TOKEN = re.compile(r"\d+\.\d+[a-z]*|[a-z0-9][a-z0-9\-']{2,}")

STOP = set('''a an and are as at be but by for from has have how in into is it its of on or
that the their there these this to was were what when where which who will with your you
if not no all any can may each other some such than then they them we our us do does did
be been being about after before over under more most only same so too very just also'''.split())


def tokens(text):
    """5.0L / 2.3L must survive tokenising: the decimal point used to split
    them into fragments too short to index, making engine variants unfindable."""
    return TOKEN.findall(text.lower())


def build_search(docs):
    """Postings are flat [docId, tf, docId, tf, ...]; the client scores BM25."""
    inv = defaultdict(list)
    lengths = []
    for _, _, _, text in docs:
        seen = {}
        for w in tokens(text):
            if w in STOP:
                continue
            seen[w] = seen.get(w, 0) + 1
        lengths.append(sum(seen.values()) or 1)
        for w, c in seen.items():
            inv[w].append(len(lengths) - 1)
            inv[w].append(min(c, 255))
    return inv, lengths


# ----------------------------------------------------------- workshop manual
def parse_wsm_toc(d, P):
    """P is the book's filename prefix, e.g. 'SLB'."""
    left = find_one(d, f'{P}LEFT.HTM', f'{P}MAIN.HTM')
    if not left:
        return [], []
    body = strip_shell(STRIP.sub('', rd_text(left)))
    grp_re = re.compile(rf'(?i){P}G\d+L\.HTM\Z')
    groups, extras, cur = [], [], None
    # walk in document order: plain "N: Name" headers, then <a> links
    for m in re.finditer(r'(?is)(<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>)|(\d+:\s*[^<]+)',
                         body):
        if m.group(1):
            href, label = m.group(2), plain(m.group(3))
            if not label:
                continue
            if grp_re.match(os.path.basename(href)):
                (cur['sections'] if cur else extras).append(
                    {'id': slug(os.path.basename(href)), 'title': label})
            else:
                extras.append({'id': slug(os.path.basename(href)), 'title': label,
                               'pdf': href.lower().endswith('.pdf')})
        else:
            cur = {'title': ' '.join(m.group(4).split()), 'sections': []}
            groups.append(cur)

    sec_re = re.compile(rf'(?i){P}S[\w]+L\.HTM\Z')
    link = re.compile(r'(?is)<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>')
    tree = []
    for g in groups:
        gnode = {'title': g['title'], 'groups': []}
        for grp in g['sections']:
            gp = find_one(d, grp['id'].upper() + '.HTM')
            secs = []
            if gp:
                gb = strip_shell(STRIP.sub('', rd_text(gp)))
                for href, lab in link.findall(gb):
                    if sec_re.match(os.path.basename(href)):
                        secs.append({'id': slug(os.path.basename(href)),
                                     'title': plain(lab)})
            gnode['groups'].append({'id': grp['id'], 'title': grp['title'],
                                    'sections': secs})
        tree.append(gnode)
    return tree, extras


def parse_wsm_section(d, P, sid):
    p = find_one(d, sid.upper() + '.HTM')
    if not p:
        return []
    b = strip_shell(STRIP.sub('', rd_text(p)))
    pat = re.compile(rf'(<a[^>]*href="({P}G\d+\.HTM)"[^>]*>(.*?)</a>)'
                     r'|(<p class=nospace>([^<]{3,80})<div class=indent>)',
                     re.I | re.S)
    items, heading = [], ''
    for m in pat.finditer(b):
        if m.group(1):
            items.append({'id': slug(m.group(2)), 'title': plain(m.group(3)),
                          'kind': heading})
        else:
            heading = ' '.join(plain(m.group(5)).split())
    return items


# ------------------------------------------------------------- wiring (EVTM)
def parse_wiring(d, P, warn=print):
    cells, titles = [], {}
    tp = find_one(d, f'{P}CELTTL.XML')
    if tp:
        for e in xml_of(tp).iter():
            if e.tag.lower() == 'cell':
                num = txt(e, 'number') or e.get('number') or ''
                ttl = txt(e, 'title') or e.get('title') or ''
                if num:
                    titles[num.zfill(3)] = ttl

    for cp in iglob(d, f'{P}CEL_*.XML'):
        cell = os.path.basename(cp)[len(P) + 4:-4]
        pages = []
        for pg in xml_of(cp).iter('page'):
            num, fl = txt(pg, 'num'), txt(pg, 'file')
            if not fl:
                continue
            meta = find_one(d, fl + '.xml')
            title = ptype = ''
            conns, grounds, splices, fuses = [], [], [], []
            if meta:
                pe = xml_of(meta).find('page')
                if pe is not None:
                    title, ptype = txt(pe, 'title'), txt(pe, 'type')
                    for c in pe.iter('conn'):
                        conns.append({'name': txt(c, 'name'), 'loc': txt(c, 'loc'),
                                      'zone': txt(c, 'zone'),
                                      'face': txt(c, 'face_view').lower(),
                                      'locview': txt(c, 'loc_view').lower()})
                    for g in pe.iter('ground'):
                        grounds.append({'name': txt(g, 'name'), 'loc': txt(g, 'loc'),
                                        'zone': txt(g, 'zone'),
                                        'locview': txt(g, 'loc_view').lower()})
                    for s in pe.iter('splice'):
                        splices.append({'name': txt(s, 'name'), 'loc': txt(s, 'loc'),
                                        'zone': txt(s, 'zone'),
                                        'locview': txt(s, 'loc_view').lower()})
                    for fu in pe.iter('fuse'):
                        fuses.append({'name': txt(fu, 'name'), 'loc': txt(fu, 'loc'),
                                      'zone': txt(fu, 'zone')})
            pages.append({'id': fl.lower(), 'num': num, 'title': title,
                          'type': ptype,
                          'svg': fl.lower() + '.svg' if find_one(d, fl + '.SVG') else None,
                          'conns': conns, 'grounds': grounds,
                          'splices': splices, 'fuses': fuses})
        cells.append({'cell': cell, 'title': titles.get(cell, ''), 'pages': pages})

    # some loc_view refs point at sheets that were never shipped; drop them so
    # the UI doesn't offer a link that goes nowhere
    ids = {p['id'] for c in cells for p in c['pages']}
    dangling = set()
    for c in cells:
        for p in c['pages']:
            for x in p['conns'] + p['grounds'] + p['splices']:
                if x.get('locview') and x['locview'] not in ids:
                    dangling.add(x['locview'])
                    x['locview'] = ''
    if dangling:
        warn(f'  dropped {len(dangling)} dangling loc_view refs: '
             + ', '.join(sorted(dangling)))

    indexes = {}
    for key in ('component', 'connector', 'ground', 'splice', 'harness'):
        p = find_one(d, f'{P}{key.upper()}_INDEX.XML')
        if not p:
            continue
        indexes[key] = [{'item': txt(e, 'item'), 'loc': txt(e, 'location_desc'),
                         'page': txt(e, 'page'), 'grid': txt(e, 'gridref'),
                         'qual': txt(e, 'qual')}
                        for e in xml_of(p).iter('entry')]
    return cells, indexes


def parse_connectors(d, P):
    out = {}
    for p in iglob(d, f'{P}CFC*.XML') + iglob(d, f'{P}CIC*.XML'):
        key = slug(os.path.basename(p))
        try:
            root = xml_of(p)
        except Exception:
            continue

        def pin(pn):
            return {'cav': pn.get('Cavity', ''), 'ckt': pn.get('CircuitNumber', ''),
                    'color': pn.get('Color', ''), 'gauge': pn.get('Guage', ''),
                    'fn': pn.get('Function', ''),
                    'term': pn.get('TerminalPartNumber', '')}

        for c in root.iter('Connector'):
            # An inline connector has two halves; each <Face> carries its own
            # gender, drawing and pin list. Older entries put <Pins> on the
            # <Connector> instead, with a single face.
            faces = []
            for f in c.findall('.//Face'):
                fl = (f.get('File') or '').lower()
                if fl and not find_one(d, fl.upper()):
                    fl = ''
                faces.append({'file': fl, 'fpn': f.get('FPN', ''),
                              'gender': f.get('Gender', '') or c.get('Gender', ''),
                              'harness': f.get('HarnessId', ''),
                              'pins': [pin(x) for x in f.findall('./Pins/Pin')]})
            loose = [pin(x) for x in c.findall('./Pins/Pin')]
            if loose and not any(f['pins'] for f in faces):
                if faces:
                    faces[0]['pins'] = loose
                else:
                    faces = [{'file': '', 'fpn': '', 'gender': c.get('Gender', ''),
                              'harness': '', 'pins': loose}]
            out[key] = {'name': c.get('CNumber', ''), 'desc': c.get('des', ''),
                        'type': c.get('Type', ''), 'color': c.get('COLOR', ''),
                        'pincount': c.get('PinCount', ''),
                        'shell': c.get('HardShell', ''), 'faces': faces}
    return out


# ----------------------------------------------------------------- PCED book
def html_meta(raw, name):
    """The content of a <meta name="..."> tag, or ''."""
    m = re.search(rf'(?i)name="{re.escape(name)}"\s+content="([^"]*)"', raw)
    return m.group(1).strip() if m else ''


def parse_pced(d, P):
    shell = re.compile(rf'(?i){P}(left|right|main|s\d+[lr])\Z')
    secs = OrderedDict()
    for p in iglob(d, '*.HTM'):
        base = slug(os.path.basename(p))
        # frame shells and section title pages carry no procedure metadata;
        # they are navigation scaffolding, not content
        if shell.match(base):
            continue
        raw = rd_text(p)
        s = html_meta(raw, 'tps_section')
        st = html_meta(raw, 'tps_section_title')
        pt = html_meta(raw, 'tps_proctitle')
        if not s and not st:
            s, st = 'z', 'Other'
        secs.setdefault((s, st), []).append({'id': base, 'title': pt or base.upper()})
    return [{'num': k[0], 'title': k[1], 'pages': v} for k, v in secs.items()]


# --------------------------------------------------------------------- title
def site_title(books, label=''):
    """Name the site after the vehicle, falling back to the disc label.

    The workshop and wiring books name one vehicle; PCED is a shared volume
    covering twenty-odd models, so it can't name the disc on its own.
    """
    def collect(bs):
        years, models = [], []
        for b in bs:
            for y in b.years:
                if y not in years:
                    years.append(y)
            for m in b.models:
                if m not in models:
                    models.append(m)
        return years, models

    years, models = collect([b for b in books if b.role in ('wsm', 'elb')])
    if models and len(models) <= 2:
        yr = years[0] if len(years) == 1 else ''
        return f'{yr} {" / ".join(models)}'.strip() + ' Service Information'
    # a shared volume on its own: name it after what it covers
    if len(books) == 1 and books[0].title:
        yrs, _ = collect(books)
        yr = yrs[0] if len(yrs) == 1 else ''
        return f'{yr} {books[0].title}'.strip() + ' Service Information'
    if label and label != '(unlabelled)':
        return f'{label} Service Information'
    return 'Ford Service Information'


def disc_label(src):
    """The label `fsd extract` recorded, or the folder name if it wasn't us."""
    from .extract import DISC_JSON
    p = os.path.join(src, DISC_JSON)
    if os.path.exists(p):
        try:
            lab = json.load(open(p, encoding='utf-8')).get('label', '')
            if lab:
                return lab
        except (OSError, ValueError):
            pass
    return os.path.basename(src.rstrip(os.sep))


def brand_parts(title):
    """Split the site title into the three pieces the header shows.

    "2020 Mustang Service Information" -> ("2020", "Mustang", "Service Information")
    """
    m = re.match(r'\A(\d{4})\s+(.+?)\s+(Service Information)\Z', title)
    if m:
        return m.group(1), m.group(2), m.group(3)
    m = re.match(r'\A(.+?)\s+(Service Information)\Z', title)
    if m:
        return 'FORD', m.group(1), m.group(2)
    return 'FORD', title, 'Service Information'


# ---------------------------------------------------------------- main build
BOOKMETA = {
    'wsm': ('Workshop Manual',
            'Service, diagnosis, removal & installation procedures'),
    'elb': ('Wiring Diagrams',
            'Schematics, component locations, connector face views'),
    'pced': ('PCED', 'Powertrain Control / Emissions Diagnosis'),
}


def build(src, out, title=None, log=print, clean=True):
    src = os.path.abspath(src)
    out = os.path.abspath(out)
    cont, data = os.path.join(out, 'content'), os.path.join(out, 'data')

    books = books_in_dir(src)
    if not books:
        raise SystemExit(
            f'No books found in {src}. Expected one subdirectory per extracted '
            'archive — run `fsd extract` first.')
    roles = [b.role for b in books]
    # Older discs split manuals across many archives, without modern navigation.
    # Keep every book and its original relative links in a simple browse layout.
    if None in roles or len(set(roles)) != len(roles):
        return build_browse(books, out, title or site_title(books, disc_label(src)),
                            log, clean)
    by_role = {b.role: b for b in books}

    version = str(int(max(os.path.getmtime(os.path.join(r, f))
                          for r, _, fs in os.walk(VIEWER) for f in fs)))
    title = title or site_title(books, disc_label(src))

    if clean and os.path.isdir(out):
        empty_dir(out)
    for d in (cont, data):
        os.makedirs(d, exist_ok=True)

    # --- app shell
    mark, name, sub = brand_parts(title)
    subs = {'__V__': version, '__TITLE__': html.escape(title),
            '__BRAND_MARK__': html.escape(mark),
            '__BRAND_NAME__': html.escape(name),
            '__BRAND_SUB__': html.escape(sub)}
    for root, _, files in os.walk(VIEWER):
        rel = os.path.relpath(root, VIEWER)
        dst = out if rel == '.' else os.path.join(out, rel)
        os.makedirs(dst, exist_ok=True)
        for fn in files:
            if fn.startswith('.'):
                continue
            dp = os.path.join(dst, fn)
            shutil.copyfile(os.path.join(root, fn), dp)
            if fn.endswith(('.html', '.js', '.css')):
                s = open(dp, encoding='utf-8').read()
                for k, v in subs.items():
                    s = s.replace(k, v)
                open(dp, 'w', encoding='utf-8').write(s)

    # --- media
    log('copying media ...')
    nmedia = 0
    for role, b in by_role.items():
        dd = os.path.join(cont, role)
        os.makedirs(dd, exist_ok=True)
        for p in glob.glob(os.path.join(b.dir, '*')):
            if not p.lower().endswith(MEDIA_EXT):
                continue
            dest = os.path.join(dd, os.path.basename(p).lower())
            if p.lower().endswith('.svg'):
                # the discs' SVGs omit the default namespace, so nothing
                # renders until it is added back
                s = open(p, 'rb').read().decode('utf-8', 'replace').lstrip('﻿')
                if not re.search(r'<svg[^>]*\sxmlns\s*=', s, re.I):
                    s = re.sub(r'<svg\b', '<svg xmlns="http://www.w3.org/2000/svg"',
                               s, count=1, flags=re.I)
                open(dest, 'w', encoding='utf-8').write(s)
            else:
                shutil.copyfile(p, dest)
            nmedia += 1
    log(f'   {nmedia} files')

    docs = []                       # (role, id, title, text)
    tree, extras, pced, cells = [], [], [], []
    indexes, connectors, counts = {}, {}, {}

    # --- workshop manual
    if 'wsm' in by_role:
        b = by_role['wsm']
        P = b.prefix
        wdir = os.path.join(cont, 'wsm')
        os.makedirs(wdir, exist_ok=True)
        tree, extras = parse_wsm_toc(b.dir, P)
        proc_title = {}
        for gnode in tree:
            for grp in gnode['groups']:
                for sec in grp['sections']:
                    sec['procs'] = parse_wsm_section(b.dir, P, sec['id'])
                    for pr in sec['procs']:
                        proc_title[pr['id']] = f"{sec['title']} – {pr['title']}"
        npages = 0
        proc_re = re.compile(rf'(?i)\A{P}g\d+\Z')
        for p in iglob(b.dir, '*.HTM'):
            base = slug(os.path.basename(p))
            frag = clean_fragment(rd_text(p), 'wsm')
            open(os.path.join(wdir, base + '.html'), 'w', encoding='utf-8').write(frag)
            npages += 1
            if proc_re.match(base) or base in (f'{P.lower()}alphaindex',
                                               f'{P.lower()}specindex'):
                docs.append(('wsm', base, proc_title.get(base) or base.upper(),
                             plain(frag)))
        # Some procedures are stored without the book-code prefix, which left
        # those TOC links dead on the original disc. Alias them.
        aliased = 0
        for p in glob.glob(os.path.join(wdir, 'g[0-9]*.html')):
            target = os.path.join(wdir, P.lower() + os.path.basename(p))
            if not os.path.exists(target):
                shutil.copyfile(p, target)
                aliased += 1
                base = P.lower() + slug(os.path.basename(p))
                frag = open(p, encoding='utf-8').read()
                docs.append(('wsm', base, proc_title.get(base) or base.upper(),
                             plain(frag)))
        log(f'  workshop pages: {npages} (+{aliased} aliased)')
        for gnode in tree:
            for grp in gnode['groups']:
                for sec in grp['sections']:
                    docs.append(('wsm', sec['id'], sec['title'],
                                 sec['title'] + ' '
                                 + ' '.join(x['title'] for x in sec.get('procs', []))))
        counts['wsm'] = sum(len(s.get('procs', [])) for g in tree
                            for gr in g['groups'] for s in gr['sections'])

    # --- PCED
    if 'pced' in by_role:
        b = by_role['pced']
        pdir = os.path.join(cont, 'pced')
        os.makedirs(pdir, exist_ok=True)
        pced = parse_pced(b.dir, b.prefix)
        ptitle = {pg['id']: f"{s['title']} – {pg['title']}"
                  for s in pced for pg in s['pages']}
        for p in iglob(b.dir, '*.HTM'):
            base = slug(os.path.basename(p))
            frag = clean_fragment(rd_text(p), 'pced')
            open(os.path.join(pdir, base + '.html'), 'w', encoding='utf-8').write(frag)
            docs.append(('pced', base, ptitle.get(base, base.upper()), plain(frag)))
        log(f'  pced pages: {len(ptitle)}')
        counts['pced'] = len(ptitle)

    # --- wiring
    if 'elb' in by_role:
        b = by_role['elb']
        cells, indexes = parse_wiring(b.dir, b.prefix, warn=log)
        connectors = parse_connectors(b.dir, b.prefix)
        for c in cells:
            for pg in c['pages']:
                body = ' '.join([pg['title']]
                                + [x['name'] for x in pg['conns']]
                                + [x['name'] for x in pg['grounds']]
                                + [x['name'] for x in pg['splices']])
                docs.append(('elb', pg['id'],
                             f"Wiring {c['cell']}-{pg['num']} – {pg['title']}", body))
        for k, cn in connectors.items():
            allpins = [x for f in cn['faces'] for x in f['pins']]
            docs.append(('conn', k, f"Connector {cn['name']} – {cn['desc']}",
                         ' '.join([cn['name'], cn['desc']]
                                  + [x['ckt'] for x in allpins]
                                  + [x['fn'] for x in allpins])))
        for key, label in (('component', 'Component index'),
                           ('connector', 'Connector index'),
                           ('ground', 'Ground index'), ('splice', 'Splice index'),
                           ('harness', 'Harness index')):
            rows = indexes.get(key, [])
            if rows:
                docs.append(('ix', key, f'{label} — wiring',
                             label + ' ' + ' '.join(r['item'] for r in rows[:400])))
        for c in cells:
            if c['pages']:
                docs.append(('cell', c['cell'],
                             f"{c['title'] or 'Cell ' + c['cell']} — wiring cell {c['cell']}",
                             (c['title'] or '') + ' '
                             + ' '.join(p['title'] or '' for p in c['pages'])))
        log(f"  wiring pages: {sum(len(c['pages']) for c in cells)}"
            f"  connectors: {len(connectors)}")
        counts['elb'] = sum(len(c['pages']) for c in cells)
        counts['conn'] = len(connectors)

    # --- reverse links: who points at this page?
    back = defaultdict(list)
    for role in ('wsm', 'pced'):
        for p in glob.glob(os.path.join(cont, role, '*.html')):
            src_id = os.path.basename(p)[:-5]
            seen = set()
            for m in re.finditer(r'href="#/(wsm|pced)/([^"#]+)',
                                 open(p, encoding='utf-8').read()):
                tgt = f'{m.group(1)}/{m.group(2)}'
                if tgt in seen or tgt == f'{role}/{src_id}':
                    continue
                seen.add(tgt)
                back[tgt].append(f'{role}/{src_id}')
    conn_sheets = defaultdict(list)
    for c in cells:
        for pg in c['pages']:
            for x in pg['conns']:
                if x['face'] and pg['id'] not in conn_sheets[x['face']]:
                    conn_sheets[x['face']].append(pg['id'])

    # --- write data
    def dump(name, obj):
        with open(os.path.join(data, name + '.json'), 'w', encoding='utf-8') as f:
            json.dump(obj, f, separators=(',', ':'))

    dump('backlinks', {'pages': dict(back), 'connSheets': dict(conn_sheets)})
    dump('wsm', {'tree': tree, 'extras': extras})
    dump('wiring', {'cells': cells, 'indexes': indexes})
    dump('connectors', connectors)
    dump('pced', pced)
    inv, lengths = build_search(docs)
    dump('search-docs', [[d[0], d[1], d[2], lengths[i]] for i, d in enumerate(docs)])
    dump('search-index', inv)

    pced_book = by_role.get('pced')
    manifest = {
        'title': title,
        'books': [{'id': r, 'code': by_role[r].code, 'name': BOOKMETA[r][0],
                   'desc': BOOKMETA[r][1]}
                  for r in ('wsm', 'elb', 'pced') if r in by_role],
        'prefixes': {r: b.prefix.lower() for r, b in by_role.items()},
        'years': sorted({y for b in books for y in b.years}),
        'pcedTitle': pced_book.title if pced_book else '',
        'pcedVehicles': pced_book.models if pced_book else [],
        'counts': counts,
    }
    dump('manifest', manifest)

    for f in ('manifest', 'wsm', 'wiring', 'connectors', 'pced', 'backlinks',
              'search-docs', 'search-index'):
        p = os.path.join(data, f + '.json')
        if os.path.exists(p):
            log(f'  data/{f}.json  {os.path.getsize(p) / 1e6:.2f} MB')
    return manifest


def build_browse(books, out, title, log, clean):
    """Content-preserving fallback; no original disc scripts are required for navigation."""
    if clean and os.path.isdir(out):
        empty_dir(out)
    os.makedirs(out, exist_ok=True)
    links = []
    total = 0
    for book in books:
        folder = os.path.basename(book.dir)
        dest = os.path.join(out, 'content', folder)
        os.makedirs(dest, exist_ok=True)
        entries = []
        filenames = {n.casefold(): n for n in os.listdir(book.dir)}

        def local_link(match, filenames=filenames):
            attr, quote, value = match.groups()
            if re.match(r'(?i)^(?:[a-z]+:|//|#)', value):
                return match.group(0)
            target, separator, fragment = value.partition('#')
            actual = filenames.get(target.replace('\\', '/').split('/')[-1].casefold())
            if actual is None:
                return match.group(0)
            return attr + '=' + quote + actual + separator + fragment + quote

        for name in sorted(os.listdir(book.dir)):
            source = os.path.join(book.dir, name)
            if not os.path.isfile(source):
                continue
            if name.lower().endswith(('.htm', '.html')):
                text = re.sub(r"(?i)(href|src)\s*=\s*([\"'])(.*?)\2", local_link,
                              rd_text(source))
                with open(os.path.join(dest, name), 'w', encoding='utf-8') as fh:
                    fh.write(text)
            else:
                shutil.copyfile(source, os.path.join(dest, name))
            entries.append('<li><a href="' + html.escape(name, quote=True) + '">' +
                           html.escape(name) + '</a></li>')
            total += 1
        # Separate listing avoids overwriting a disc's own index.html.
        listing = os.path.join(out, folder + '.html')
        with open(listing, 'w', encoding='utf-8') as fh:
            fh.write('<!doctype html><meta charset="utf-8"><title>' +
                     html.escape(book.describe()) + '</title><h1>' +
                     html.escape(book.describe()) + '</h1><base href="content/' +
                     html.escape(folder, quote=True) + '/"><ul>' + ''.join(entries) + '</ul>')
        links.append('<li><a href="' + html.escape(folder, quote=True) + '.html">' +
                     html.escape(book.describe()) + '</a></li>')
    with open(os.path.join(out, 'index.html'), 'w', encoding='utf-8') as fh:
        fh.write('<!doctype html><meta charset="utf-8"><title>' + html.escape(title) +
                 '</title><h1>' + html.escape(title) + '</h1><p>Archive browser</p><ul>' +
                 ''.join(links) + '</ul>')
    log(f'Archive browser: {len(books)} books, {total} files (original relative links preserved)')
    return {'books': len(books), 'files': total}
