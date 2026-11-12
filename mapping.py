"""字段映射：绑定结构签名与适用单位，把网格单元格落成事实字段。"""

from interpret import project_name


class MappingError(Exception):
    """映射登记或字段落实失败。"""


ROLES = ("site", "project", "period")
_SOURCES = ("row-header", "column-header")


def validate(spec):
    """登记前校验；返回规范化后的映射。映射必须绑定结构签名与适用单位。"""
    if not isinstance(spec, dict):
        raise MappingError("映射必须是对象")
    for key in ("name", "signature", "target_unit", "units", "fields"):
        if key not in spec:
            raise MappingError(f"映射缺少字段 {key}")
    if not spec["name"]:
        raise MappingError("映射名不能为空")
    if not isinstance(spec["signature"], str) or not spec["signature"]:
        raise MappingError("映射必须绑定结构签名")
    units = spec["units"]
    if not isinstance(units, dict) or not units:
        raise MappingError("映射必须声明适用单位")
    target = spec["target_unit"]
    if target not in units:
        raise MappingError("目标单位必须包含在适用单位中")
    factors = {}
    for unit, factor in units.items():
        try:
            factors[unit] = float(factor)
        except (TypeError, ValueError):
            raise MappingError(f"单位 {unit} 的换算因子无法解析") from None
        if factors[unit] <= 0:
            raise MappingError(f"单位 {unit} 的换算因子必须为正")
    if factors[target] != 1.0:
        raise MappingError("目标单位的换算因子必须为 1")
    fields = spec["fields"]
    if not isinstance(fields, dict):
        raise MappingError("映射字段必须是对象")
    for role in ROLES:
        rule = fields.get(role)
        if not isinstance(rule, dict) or rule.get("from") not in _SOURCES:
            raise MappingError(f"字段 {role} 的来源必须是 row-header 或 column-header")
    return {
        "name": spec["name"],
        "signature": spec["signature"],
        "target_unit": target,
        "units": factors,
        "fields": {role: dict(fields[role]) for role in ROLES},
    }


def _sources(rule, cell):
    return cell.row_path if rule["from"] == "row-header" else cell.col_path


def extract(spec, cell):
    """按映射从一个数据单元格落实采样点、项目、时段与单位。"""
    fields = spec["fields"]
    site = "/".join(h.text for h in _sources(fields["site"], cell)) or None
    if site is None:
        raise MappingError(f"采样点无法落实：单元格 {cell.text!r} 缺少行头")
    project_rule = fields["project"]
    candidates = _sources(project_rule, cell)
    unit_headers = [h for h in candidates if h.annotation["units"]]
    if project_rule.get("require") == "unit":
        if not unit_headers:
            raise MappingError(f"项目无法落实：单元格 {cell.text!r} 的表头路径缺少带单位的表头")
        header = unit_headers[-1]
        project = project_name(header.text)
        unit = header.annotation["units"][0]
    else:
        project = "/".join(h.text for h in candidates) or None
        unit = unit_headers[-1].annotation["units"][0] if unit_headers else None
    if project is None:
        raise MappingError(f"项目无法落实：单元格 {cell.text!r} 的表头路径为空")
    period_rule = fields["period"]
    periods = [p for h in _sources(period_rule, cell) for p in h.annotation["periods"]]
    period = "/".join(periods) or None
    if period is None and period_rule.get("require") == "period":
        raise MappingError(f"时段无法落实：单元格 {cell.text!r} 的表头路径缺少时段词")
    return {"采样点": site, "项目": project, "时段": period, "单位": unit}
