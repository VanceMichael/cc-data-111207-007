import argparse
import json
import tempfile
from pathlib import Path

from lab import fetch, serving
from pipeline import Pipeline
from reader import inspect
from source import Source
from store import Store

FIELDS = {
    "site": {"from": "row-header"},
    "project": {"from": "column-header", "require": "unit"},
    "period": {"from": "column-header", "require": "period"},
}


def fetch_html(base, url):
    status, _, body = fetch(base + url)
    if status != 200:
        raise ValueError(f"来源返回状态 {status}")
    return body.decode("utf-8")


def preview(fixture):
    with serving(Source(fixture)) as base:
        return inspect(base, fixture)


def demo(fixture):
    """用附带页面演示合并格、脚注、结构变更与单位漂移。"""
    report = {}
    tmp = tempfile.TemporaryDirectory()
    store = Store(Path(tmp.name) / "demo.db")
    pipe = Pipeline(store)
    try:
        with serving(Source(fixture)) as base:
            pages = sorted(fixture["pages"])
            for url in pages:
                pipe.collect_page(base, url)
            report["1_初始采集_全部待确认"] = pipe.pending()

            sig_v1 = pipe.page_signature(fetch_html(base, "/v1"))
            report["2_登记映射"] = pipe.register({
                "name": "沿江日报", "signature": sig_v1,
                "target_unit": "mg/L",
                "units": {"mg/L": 1.0}, "fields": FIELDS})
            report["2_采集_v1_合并格与脚注"] = pipe.collect_page(base, "/v1")

            again = pipe.collect_page(base, "/v1")
            report["3_重跑_v1_幂等"] = {"新增事实": again["新增事实"],
                                       "事实总数": again["事实总数"]}

            report["4_结构变更_v4_旧映射不沿用"] = pipe.collect_page(base, "/v4")

            sig_v2 = pipe.page_signature(fetch_html(base, "/v2"))
            pipe.register({"name": "沿江日报-微克换算", "signature": sig_v2,
                           "target_unit": "mg/L",
                           "units": {"mg/L": 1.0, "μg/L": 0.001},
                           "fields": FIELDS})
            report["5_单位漂移_v2_嵌套表忽略"] = pipe.collect_page(base, "/v2")

            sig_v3 = pipe.page_signature(fetch_html(base, "/v3"))
            pipe.register({"name": "多指标共享时段", "signature": sig_v3,
                           "target_unit": "mg/L",
                           "units": {"mg/L": 1.0}, "fields": FIELDS})
            report["6_多指标_v3_完整表头路径"] = pipe.collect_page(base, "/v3")

            sig_v5 = pipe.page_signature(fetch_html(base, "/v5"))
            pipe.register({"name": "未知单位尝试", "signature": sig_v5,
                           "target_unit": "mg/L",
                           "units": {"mg/L": 1.0}, "fields": FIELDS})
            report["7_未知单位_v5_拒绝入库"] = pipe.collect_page(base, "/v5")

            pipe.register({"name": "沿江日报", "signature": sig_v1,
                           "target_unit": "μg/L",
                           "units": {"mg/L": 1000.0, "μg/L": 1.0},
                           "fields": FIELDS})
            pipe.collect_page(base, "/v1")
            report["8_更换映射重处理_v1_对比"] = pipe.compare("/v1")

            report["9_待确认页面"] = pipe.pending()
    finally:
        store.close()
        tmp.cleanup()
    return report


def main():
    parser = argparse.ArgumentParser(description="合并表头网页的关系化采集与映射版本")
    parser.add_argument("--fixture", type=Path,
                        default=Path(__file__).parent / "fixtures/source.json")
    parser.add_argument("--state", type=Path, default=Path("state"))
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("preview", help="旧的纯文本预览（仅列出单元格文本）")
    sub.add_parser("collect", help="采集全部页面并写入状态库")
    reg = sub.add_parser("register", help="登记字段映射（JSON 字符串或文件路径）")
    reg.add_argument("mapping")
    sub.add_parser("pending", help="查看待确认页面")
    cmp_ = sub.add_parser("compare", help="对比某页面在映射前后的结果")
    cmp_.add_argument("url")
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))

    if args.cmd is None:
        print(json.dumps(demo(fixture), ensure_ascii=False, indent=2))
        return
    if args.cmd == "preview":
        print(json.dumps(preview(fixture), ensure_ascii=False, indent=2))
        return

    args.state.mkdir(parents=True, exist_ok=True)
    store = Store(args.state / "collector.db")
    pipe = Pipeline(store)
    try:
        if args.cmd == "collect":
            with serving(Source(fixture)) as base:
                out = [pipe.collect_page(base, url)
                       for url in sorted(fixture["pages"])]
        elif args.cmd == "register":
            candidate = Path(args.mapping)
            text = (candidate.read_text(encoding="utf-8")
                    if candidate.exists() else args.mapping)
            out = pipe.register(json.loads(text))
        elif args.cmd == "pending":
            out = pipe.pending()
        else:
            out = pipe.compare(args.url)
    finally:
        store.close()
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
