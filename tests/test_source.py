import json
import unittest
from pathlib import Path
from reader import inspect
from lab import serving
from source import Source


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parents[1] / "fixtures/source.json").read_text(encoding="utf-8"))
        self.source = Source(self.fixture)

    def test_text_view_preserves_limit_marker(self):
        with serving(Source(self.fixture)) as base:
            self.assertIn('<0.05',inspect(base,self.fixture)['单元格文本'])

    def test_nested_text_view_is_only_text(self):
        from reader import CellText
        parser=CellText()
        parser.feed(self.fixture['pages']['/v2'])
        self.assertIn('仅供说明',parser.cells)
        self.assertIn('200',parser.cells)

    def test_unit_variants_differ(self):
        source=Source(self.fixture)
        self.assertIn('mg/L',source.handle('/v1',{})[2].decode())
        self.assertIn('μg/L',source.handle('/v2',{})[2].decode())

    def test_missing_page(self):
        self.assertEqual(Source(self.fixture).handle('/absent',{})[0],404)


if __name__ == "__main__":
    unittest.main()
