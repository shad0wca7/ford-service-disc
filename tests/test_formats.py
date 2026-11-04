"""Format tests.

Everything here is synthesised in memory. No Ford content is needed to run
the suite, which is the point: these tests double as an executable
specification of the two container formats.

    python3 -m unittest discover -s tests -v
"""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fsd import idicomp  # noqa: E402
from fsd.arc import ArcError, Archive  # noqa: E402
from fsd.build import brand_parts, clean_fragment, site_title, tokens  # noqa: E402
from fsd.disc import Book, parse_epl  # noqa: E402
from fsd.extract import safe_name  # noqa: E402
from fsd.idicomp import LZError, unwrap  # noqa: E402
from fsd.iso import IsoError, SectorSource  # noqa: E402


# --------------------------------------------------------------- LZ helpers
def lit(b):
    return ('lit', b)


def tok(*bs):
    return ('tok',) + bs


def chunk(items):
    """One flag word plus up to 16 tokens."""
    assert len(items) <= 16
    flag = 0
    for i, t in enumerate(items):
        if t[0] == 'tok':
            flag |= 0x8000 >> i          # flags are consumed MSB first
    body = b''.join(bytes(t[1:]) for t in items)
    return struct.pack('<H', flag) + body


def payload(*chunks, stored=()):
    out = idicomp.MAGIC + b'\x01'
    for c in chunks:
        out += struct.pack('<h', len(c)) + c
    for s in stored:
        out += struct.pack('<h', -len(s)) + s
    return out + struct.pack('<h', 0)


class TestIdicomp(unittest.TestCase):
    def test_literals(self):
        data, _ = unwrap(payload(chunk([lit(b) for b in b'Ford'])))
        self.assertEqual(data, b'Ford')

    def test_stored_chunk(self):
        data, _ = unwrap(payload(stored=[b'raw bytes']))
        self.assertEqual(data, b'raw bytes')

    def test_short_run(self):
        # hi=0: b1 repeated lo+3 times
        data, _ = unwrap(payload(chunk([tok(0x00, 0x41)])))
        self.assertEqual(data, b'A' * 3)
        data, _ = unwrap(payload(chunk([tok(0x0F, 0x42)])))
        self.assertEqual(data, b'B' * 18)

    def test_long_run(self):
        # hi=1: third byte repeated ((b1 << 4) | lo) + 19 times
        data, _ = unwrap(payload(chunk([tok(0x10, 0x00, 0x43)])))
        self.assertEqual(data, b'C' * 19)
        data, _ = unwrap(payload(chunk([tok(0x11, 0x02, 0x44)])))
        self.assertEqual(data, b'D' * (((0x02 << 4) | 1) + 19))

    def test_short_match(self):
        # hi>=3: length = hi, distance = ((b1 << 4) | lo) + 3
        items = [lit(b) for b in b'abc'] + [tok(0x30, 0x00)]
        data, _ = unwrap(payload(chunk(items)))
        self.assertEqual(data, b'abcabc')

    def test_overlapping_match(self):
        """A match may read bytes it is itself writing — that is how the
        format encodes a repeating pattern longer than its period."""
        # history 'abc', then length 6 at distance 3
        items = [lit(b) for b in b'abc'] + [tok(0x60, 0x00)]
        data, _ = unwrap(payload(chunk(items)))
        self.assertEqual(data, b'abcabcabc')

    def test_extended_match_length(self):
        # hi=2: length = third byte + 16. lo=1 -> distance 4.
        items = [lit(b) for b in b'abcd'] + [tok(0x21, 0x00, 0x00)]
        data, _ = unwrap(payload(chunk(items)))
        self.assertEqual(len(data), 4 + 16)
        self.assertEqual(data, b'abcd' * 5)

    def test_prologue_is_zero_filled(self):
        """Matches at the very start legitimately reach back before byte 0."""
        data, _ = unwrap(payload(chunk([tok(0x30, 0x00)])))
        self.assertEqual(data, b'\0' * 3)

    def test_bad_magic(self):
        with self.assertRaises(LZError):
            unwrap(b'NOTIDICOMP\x00\x00')

    def test_prologue_covers_the_maximum_distance(self):
        """The zero prologue is exactly as long as the longest match distance
        (0xFFF + 3 = 4098), so a match can never outrun the history. The
        distance check in the decoder is defensive only."""
        self.assertEqual(idicomp.PROLOGUE, 0xFFF + 3)
        # the largest encodable distance, at the very start of a stream
        data, _ = unwrap(payload(chunk([tok(0x3F, 0xFF)])))
        self.assertEqual(data, b'\0' * 3)

    def test_strict_rejects_short_middle_chunk(self):
        """Every chunk but the last expands to exactly 16 KB."""
        two = payload(chunk([lit(0x41)]), chunk([lit(0x42)]))
        self.assertEqual(unwrap(two)[0], b'AB')          # lenient
        with self.assertRaises(LZError):
            unwrap(two, strict=True)

    def test_strict_allows_single_short_chunk(self):
        unwrap(payload(chunk([lit(0x41)])), strict=True)

    def test_consumed_offset_reported(self):
        blob = payload(chunk([lit(0x41)]))
        data, used = unwrap(blob)
        self.assertEqual(data, b'A')
        self.assertEqual(used, len(blob))


# ------------------------------------------------------------------ archive
def make_arc(files):
    names, table, blobs = b'', b'', b''
    head = 17 + len(files) * 16
    nsize = sum(len(n) + 1 for n in files)
    data_at = head + nsize
    for name, body in files.items():
        table += struct.pack('<IIII', len(names), len(name),
                             data_at + len(blobs), len(body))
        names += name.encode() + b'\0'
        blobs += body
    return (b'BAY POD' + bytes([2, 0]) + struct.pack('<II', len(files), nsize)
            + table + names + blobs)


def pack_v1_name(name):
    symbols = []
    for char in name:
        if char.isdigit():
            symbols.append(ord(char) - ord('0') + 1)
        elif 'A' <= char <= 'Z':
            symbols.append(ord(char) - ord('A') + 11)
        elif char == '_':
            symbols.append(37)
        else:
            raise ValueError(f'unencodable v1 name character: {char!r}')
    if len(symbols) > 8:
        raise ValueError('v1 names contain at most eight symbols')
    bits = 0
    for symbol in symbols + [0] * (8 - len(symbols)):
        bits = (bits << 6) | symbol
    return bits.to_bytes(6, 'big') + b'\x62\xc6'


def make_v1_arc(files):
    table, blobs = b'', b''
    data_at = 13 + len(files) * 15
    for name, body in files.items():
        table += pack_v1_name(name)
        table += struct.pack('<I', data_at + len(blobs))
        table += b'\0\0\0'
        blobs += body
    return b'POD BAY\x01\x00' + struct.pack('<I', len(files)) + table + blobs


class TestArchive(unittest.TestCase):
    def setUp(self):
        import io
        self.files = {'ONE.HTM': payload(chunk([lit(b) for b in b'hello'])),
                      'TWO.epl': payload(stored=[b'<workunit/>'])}
        self.f = io.BytesIO(make_arc(self.files))

    def test_bay_pod_v2_parses_entries(self):
        a = Archive(self.f)
        self.assertEqual(a.version, 2)
        self.assertEqual([e.name for e in a], ['ONE.HTM', 'TWO.epl'])

    def test_bay_pod_v2_decompresses(self):
        a = Archive(self.f)
        self.assertEqual(a.read(a.find('ONE.HTM')), b'hello')

    def test_pod_bay_v1_parses_and_decompresses(self):
        import io
        files = {
            'A0_ONE': payload(stored=[b'first']),
            'T50T100A': payload(chunk([lit(b) for b in b'second'])),
        }
        f = io.BytesIO(make_v1_arc(files))
        a = Archive(f)
        self.assertEqual(a.version, 1)
        self.assertEqual([e.name for e in a], ['A0_ONE.GIF', 'T50T100A.GIF'])
        self.assertEqual(
            [(e.offset, e.length) for e in a],
            [(43, len(files['A0_ONE'])),
             (43 + len(files['A0_ONE']), len(files['T50T100A']))],
        )
        self.assertEqual(a.read(a.find('A0_ONE.GIF')), b'first')
        self.assertEqual(a.read(a.find('T50T100A.GIF')), b'second')

    def test_pod_bay_v1_rejects_truncated_record_table(self):
        import io
        blob = (b'POD BAY\x01\x00' + struct.pack('<I', 1)
                + pack_v1_name('ONE') + b'\0' * 6)
        with self.assertRaisesRegex(ArcError, 'truncated v1 record table'):
            Archive(io.BytesIO(blob))

    def test_pod_bay_v1_rejects_impossible_payload_offsets(self):
        import io
        files = {
            'ONE': payload(stored=[b'first']),
            'TWO': payload(stored=[b'second']),
        }
        good = make_v1_arc(files)
        table_end = 13 + len(files) * 15
        cases = (
            ('inside record table', ((0, table_end - 1),)),
            ('past EOF', ((1, len(good) + 1),)),
            ('descending', ((0, table_end + 1), (1, table_end))),
        )
        for label, changes in cases:
            with self.subTest(label=label):
                blob = bytearray(good)
                for index, offset in changes:
                    struct.pack_into('<I', blob, 13 + index * 15 + 8, offset)
                with self.assertRaisesRegex(ArcError, 'invalid v1 payload'):
                    Archive(io.BytesIO(blob))

    def test_ext_counts(self):
        self.assertEqual(Archive(self.f).ext_counts(), {'htm': 1, 'epl': 1})

    def test_rejects_foreign_and_near_miss_magic(self):
        import io
        for magic in (b'PK\x03\x04\0\0\0', b'POD BA?', b'BAY P0D'):
            with self.subTest(magic=magic):
                with self.assertRaisesRegex(
                        ArcError, r'unsupported POD archive magic .*'
                                  r"expected b'BAY POD' or b'POD BAY'"):
                    Archive(io.BytesIO(magic + make_arc(self.files)[7:]))


# ---------------------------------------------------------------------- iso
def iso_image(stride=2048, data_off=0, label='TESTDISC'):
    """A volume descriptor is all SectorSource needs to identify the layout."""
    pvd = bytearray(2048)
    pvd[0:6] = b'\x01CD001'
    pvd[40:40 + len(label)] = label.encode().ljust(32)[:32]
    sectors = [bytes(2048)] * 16 + [bytes(pvd)]
    out = b''
    for s in sectors:
        raw = bytearray(stride)
        raw[data_off:data_off + 2048] = s
        out += bytes(raw)
    return out


class TestSectorSource(unittest.TestCase):
    def _open(self, blob):
        import io
        return SectorSource(io.BytesIO(blob))

    def test_plain_iso(self):
        s = self._open(iso_image(2048, 0))
        self.assertEqual((s.stride, s.data_off, s.raw), (2048, 0, False))

    def test_mode1_raw(self):
        s = self._open(iso_image(2352, 16))
        self.assertEqual((s.stride, s.data_off, s.raw), (2352, 16, True))

    def test_mode2_form1(self):
        s = self._open(iso_image(2352, 24))
        self.assertEqual((s.stride, s.data_off), (2352, 24))

    def test_with_subchannel(self):
        s = self._open(iso_image(2448, 16))
        self.assertEqual(s.stride, 2448)

    def test_reads_label(self):
        from fsd.iso import Iso9660
        # root record is zeroed here, so only check the label parse
        self.assertEqual(Iso9660(self._open(iso_image())).label, 'TESTDISC')

    def test_rejects_non_disc(self):
        with self.assertRaises(IsoError):
            self._open(b'\0' * 200000)


# ---------------------------------------------------------------- manifests
class TestEpl(unittest.TestCase):
    def test_basic(self):
        b = parse_epl('<workunit><type>SERVICE</type><code>SLB</code>'
                      '<vehicles><vehicle><year>2020</year><name>Mustang</name>'
                      '</vehicle></vehicles></workunit>')
        self.assertEqual((b.code, b.type, b.role), ('SLB', 'SERVICE', 'wsm'))
        self.assertEqual((b.years, b.models), (['2020'], ['Mustang']))

    def test_bare_ampersand_is_repaired(self):
        """Real manifests put an unescaped & inside a <dest> URL."""
        b = parse_epl('<workunit><type>EVTM</type><code>ELB</code><sections>'
                      '<section><title>Contents</title>'
                      '<dest>x.asp?a=1&b=2&legacy=N</dest></section>'
                      '</sections></workunit>')
        self.assertEqual((b.code, b.type), ('ELB', 'EVTM'))
        self.assertEqual(b.title, '', 'a section title must not become the book title')

    def test_unparseable_falls_back(self):
        b = parse_epl('<workunit><type>PCED</type><code>VL2</code>'
                      '<title>Gasoline Engines</title><unclosed>')
        self.assertEqual((b.code, b.type, b.title),
                         ('VL2', 'PCED', 'Gasoline Engines'))

    def test_not_a_manifest(self):
        self.assertIsNone(parse_epl('<other><thing>1</thing></other>'))

    def test_unknown_type_has_no_role(self):
        self.assertIsNone(parse_epl('<workunit><type>WIDGET</type>'
                                    '<code>ZZ</code></workunit>').role)


# -------------------------------------------------------------------- build
class TestBuildHelpers(unittest.TestCase):
    def _book(self, type_, models, years=('2020',), title=''):
        return Book(type_[:3], type_, title,
                    [{'year': y, 'name': m, 'engine': ''}
                     for y in years for m in models])

    def test_title_from_vehicle_book(self):
        self.assertEqual(
            site_title([self._book('SERVICE', ['Mustang'])]),
            '2020 Mustang Service Information')

    def test_shared_volume_does_not_name_the_disc(self):
        pced = self._book('PCED', ['Explorer', 'Escape', 'Edge'],
                          title='Gasoline Engines')
        wsm = self._book('SERVICE', ['Mustang'])
        self.assertEqual(site_title([pced, wsm]),
                         '2020 Mustang Service Information')

    def test_shared_volume_alone_uses_its_own_title(self):
        pced = self._book('PCED', ['Explorer', 'Escape', 'Edge'],
                          title='Gasoline Engines')
        self.assertEqual(site_title([pced]),
                         '2020 Gasoline Engines Service Information')

    def test_title_falls_back_to_label(self):
        self.assertEqual(site_title([], '20SLB'), '20SLB Service Information')

    def test_brand_parts(self):
        self.assertEqual(brand_parts('2020 Mustang Service Information'),
                         ('2020', 'Mustang', 'Service Information'))
        self.assertEqual(brand_parts('Ranger Service Information'),
                         ('FORD', 'Ranger', 'Service Information'))

    def test_engine_sizes_survive_tokenising(self):
        self.assertIn('5.0l', tokens('the 5.0L V8'))
        self.assertIn('2.3l', tokens('2.3L EcoBoost'))

    def test_frame_shells_are_dropped(self):
        out = clean_fragment(
            '<html><frameset cols="25%,*"><frame src="SLBLEFT.HTM">'
            '</frameset></html>', 'wsm')
        self.assertNotIn('src=', out)

    def test_images_are_rewritten_relative(self):
        out = clean_fragment('<body><img src="FOO.JPG"></body>', 'wsm')
        self.assertIn('src="content/wsm/foo.jpg"', out)
        self.assertNotIn('../', out)      # must work from a subdirectory
        self.assertIn('loading="lazy"', out)

    def test_links_become_hash_routes(self):
        out = clean_fragment('<body><a href="SLBG1234567.HTM">x</a></body>', 'wsm')
        self.assertIn('href="#/wsm/slbg1234567"', out)

    def test_dead_asp_links_are_redirected(self):
        out = clean_fragment(
            '<body><a href="/renderers/pced_2colframeset.asp?leftside=vl2s01l.htm'
            '&rightside=x">back</a></body>', 'pced')
        self.assertIn('href="#/pced/vl2s01l"', out)

    def test_external_links_open_in_a_new_tab(self):
        out = clean_fragment('<body><a href="http://example.com">x</a></body>', 'wsm')
        self.assertIn('rel="noopener"', out)


class TestSafeName(unittest.TestCase):
    def test_strips_path_traversal(self):
        for bad in ('../../etc/passwd', r'..\..\win.ini', '/abs/path'):
            self.assertNotIn('/', safe_name(bad))
            self.assertNotIn('\\', safe_name(bad))
            self.assertFalse(safe_name(bad).startswith('.'))

    def test_keeps_ordinary_names(self):
        self.assertEqual(safe_name('SLBG1234567.HTM'), 'SLBG1234567.HTM')


if __name__ == '__main__':
    unittest.main()
