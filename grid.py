"""把页面中的 HTML 表展开成可复核的网格。

只处理结构：rowspan/colspan 占位、thead/tbody、显式 headers 关联、
重复表头与嵌套说明表；数值、单位与字段归属见 interpret.py 与 mapping.py。
"""

import re
from html.parser import HTMLParser


class ParseError(Exception):
    """页面结构无法解析。"""


class GridConflict(ParseError):
    """单元格占位相互冲突。"""


class HeaderConflict(ParseError):
    """表头关联相互冲突。"""


def _span(value, name):
    if value is None:
        return 1
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ParseError(f"{name} 属性无法解析: {value!r}") from None
    if number < 1:
        raise ParseError(f"{name} 属性必须为正整数: {value!r}")
    return number


def _norm(text):
    return re.sub(r"\s+", " ", text).strip()


class Cell:
    """表内一个单元格；col/col_path/row_path 在展开与表头解析后填充。"""

    def __init__(self, row, header, section, cell_id, headers_attr, rowspan, colspan):
        self.row = row
        self.header = header
        self.section = section
        self.cell_id = cell_id
        self.headers_attr = headers_attr
        self.rowspan = rowspan
        self.colspan = colspan
        self.text = ""
        self.refs = []
        self.nested = False
        self.col = None
        self.col_path = []
        self.row_path = []
        self.annotation = None

    def __repr__(self):
        return f"Cell({self.text!r} @{self.row},{self.col})"


class Table:
    def __init__(self, table_id):
        self.table_id = table_id
        self.cells = []
        self.grid = {}
        self.nrows = 0
        self.ncols = 0
        self.header_rows = set()
        self.thead_rows = set()

    def data_cells(self):
        return [cell for cell in self.cells if not cell.header]


_FOOTNOTE = re.compile(r"^(\d+)\s*[：:]\s*(.+)$")


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.footnotes = {}
        self._table = None
        self._depth = 0
        self._row = -1
        self._section = ""
        self._cell = None
        self._parts = []
        self._refs = []
        self._sup = False
        self._p = None

    def _close_cell(self):
        if self._cell is None:
            return
        self._cell.text = _norm("".join(self._parts))
        self._cell.refs = [_norm(ref) for ref in self._refs if _norm(ref)]
        self._table.cells.append(self._cell)
        self._cell = None
        self._parts = []
        self._refs = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            if self._table is None:
                self._table = Table(attrs.get("id") or f"table-{len(self.tables)}")
                self._row = -1
                self._section = ""
            else:
                # 嵌套的说明表不属于外层数据，整棵忽略。
                self._depth += 1
                if self._cell is not None:
                    self._cell.nested = True
            return
        if self._table is None:
            if tag == "p":
                self._p = []
            return
        if self._depth > 0:
            return
        if tag in ("thead", "tbody", "tfoot"):
            self._section = tag
        elif tag == "tr":
            self._row += 1
        elif tag in ("th", "td"):
            self._close_cell()
            self._cell = Cell(
                row=self._row,
                header=tag == "th",
                section=self._section,
                cell_id=attrs.get("id"),
                headers_attr=attrs.get("headers"),
                rowspan=_span(attrs.get("rowspan"), "rowspan"),
                colspan=_span(attrs.get("colspan"), "colspan"),
            )
        elif tag == "sup" and self._cell is not None:
            self._sup = True
        elif tag == "br" and self._cell is not None:
            self._parts.append(" ")

    def handle_endtag(self, tag):
        if tag == "table":
            if self._table is not None:
                if self._depth > 0:
                    self._depth -= 1
                else:
                    self._close_cell()
                    self.tables.append(self._table)
                    self._table = None
            return
        if self._table is None:
            if tag == "p" and self._p is not None:
                match = _FOOTNOTE.match(_norm("".join(self._p)))
                if match:
                    self.footnotes[match.group(1)] = match.group(2)
                self._p = None
            return
        if self._depth > 0:
            return
        if tag in ("thead", "tbody", "tfoot"):
            self._section = ""
        elif tag in ("th", "td", "tr"):
            self._close_cell()
        elif tag == "sup":
            self._sup = False

    def handle_data(self, data):
        if self._cell is not None and self._depth == 0:
            (self._refs if self._sup else self._parts).append(data)
        elif self._p is not None and self._table is None:
            self._p.append(data)


def _expand(table):
    """按声明的跨度占位；与既有占位重叠即网格冲突，拒绝继续。"""
    rows = {}
    for cell in table.cells:
        rows.setdefault(cell.row, []).append(cell)
    grid = {}
    for row_index in sorted(rows):
        col = 0
        for cell in rows[row_index]:
            while (row_index, col) in grid:
                col += 1
            slots = [(row_index + dr, col + dc)
                     for dr in range(cell.rowspan)
                     for dc in range(cell.colspan)]
            for slot in slots:
                if slot in grid:
                    raise GridConflict(
                        f"单元格 {cell.text!r} 与 {grid[slot].text!r} "
                        f"在第 {slot[0]} 行第 {slot[1]} 列占位冲突")
            for slot in slots:
                grid[slot] = cell
            cell.col = col
            col += cell.colspan
    table.grid = grid
    table.nrows = (max(r for r, _ in grid) + 1) if grid else 0
    table.ncols = (max(c for _, c in grid) + 1) if grid else 0
    table.thead_rows = {r for r, cells in rows.items() if cells[0].section == "thead"}
    table.header_rows = ({r for r, cells in rows.items() if all(c.header for c in cells)}
                         | table.thead_rows)


def _column_path(table, cell):
    """列头路径：tbody 里重复出现的表头块替代 thead，否则沿用 thead。"""
    local = sorted(r for r in table.header_rows
                   if r not in table.thead_rows and r < cell.row)
    if local:
        block = [local[-1]]
        while len(local) > len(block) and local[-len(block) - 1] == block[-1] - 1:
            block.append(local[-len(block) - 1])
        applicable = sorted(block)
    else:
        applicable = sorted(table.thead_rows)
    path = []
    for row_index in applicable:
        occupant = table.grid.get((row_index, cell.col))
        if occupant is not None and occupant.header and occupant not in path:
            path.append(occupant)
    return path


def _row_headers(table, cell):
    headers = []
    for col in range(cell.col):
        occupant = table.grid.get((cell.row, col))
        if (occupant is not None and occupant.header
                and occupant.row not in table.header_rows
                and occupant not in headers):
            headers.append(occupant)
    return headers


def _resolve(table, ids):
    for cell in table.cells:
        if cell.header:
            continue
        col_path = _column_path(table, cell)
        row_path = _row_headers(table, cell)
        if cell.headers_attr:
            targets = []
            for ref in cell.headers_attr.split():
                target = ids.get(ref)
                if target is None:
                    raise HeaderConflict(f"headers 引用了未知 id {ref!r}")
                if not target.header:
                    raise HeaderConflict(f"headers 引用的 {ref!r} 不是表头单元格")
                targets.append(target)
            if set(targets) != set(col_path) | set(row_path):
                raise HeaderConflict(
                    f"单元格 {cell.text!r} 的显式 headers 与位置推断不一致")
        cell.col_path = col_path
        cell.row_path = row_path


def parse_page(html):
    """解析页面，返回 (表列表, 页面脚注定义)。嵌套说明表被忽略。"""
    builder = _Builder()
    builder.feed(html)
    builder.close()
    if builder._table is not None:
        raise ParseError("表格未闭合")
    ids = {}
    for table in builder.tables:
        for cell in table.cells:
            if cell.cell_id is None:
                continue
            if cell.cell_id in ids:
                raise HeaderConflict(f"id {cell.cell_id!r} 在页面中重复出现")
            ids[cell.cell_id] = cell
    for table in builder.tables:
        _expand(table)
        _resolve(table, ids)
    return builder.tables, builder.footnotes
