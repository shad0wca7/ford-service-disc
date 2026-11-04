"""Reader for Ford's POD archive containers (`CONTENT/<locale>/*.ARC`).

Version 2 (``BAY POD``) has a 17-byte header, 16-byte records and a separate
name table. Version 1 (``POD BAY``) has a 13-byte header followed by 15-byte
records containing packed names and absolute payload offsets. Version 1
payload lengths are the distance to the next record offset, or to EOF.

Each payload is IDICOMP-compressed — see `idicomp.py`.
"""
import os
import struct

MAGIC = b'BAY POD'
V1_MAGIC = b'POD BAY'
MAGICS = (MAGIC, V1_MAGIC)
HEADER = 17
ENTRY = 16
V1_HEADER = 13
V1_ENTRY = 15

# Byte order is the on-disc order, confirmed by issue #2's type survey.
V1_TYPES = {
    '62c6': 'GIF', '6a13': 'HTM', '94cc': 'PDF', '588e': 'EPL',
    'bc22': 'WCF', 'a88a': 'SWF', 'c348': 'XML',
}


class ArcError(Exception):
    pass


class Entry:
    __slots__ = ('name', 'offset', 'length')

    def __init__(self, name, offset, length):
        self.name, self.offset, self.length = name, offset, length

    @property
    def ext(self):
        return self.name.rsplit('.', 1)[-1].lower() if '.' in self.name else ''

    def __repr__(self):
        return f'<Entry {self.name} @{self.offset} {self.length}B>'


def _decode_v1_name(raw):
    bits = int.from_bytes(raw[:6], 'big')
    name = []
    for shift in range(42, -1, -6):
        symbol = (bits >> shift) & 0x3f
        if symbol == 0:
            continue
        if symbol <= 10:
            name.append(chr(ord('0') + symbol - 1))
        elif symbol <= 36:
            name.append(chr(ord('A') + symbol - 11))
        elif symbol == 37:
            name.append('_')
        else:
            name.append('?')
    return ''.join(name)


class Archive:
    """An open .ARC. `f` may be any seekable binary file-like object."""

    def __init__(self, f, name='<archive>'):
        self.f = f
        self.name = name
        hdr = f.read(HEADER)
        if hdr[:7] not in MAGICS:
            raise ArcError(f'{name}: unsupported POD archive magic {hdr[:7]!r} '
                           f'(expected {MAGICS[0]!r} or {MAGICS[1]!r})')
        if len(hdr) < 9:
            raise ArcError(f'{name}: truncated header')
        self.version = hdr[7]
        if hdr[:7] == V1_MAGIC and self.version == 1:
            self._read_v1(hdr)
            return
        count, nsize = struct.unpack('<II', hdr[9:17])
        table = f.read(count * ENTRY)
        names = f.read(nsize)
        if len(table) < count * ENTRY or len(names) < nsize:
            raise ArcError(f'{name}: truncated header')
        self.entries = []
        for i in range(count):
            no, nl, do, dl = struct.unpack_from('<IIII', table, i * ENTRY)
            nm = names[no:no + nl].split(b'\0')[0].decode('latin-1')
            self.entries.append(Entry(nm, do, dl))

    def _read_v1(self, hdr):
        if len(hdr) < V1_HEADER:
            raise ArcError(f'{self.name}: truncated v1 header')
        count = struct.unpack('<I', hdr[9:V1_HEADER])[0]
        table_size = count * V1_ENTRY
        table_end = V1_HEADER + table_size

        self.f.seek(0, os.SEEK_END)
        archive_size = self.f.tell()
        if table_end > archive_size:
            raise ArcError(f'{self.name}: truncated v1 record table')
        self.f.seek(V1_HEADER)
        table = self.f.read(table_size)
        if len(table) != table_size:
            raise ArcError(f'{self.name}: truncated v1 record table')

        records = []
        for i in range(count):
            record_at = i * V1_ENTRY
            raw_name = table[record_at:record_at + 8]
            data_offset = struct.unpack_from('<I', table, record_at + 8)[0]
            marker = raw_name[6:8].hex()
            extension = V1_TYPES.get(marker, marker)
            records.append((_decode_v1_name(raw_name) + '.' + extension, data_offset))

        for record_name, data_offset in records:
            if not table_end <= data_offset <= archive_size:
                raise ArcError(
                    f'{self.name}: invalid v1 payload offset {data_offset} '
                    f'for {record_name!r}')

        self.entries = []
        for i, (record_name, data_offset) in enumerate(records):
            data_end = records[i + 1][1] if i + 1 < count else archive_size
            if data_end < data_offset:
                raise ArcError(
                    f'{self.name}: invalid v1 payload bounds for {record_name!r}')
            self.entries.append(Entry(record_name, data_offset,
                                      data_end - data_offset))

    def __len__(self):
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def raw(self, entry):
        """The still-compressed payload for one entry."""
        self.f.seek(entry.offset)
        d = self.f.read(entry.length)
        if len(d) != entry.length:
            raise ArcError(f'{self.name}: short read on {entry.name}')
        return d

    def read(self, entry):
        """The decompressed contents of one entry."""
        from .idicomp import unwrap
        data, _ = unwrap(self.raw(entry))
        return data

    def find(self, name):
        low = name.lower()
        for e in self.entries:
            if e.name.lower() == low:
                return e
        return None

    def ext_counts(self):
        counts = {}
        for e in self.entries:
            counts[e.ext or '(none)'] = counts.get(e.ext or '(none)', 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def close(self):
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def open_arc(path):
    return Archive(open(path, 'rb'), os.path.basename(path))
