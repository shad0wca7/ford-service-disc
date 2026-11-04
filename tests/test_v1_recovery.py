"""Issue #2: synthetic mixed-type archives through the complete build path."""
import io
import os
import struct
import tempfile
import unittest
from pathlib import Path

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
                self.assertIn(code + '.html', (site / 'index.html').read_text())
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
