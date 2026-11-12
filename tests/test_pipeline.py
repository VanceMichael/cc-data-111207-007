import json
import tempfile
import unittest
from pathlib import Path

from lab import fetch, serving
from mapping import MappingError
from pipeline import Pipeline
from source import Source
from store import Store

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures/source.json").read_text(encoding="utf-8"))

FIELDS = {
    "site": {"from": "row-header"},
    "project": {"from": "column-header", "require": "unit"},
    "period": {"from": "column-header", "require": "period"},
}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "t.db")
        self.addCleanup(self.store.close)
        self.server = serving(Source(FIXTURE))
        self.base = self.server.__enter__()
        self.addCleanup(lambda: self.server.__exit__(None, None, None))
        self.pipe = Pipeline(self.store)

    def sig(self, url):
        status, _, body = fetch(self.base + url)
        self.assertEqual(status, 200)
        return self.pipe.page_signature(body.decode("utf-8"))

    def register(self, name, url, units, target):
        return self.pipe.register({
            "name": name, "signature": self.sig(url),
            "target_unit": target, "units": units, "fields": FIELDS})

    def test_collect_v1_facts_with_provenance(self):
        self.register("沿江日报", "/v1", {"mg/L": 1.0}, "mg/L")
        result = self.pipe.collect_page(self.base, "/v1")
        self.assertEqual(result["状态"], "已采集")
        self.assertEqual(result["新增事实"], 4)
        facts = {(f["采样点"], f["时段"]): f for f in result["事实"]}
        am = facts[("甲站", "上午")]
        self.assertEqual(am["项目"], "总氮")
        self.assertEqual((am["数值"], am["单位"]), (0.2, "mg/L"))
        self.assertEqual((am["标准值"], am["标准单位"]), (0.2, "mg/L"))
        self.assertEqual(am["脚注"], {"1": "复测值"})
        self.assertEqual(am["定位"]["列头路径"], ["总氮 mg/L", "上午"])
        self.assertEqual((am["定位"]["表"], am["定位"]["行"], am["定位"]["列"]),
                         ("samples", 2, 1))
        pm = facts[("甲站", "下午")]
        self.assertEqual((pm["定性"], pm["数值"]), ("低于检出限", 0.05))
        zero = facts[("乙站", "上午")]
        self.assertEqual((zero["定性"], zero["数值"]), (None, 0.0))
        missing = facts[("乙站", "下午")]
        self.assertEqual((missing["定性"], missing["数值"]), ("缺失", None))
        self.assertIsNotNone(zero["数值"])

    def test_rerun_is_idempotent(self):
        self.register("沿江日报", "/v1", {"mg/L": 1.0}, "mg/L")
        first = self.pipe.collect_page(self.base, "/v1")
        second = self.pipe.collect_page(self.base, "/v1")
        self.assertEqual(first["新增事实"], 4)
        self.assertEqual(second["新增事实"], 0)
        self.assertEqual(self.store.fact_count("/v1"), 4)

    def test_structure_change_not_silently_mapped(self):
        self.register("沿江日报", "/v1", {"mg/L": 1.0}, "mg/L")
        self.pipe.collect_page(self.base, "/v1")
        result = self.pipe.collect_page(self.base, "/v4")
        self.assertEqual(result["状态"], "待确认")
        self.assertIn("不一致", result["原因"])
        self.assertEqual(self.store.fact_count("/v4"), 0)
        pending = {p["页面"] for p in self.pipe.pending()}
        self.assertIn("/v4", pending)

    def test_unit_drift_converted_and_nested_ignored(self):
        self.register("微克版", "/v2", {"mg/L": 1.0, "μg/L": 0.001}, "mg/L")
        result = self.pipe.collect_page(self.base, "/v2")
        self.assertEqual(result["状态"], "已采集")
        self.assertEqual(result["新增事实"], 1)
        fact = result["事实"][0]
        self.assertEqual((fact["数值"], fact["单位"]), (200.0, "μg/L"))
        self.assertEqual((fact["标准值"], fact["标准单位"]), (0.2, "mg/L"))
        self.assertEqual((fact["项目"], fact["时段"]), ("总氮", "上午"))

    def test_unknown_unit_rejected(self):
        self.register("尝试", "/v5", {"mg/L": 1.0}, "mg/L")
        result = self.pipe.collect_page(self.base, "/v5")
        self.assertEqual(result["状态"], "待确认")
        self.assertIn("未知单位", result["原因"])
        self.assertIn("ng/L", result["原因"])
        self.assertEqual(self.store.fact_count("/v5"), 0)

    def test_unit_outside_mapping_rejected(self):
        self.register("仅毫克", "/v2", {"mg/L": 1.0}, "mg/L")
        result = self.pipe.collect_page(self.base, "/v2")
        self.assertEqual(result["状态"], "待确认")
        self.assertIn("适用单位", result["原因"])
        self.assertEqual(self.store.fact_count("/v2"), 0)

    def test_shared_periods_keep_full_header_path(self):
        self.register("多指标", "/v3", {"mg/L": 1.0}, "mg/L")
        result = self.pipe.collect_page(self.base, "/v3")
        self.assertEqual(result["新增事实"], 8)
        by = {(f["采样点"], f["项目"], f["时段"]): f for f in result["事实"]}
        self.assertIn(("甲站", "总磷", "下午"), by)
        self.assertEqual(by[("甲站", "总氮", "上午")]["定位"]["列头路径"],
                         ["总氮 mg/L", "上午"])
        self.assertEqual(by[("乙站", "总氮", "上午")]["定位"]["列头路径"],
                         ["总氮 mg/L 上午"])
        self.assertEqual(by[("乙站", "总氮", "下午")]["定性"], "低于检出限")
        self.assertEqual(by[("乙站", "总磷", "上午")]["定性"], "缺失")

    def test_reprocess_keeps_old_version(self):
        self.register("沿江日报", "/v1", {"mg/L": 1.0}, "mg/L")
        self.pipe.collect_page(self.base, "/v1")
        self.register("沿江日报", "/v1",
                      {"mg/L": 1000.0, "μg/L": 1.0}, "μg/L")
        again = self.pipe.collect_page(self.base, "/v1")
        self.assertEqual(again["新增事实"], 4)
        self.assertEqual(self.store.fact_count("/v1"), 8)
        compare = self.pipe.compare("/v1")
        self.assertEqual(compare["版本数"], 2)
        v1 = compare["版本"]["沿江日报@v1"]
        v2 = compare["版本"]["沿江日报@v2"]
        self.assertEqual({f["标准单位"] for f in v1}, {"mg/L"})
        self.assertEqual({f["标准单位"] for f in v2}, {"μg/L"})
        am1 = [f for f in v1 if f["采样点"] == "甲站" and f["时段"] == "上午"][0]
        am2 = [f for f in v2 if f["采样点"] == "甲站" and f["时段"] == "上午"][0]
        self.assertEqual(am1["标准值"], 0.2)
        self.assertEqual(am2["标准值"], 200.0)

    def test_conflicting_headers_rejected(self):
        html = ('<table><tr><th id="a">采样点</th><th id="b">项目 mg/L</th></tr>'
                '<tr><th>甲站</th><td headers="a">1</td></tr></table>')
        result = self.pipe.collect("/x", html)
        self.assertEqual(result["状态"], "待确认")
        self.assertIn("表头关联冲突", result["原因"])
        self.assertEqual(self.store.fact_count(), 0)

    def test_grid_conflict_rejected(self):
        html = ('<table><tr><td>A</td><td rowspan="2">B</td></tr>'
                '<tr><td colspan="2">X</td></tr></table>')
        result = self.pipe.collect("/y", html)
        self.assertEqual(result["状态"], "待确认")
        self.assertIn("网格冲突", result["原因"])

    def test_unparseable_value_rejected(self):
        html = ('<table><thead><tr><th>采样点</th><th>总氮 mg/L 上午</th></tr></thead>'
                '<tbody><tr><th>甲站</th><td>约0.5</td></tr></tbody></table>')
        sig = self.pipe.page_signature(html)
        self.pipe.register({"name": "m", "signature": sig, "target_unit": "mg/L",
                            "units": {"mg/L": 1.0}, "fields": FIELDS})
        result = self.pipe.collect("/z", html)
        self.assertEqual(result["状态"], "待确认")
        self.assertIn("数值无法解析", result["原因"])

    def test_rollback_keeps_store_clean(self):
        self.register("沿江日报", "/v1", {"mg/L": 1.0}, "mg/L")
        original = self.store.add_fact
        calls = []

        def flaky(*args):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("模拟写入故障")
            return original(*args)

        self.store.add_fact = flaky
        with self.assertRaises(RuntimeError):
            self.pipe.collect_page(self.base, "/v1")
        self.assertEqual(self.store.fact_count(), 0)
        self.assertIsNone(self.store.status("/v1"))

    def test_batch_rollback(self):
        with self.assertRaises(RuntimeError):
            with self.store.batch():
                self.store.set_status("/x", "sig-x", "已采集", "")
                raise RuntimeError("故障")
        self.assertIsNone(self.store.status("/x"))

    def test_register_validation_and_versions(self):
        with self.assertRaises(MappingError):
            self.pipe.register({"name": "x", "target_unit": "mg/L",
                                "units": {"mg/L": 1.0}, "fields": FIELDS})
        with self.assertRaises(MappingError):
            self.pipe.register({"name": "x", "signature": "sig-1",
                                "target_unit": "mg/L", "units": {},
                                "fields": FIELDS})
        with self.assertRaises(MappingError):
            self.pipe.register({"name": "x", "signature": "sig-1",
                                "target_unit": "mg/L",
                                "units": {"mg/L": 1000.0}, "fields": FIELDS})
        self.register("沿江日报", "/v1", {"mg/L": 1.0}, "mg/L")
        self.register("沿江日报", "/v1",
                      {"mg/L": 1000.0, "μg/L": 1.0}, "μg/L")
        self.assertEqual(self.store.mapping_versions("沿江日报"), [1, 2])


if __name__ == "__main__":
    unittest.main()
