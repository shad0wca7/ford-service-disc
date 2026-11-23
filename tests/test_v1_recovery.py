"""Issue #2: synthetic mixed-type archives through the complete build path."""
import io
import os
import re
import struct
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

from test_formats import pack_v1_name, payload

from fsd.arc import Archive
from fsd.build import build
from fsd.disc import open_source
from fsd.extract import extract


def mixed(records):
    table, blobs = b'', b''
    offset = 13 + 15 * len(records)
    for stem, marker, data in records:
        body = payload(stored=[data])
        table += pack_v1_name(stem)[:6] + bytes.fromhex(marker)
        table += struct.pack('<I', offset + len(blobs)) + b'\0\0\0'
        blobs += body
    return b'POD BAY\x01\0' + struct.pack('<I', len(records)) + table + blobs


class Recovery(unittest.TestCase):
    def test_survey_types_preserved(self):
        markers = ['62c6', '6a13', '94cc', '588e', 'bc22', 'a865', 'a88a', '83dc', 'c348']
        arc = Archive(io.BytesIO(mixed([('SAME', m, b'x') for m in markers])))
        self.assertEqual([e.ext for e in arc],
                         ['gif', 'htm', 'pdf', 'epl', 'wcf', 'a865', 'swf', '83dc', 'xml'])

    def test_extract_build_and_resume(self):
        with tempfile.TemporaryDirectory() as root:
            source, dest, site = [Path(root) / p for p in ('source', 'dest', 'site')]
            source.mkdir()
            for code in ('ONE', 'TWO'):
                (source / (code + '.ARC')).write_bytes(mixed([
                    ('SAME', '6a13', b'<html><body><img src="same.gif"></body></html>'),
                    ('SAME', '62c6', b'GIF89a'), ('OTHER', 'a865', b'unknown'),
                    ('SNIFF', 'ffff', b'%PDF-1.4')]))
            with open_source(str(source)) as disc:
                result = extract(disc, str(dest), log=lambda _: None)
                self.assertTrue(result.ok, result.failed)
                self.assertEqual(result.files, 8)
                self.assertEqual(extract(disc, str(dest), log=lambda _: None).skipped, 8)
            build(str(dest), str(site), log=lambda _: None)
            self.assertIn('SAME.GIF', (site / 'content/ONE/SAME.HTM').read_text())
            for code in ('ONE', 'TWO'):
                self.assertIn(code, (site / 'catalog/all-1.html').read_text(encoding='utf-8'))
                for name in ('SAME.HTM', 'SAME.GIF', 'OTHER.a865', 'SNIFF.PDF'):
                    self.assertTrue((site / 'content' / code / name).exists())

    def test_duplicate_is_failure_even_with_force(self):
        for force in (False, True):
            with tempfile.TemporaryDirectory() as root:
                source = Path(root) / 'source'
                source.mkdir()
                (source / 'ONE.ARC').write_bytes(mixed([
                    ('SAME', '62c6', b'GIF89a'), ('SAME', '62c6', b'GIF89b')]))
                with open_source(str(source)) as disc:
                    result = extract(disc, os.path.join(root, 'dest'), force=force,
                                     log=lambda _: None)
                self.assertFalse(result.ok)
                self.assertIn('duplicate', result.failed[0][2])
                self.assertEqual(result.skipped, 0)

    def test_same_code_on_two_discs_gets_separate_directories(self):
        """A folder holding two discs repeats archive codes; nothing may collide."""
        with tempfile.TemporaryDirectory() as root:
            source, dest = Path(root) / 'source', Path(root) / 'dest'
            for sub in ('disc1', 'disc2'):
                (source / sub).mkdir(parents=True)
            (source / 'disc1' / 'ONE.ARC').write_bytes(mixed([
                ('SAME', '62c6', b'GIF89a'), ('DIFF', '83dc', b'first')]))
            (source / 'disc2' / 'ONE.ARC').write_bytes(mixed([
                ('SAME', '62c6', b'GIF89a'), ('DIFF', '83dc', b'second')]))
            with open_source(str(source)) as disc:
                result = extract(disc, str(dest), log=lambda _: None)
            self.assertTrue(result.ok, result.failed)
            self.assertEqual(result.files, 4)
            self.assertEqual((dest / 'ONE' / 'DIFF.83dc').read_bytes(), b'first')
            self.assertEqual((dest / 'ONE-2' / 'DIFF.83dc').read_bytes(), b'second')
            with open_source(str(source)) as disc:
                again = extract(disc, str(dest), log=lambda _: None)
            self.assertTrue(again.ok, again.failed)
            self.assertEqual(again.skipped, 4)

            site = Path(root) / 'site'
            build(str(dest), str(site), log=lambda _: None)
            home = (site / 'index.html').read_text(encoding='utf-8')
            self.assertIn('disc1', home)
            self.assertIn('disc2', home)
            self.assertNotIn('DIFF.83dc', home)
            self.assert_reachable(site)

    def assert_reachable(self, site):
        pending = [site / 'index.html']
        seen = set()
        while pending:
            page = pending.pop().resolve()
            if page in seen:
                continue
            seen.add(page)
            if (site / 'content') in page.parents:
                continue
            for href in re.findall(r'href="([^"]+)"', page.read_text(encoding='utf-8')):
                target = (page.parent / unquote(href)).resolve()
                self.assertTrue(target.is_file(), (page, href))
                pending.append(target)
        self.assertEqual(seen, {p for p in site.rglob('*') if p.is_file()})

    def test_paginated_catalog_with_metadata_and_reserved_filename(self):
        with tempfile.TemporaryDirectory() as root:
            dest, site = Path(root) / 'dest', Path(root) / 'site'
            for n in range(101):
                folder = dest / str(n)
                folder.mkdir(parents=True)
                (folder / 'info.epl').write_text(
                    '<book><type>TSB</type><vehicle><year>2001</year>'
                    '<name>Test Car</name></vehicle></book>')
                (folder / 'notes #1.pdf').write_bytes(b'test')
            build(str(dest), str(site), log=lambda _: None)
            home = (site / 'index.html').read_text(encoding='utf-8')
            self.assertIn('TSB (101 books)', home)
            page = (site / 'catalog/group-0-0-1.html').read_text(encoding='utf-8')
            self.assertIn('Page 1 of 2', page)
            self.assertIn('2001 Test Car', page)
            self.assert_reachable(site)
