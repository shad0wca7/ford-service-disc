"""Viewer compatibility regression tests."""
import re
import unittest
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "viewer" / "assets" / "app.js"
APP_CSS = Path(__file__).resolve().parents[1] / "viewer" / "assets" / "app.css"


class TestViewerCompatibility(unittest.TestCase):
    def test_app_avoids_nullish_coalescing_for_chrome_74(self):
        source = APP_JS.read_text(encoding="utf-8")
        self.assertEqual(source.count("??"), 0, "Chrome 74 cannot parse nullish coalescing")

    def test_diagram_canvas_height_works_in_chrome_74(self):
        source = APP_CSS.read_text(encoding="utf-8")
        block = re.search(r"\.viewer \.canvas\{([^}]*)\}", source)
        self.assertIsNotNone(block, "diagram canvas rule is missing")
        declarations = block.group(1)
        self.assertIn("height:74vh", declarations)
        self.assertIn("max-height:860px", declarations)
        self.assertNotIn("height:min(", declarations,
                         "Chrome 74 discards CSS min() and collapses the canvas")

    def test_short_landscape_tablets_use_compact_chrome(self):
        source = APP_CSS.read_text(encoding="utf-8")
        self.assertIn("@media (max-height:700px) and (min-width:700px){", source)
        self.assertIn(":root{--hdr:48px}", source)
        self.assertIn("h1.title{font-size:19px}", source)
        self.assertIn(".hero h1{font-size:23px}", source)

    def test_css_avoids_chrome_74_structural_gaps(self):
        source = APP_CSS.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?:^|[;{])inset:",
                            "Chrome 74 ignores inset, breaking fixed bounds")
        self.assertNotIn(":is(", source,
                         "Chrome 74 ignores selectors containing :is()")


if __name__ == "__main__":
    unittest.main()
