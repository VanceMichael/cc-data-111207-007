"""SQLite 持久化：映射版本、页面状态与事实；批量写入支持回滚。"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS mappings(
  name TEXT NOT NULL,
  version INTEGER NOT NULL,
  signature TEXT NOT NULL,
  spec TEXT NOT NULL,
  created TEXT NOT NULL,
  PRIMARY KEY(name, version)
);
CREATE TABLE IF NOT EXISTS page_status(
  url TEXT PRIMARY KEY,
  signature TEXT,
  status TEXT NOT NULL,
  reason TEXT,
  mapping_name TEXT,
  mapping_version INTEGER,
  updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts(
  url TEXT NOT NULL,
  locator TEXT NOT NULL,
  mapping_name TEXT NOT NULL,
  mapping_version INTEGER NOT NULL,
  site TEXT,
  project TEXT,
  period TEXT,
  qualifier TEXT,
  value REAL,
  unit TEXT,
  std_value REAL,
  std_unit TEXT,
  footnotes TEXT,
  raw TEXT,
  PRIMARY KEY(url, locator, mapping_name, mapping_version)
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        with self.conn:
            self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    @contextmanager
    def batch(self):
        """一批写入要么全部提交，要么全部回滚。"""
        try:
            yield self
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def add_mapping(self, spec):
        row = self.conn.execute(
            "SELECT MAX(version) AS v FROM mappings WHERE name=?",
            (spec["name"],)).fetchone()
        version = (row["v"] or 0) + 1
        self.conn.execute(
            "INSERT INTO mappings VALUES (?,?,?,?,?)",
            (spec["name"], version, spec["signature"],
             json.dumps(spec, ensure_ascii=False, sort_keys=True), _now()))
        return version

    def latest_mappings(self):
        rows = self.conn.execute("""
            SELECT m.name, m.version, m.signature, m.spec FROM mappings m
            JOIN (SELECT name AS n, MAX(version) AS v FROM mappings GROUP BY name) t
              ON m.name = t.n AND m.version = t.v""").fetchall()
        return [{"name": r["name"], "version": r["version"],
                 "signature": r["signature"], "spec": json.loads(r["spec"])}
                for r in rows]

    def mapping_versions(self, name):
        return [r["version"] for r in self.conn.execute(
            "SELECT version FROM mappings WHERE name=? ORDER BY version",
            (name,)).fetchall()]

    def set_status(self, url, signature, status, reason,
                   mapping_name=None, mapping_version=None):
        self.conn.execute("""
            INSERT INTO page_status VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(url) DO UPDATE SET
              signature=excluded.signature, status=excluded.status,
              reason=excluded.reason, mapping_name=excluded.mapping_name,
              mapping_version=excluded.mapping_version, updated=excluded.updated""",
            (url, signature, status, reason, mapping_name, mapping_version, _now()))

    def status(self, url):
        row = self.conn.execute(
            "SELECT * FROM page_status WHERE url=?", (url,)).fetchone()
        return dict(row) if row else None

    def pending(self):
        return self.conn.execute(
            "SELECT * FROM page_status WHERE status<>'已采集' ORDER BY url").fetchall()

    def add_fact(self, url, mapping_name, mapping_version, fact):
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (url,
             json.dumps(fact["定位"], ensure_ascii=False, sort_keys=True),
             mapping_name, mapping_version,
             fact["采样点"], fact["项目"], fact["时段"],
             fact["定性"], fact["数值"], fact["单位"],
             fact["标准值"], fact["标准单位"],
             json.dumps(fact["脚注"], ensure_ascii=False, sort_keys=True),
             fact["原始文本"]))
        return cursor.rowcount

    def facts(self, url):
        return self.conn.execute(
            "SELECT * FROM facts WHERE url=?"
            " ORDER BY mapping_name, mapping_version, rowid",
            (url,)).fetchall()

    def fact_count(self, url=None):
        if url is None:
            return self.conn.execute("SELECT COUNT(*) AS c FROM facts").fetchone()["c"]
        return self.conn.execute(
            "SELECT COUNT(*) AS c FROM facts WHERE url=?", (url,)).fetchone()["c"]
