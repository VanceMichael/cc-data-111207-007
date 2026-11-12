"""采集流水线：解析 → 映射 → 存储，并提供待确认与对比视图。"""

import json

from grid import GridConflict, HeaderConflict, ParseError, parse_page
from interpret import annotate, parse_value, signature
from lab import fetch
from mapping import MappingError, extract, validate


class Pipeline:
    def __init__(self, store):
        self.store = store

    def register(self, spec):
        """登记映射；同名映射递增版本，旧版本保留。"""
        spec = validate(spec)
        with self.store.batch():
            version = self.store.add_mapping(spec)
        return {"名称": spec["name"], "版本": version, "签名": spec["signature"]}

    def page_signature(self, html):
        tables, _ = parse_page(html)
        return signature(tables)

    def collect_page(self, base, url):
        status, _, body = fetch(base + url)
        if status != 200:
            return self._defer(url, None, f"来源返回状态 {status}")
        return self.collect(url, body.decode("utf-8"))

    def collect(self, url, html):
        try:
            tables, footnotes = parse_page(html)
        except HeaderConflict as error:
            return self._defer(url, None, f"表头关联冲突：{error}")
        except GridConflict as error:
            return self._defer(url, None, f"网格冲突：{error}")
        except ParseError as error:
            return self._defer(url, None, f"解析异常：{error}")
        sig = signature(tables)
        for table in tables:
            for cell in table.cells:
                if cell.header:
                    cell.annotation = annotate(cell.text)
        mapping = self._match(sig)
        if mapping is None:
            return self._defer(url, sig, self._no_mapping_reason())
        spec = mapping["spec"]
        unknown = sorted({u for t in tables for c in t.cells if c.header
                          for u in c.annotation["unknown_units"]})
        if unknown:
            return self._defer(url, sig, f"未知单位 {'/'.join(unknown)}，拒绝自动入库")
        multi = [c.text for t in tables for c in t.cells
                 if c.header and len(c.annotation["units"]) > 1]
        if multi:
            return self._defer(url, sig, f"表头含多个单位：{'；'.join(multi)}")
        page_units = {u for t in tables for c in t.cells if c.header
                      for u in c.annotation["units"]}
        uncovered = sorted(page_units - set(spec["units"]))
        if uncovered:
            return self._defer(
                url, sig,
                f"单位 {'/'.join(uncovered)} 不在映射 {spec['name']} 的适用单位内")
        try:
            facts = self._facts(tables, footnotes, spec)
        except (ParseError, MappingError) as error:
            return self._defer(url, sig, str(error))
        added = 0
        with self.store.batch():
            self.store.set_status(url, sig, "已采集", "",
                                  spec["name"], mapping["version"])
            for fact in facts:
                added += self.store.add_fact(url, spec["name"],
                                             mapping["version"], fact)
        return {"页面": url, "状态": "已采集", "签名": sig,
                "映射": f"{spec['name']}@v{mapping['version']}",
                "新增事实": added, "事实总数": self.store.fact_count(url),
                "事实": facts}

    def pending(self):
        return [{"页面": row["url"], "签名": row["signature"],
                 "原因": row["reason"], "更新时间": row["updated"]}
                for row in self.store.pending()]

    def compare(self, url):
        versions = {}
        for row in self.store.facts(url):
            key = f"{row['mapping_name']}@v{row['mapping_version']}"
            versions.setdefault(key, []).append(_fact_view(row))
        return {"页面": url, "版本数": len(versions), "版本": versions}

    def _match(self, sig):
        for mapping in self.store.latest_mappings():
            if mapping["spec"]["signature"] == sig:
                return mapping
        return None

    def _no_mapping_reason(self):
        if self.store.latest_mappings():
            return "结构签名与已登记映射不一致，旧映射不沿用"
        return "无已登记映射"

    def _defer(self, url, sig, reason):
        with self.store.batch():
            self.store.set_status(url, sig, "待确认", reason)
        return {"页面": url, "状态": "待确认", "签名": sig, "原因": reason}

    def _facts(self, tables, footnotes, spec):
        facts = []
        for table in tables:
            for cell in table.data_cells():
                parsed = parse_value(cell.text)
                ext = extract(spec, cell)
                unit = ext["单位"]
                if unit is None:
                    raise MappingError(
                        f"单位无法落实：单元格 {cell.text!r} 的表头未标注单位")
                value = parsed["数值"]
                facts.append({
                    "采样点": ext["采样点"],
                    "项目": ext["项目"],
                    "时段": ext["时段"],
                    "定性": parsed["定性"],
                    "数值": value,
                    "单位": unit,
                    "标准值": (None if value is None
                               else round(value * spec["units"][unit], 9)),
                    "标准单位": spec["target_unit"],
                    "脚注": {ref: footnotes.get(ref) for ref in cell.refs},
                    "原始文本": cell.text,
                    "定位": {"表": table.table_id, "行": cell.row, "列": cell.col,
                             "列头路径": [h.text for h in cell.col_path],
                             "行头": [h.text for h in cell.row_path]},
                })
        return facts


def _fact_view(row):
    return {"采样点": row["site"], "项目": row["project"], "时段": row["period"],
            "定性": row["qualifier"], "数值": row["value"], "单位": row["unit"],
            "标准值": row["std_value"], "标准单位": row["std_unit"],
            "脚注": json.loads(row["footnotes"]), "原始文本": row["raw"],
            "定位": json.loads(row["locator"])}
