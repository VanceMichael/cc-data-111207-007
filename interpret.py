"""数值判读、单位与时段词表、结构签名。"""

import hashlib
import json
import re

from grid import ParseError

KNOWN_UNITS = ("mg/L", "μg/L")
UNIT_LIKE = re.compile(r"[A-Za-zμµ]+/L")
PERIODS = ("上午", "下午", "夜间")
MISSING = {"", "—", "-", "–"}

_LIMIT = re.compile(r"[<≤]\s*(\d+(?:\.\d+)?)")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def annotate(text):
    """识别表头文本中的单位与时段词。"""
    return {
        "units": [unit for unit in KNOWN_UNITS if unit in text],
        "unknown_units": sorted({m for m in UNIT_LIKE.findall(text) if m not in KNOWN_UNITS}),
        "periods": [period for period in PERIODS if period in text],
    }


def project_name(text):
    """去掉单位与时段词后的项目名。"""
    cleaned = UNIT_LIKE.sub(" ", text)
    for period in PERIODS:
        cleaned = cleaned.replace(period, " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_value(text):
    """缺失、低于检出限与数值零分别记录，互不混淆。"""
    stripped = text.strip()
    if stripped in MISSING:
        return {"定性": "缺失", "数值": None}
    limit = _LIMIT.fullmatch(stripped)
    if limit:
        return {"定性": "低于检出限", "数值": float(limit.group(1))}
    if _NUMBER.fullmatch(stripped):
        return {"定性": None, "数值": float(stripped)}
    raise ParseError(f"数值无法解析: {text!r}")


def signature(tables):
    """结构签名：表头文本、合并方式与网格形状；数据单元格的取值不参与。"""
    canon = []
    for table in tables:
        cells = []
        for cell in sorted(table.cells, key=lambda c: (c.row, c.col)):
            cells.append([
                cell.row, cell.col, cell.rowspan, cell.colspan,
                "th" if cell.header else "td", cell.section,
                cell.text if cell.header else "",
            ])
        canon.append({"id": table.table_id, "cells": cells})
    raw = json.dumps(canon, ensure_ascii=False, sort_keys=True)
    return "sig-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
