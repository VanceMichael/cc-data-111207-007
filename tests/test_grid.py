import json
import unittest
from pathlib import Path

from grid import GridConflict, HeaderConflict, ParseError, parse_page
from interpret import annotate, parse_value, project_name, signature

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures/source.json").read_text(encoding="utf-8"))


def page(url):
    return parse_page(FIXTURE["pages"][url])


class GridTests(unittest.TestCase):
    def test_merged_cells_and_header_path(self):
        tables, notes = page("/v1")
        table = tables[0]
        self.assertEqual((table.nrows, table.ncols), (4, 3))
        cells = {(c.row, c.col): c for c in table.cells}
        first = cells[(2, 1)]
        self.assertEqual([h.text for h in first.col_path], ["总氮 mg/L", "上午"])
        self.assertEqual([h.text for h in first.row_path], ["甲站"])
        self.assertEqual(first.refs, ["1"])
        self.assertEqual(notes, {"1": "复测值"})
        second = cells[(2, 2)]
        self.assertEqual([h.text for h in second.col_path], ["总氮 mg/L", "下午"])

    def test_nested_table_ignored(self):
        tables, _ = page("/v2")
        texts = [c.text for c in tables[0].cells]
        self.assertNotIn("仅供说明", texts)
        data = tables[0].data_cells()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0].text, "200")
        self.assertTrue(data[0].nested)

    def test_repeated_header_relabels_following_rows(self):
        tables, _ = page("/v3")
        cells = {(c.row, c.col): c for c in tables[0].data_cells()}
        self.assertEqual([h.text for h in cells[(2, 1)].col_path],
                         ["总氮 mg/L", "上午"])
        self.assertEqual([h.text for h in cells[(2, 3)].col_path],
                         ["总磷 mg/L", "上午"])
        self.assertEqual([h.text for h in cells[(4, 1)].col_path],
                         ["总氮 mg/L 上午"])
        self.assertEqual([h.text for h in cells[(4, 4)].col_path],
                         ["总磷 mg/L 下午"])

    def test_value_kinds_stay_distinct(self):
        self.assertEqual(parse_value("<0.05"), {"定性": "低于检出限", "数值": 0.05})
        self.assertEqual(parse_value("—"), {"定性": "缺失", "数值": None})
        zero = parse_value("0")
        self.assertEqual(zero, {"定性": None, "数值": 0.0})
        self.assertIsNotNone(zero["数值"])
        with self.assertRaises(ParseError):
            parse_value("约0.5")

    def test_grid_conflict(self):
        html = ('<table><tr><td>A</td><td rowspan="2">B</td></tr>'
                '<tr><td colspan="2">X</td></tr></table>')
        with self.assertRaises(GridConflict):
            parse_page(html)

    def test_headers_unknown_id(self):
        html = ('<table><tr><th id="a">采样点</th></tr>'
                '<tr><td headers="b">1</td></tr></table>')
        with self.assertRaises(HeaderConflict):
            parse_page(html)

    def test_headers_pointing_at_data_cell(self):
        html = ('<table><tr><th>采样点</th><td id="v">0</td></tr>'
                '<tr><td headers="v">1</td></tr></table>')
        with self.assertRaises(HeaderConflict):
            parse_page(html)

    def test_headers_disagreeing_with_position(self):
        html = ('<table><tr><th id="a">采样点</th><th id="b">项目</th></tr>'
                '<tr><th>甲站</th><td headers="a">1</td></tr></table>')
        with self.assertRaises(HeaderConflict):
            parse_page(html)

    def test_duplicate_id(self):
        html = '<table><tr><th id="a">甲</th><th id="a">乙</th></tr></table>'
        with self.assertRaises(HeaderConflict):
            parse_page(html)

    def test_bad_span_and_unclosed_table(self):
        with self.assertRaises(ParseError):
            parse_page('<table><tr><td rowspan="x">1</td></tr></table>')
        with self.assertRaises(ParseError):
            parse_page('<table><tr><td>1</td></tr>')

    def test_unit_and_period_annotation(self):
        ann = annotate("总氮 μg/L 上午")
        self.assertEqual(ann["units"], ["μg/L"])
        self.assertEqual(ann["periods"], ["上午"])
        self.assertEqual(annotate("总氮 ng/L")["unknown_units"], ["ng/L"])
        self.assertEqual(project_name("总氮 μg/L 上午"), "总氮")

    def test_signature_tracks_structure_not_data(self):
        self.assertEqual(signature(page("/v1")[0]), signature(page("/v1")[0]))
        self.assertNotEqual(signature(page("/v1")[0]), signature(page("/v4")[0]))
        first, _ = parse_page(
            "<table><tr><th>采样点</th></tr><tr><td>1</td></tr></table>")
        second, _ = parse_page(
            "<table><tr><th>采样点</th></tr><tr><td>2</td></tr></table>")
        self.assertEqual(signature(first), signature(second))


if __name__ == "__main__":
    unittest.main()
