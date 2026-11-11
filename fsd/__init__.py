"""fsd — read Ford Technical Service Publications discs.

Reverse-engineered readers for the "BAY POD" and "POD BAY" archive containers
and the IDICOMP compression Ford used on its service manual CDs and DVDs,
plus a static web viewer to browse the result in a modern browser.

This package ships no Ford content. Bring your own disc.
"""
__version__ = '1.1.1'

from .arc import ArcError, Archive, open_arc  # noqa: F401
from .disc import Book, DiscError, open_source  # noqa: F401
from .idicomp import LZError, unwrap  # noqa: F401
from .iso import Iso9660, IsoError, SectorSource  # noqa: F401
