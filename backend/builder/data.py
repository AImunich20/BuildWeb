"""Site data: collections imported from XAMPP MySQL (copied or read live), .sql dumps or CSV, and the
render-time templating that binds them to pages.

In page HTML:
  <div data-bw-repeat="products" data-bw-limit="6" data-bw-sort="price" data-bw-order="desc"
       data-bw-filter="category=coffee"> ...{{name}} {{price}} <img src="{{image}}"> ... </div>
      The element's content is repeated for every row. {{field}} is HTML-escaped, {{{field}}} is raw,
      {{#}} is the row number.
  Anywhere: {{products.count}}, {{products.name}} (first row), {{site.name}}, {{page.title}}, {{now.year}}.
Placeholders that do not resolve are left untouched, so imported sites using {{ }} for something else keep
working.
"""
import csv
import html as htmllib
import io
import re
import threading
import time
from datetime import date, datetime
from decimal import Decimal

import pymysql
from django.db import transaction
from django.utils import timezone

from .models import Collection, Record, slugify_th

LIVE_TTL = 15  # seconds a live MySQL result is reused
MAX_IMPORT_ROWS = 20000
_live_cache = {}
_live_lock = threading.Lock()

# A start tag whose attributes may contain ">" inside quotes (e.g. data-bw-filter="n>=10").
_ATTRS = r"""(?:\s+[^\s"'=<>/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?)*"""
REPEAT_RE = re.compile(r"<([a-zA-Z][\w-]*)(" + _ATTRS + r")\s*>", re.S)
_ATTR_RES = {}


class _Attr:
    def __init__(self, name):
        self.rx = _ATTR_RES.setdefault(name, re.compile(rf"""(?:^|\s){re.escape(name)}\s*=\s*(?:"([^"]*)"|'([^']*)')"""))

    def search(self, text):
        m = self.rx.search(text)
        if not m:
            return None
        val = htmllib.unescape(m.group(1) if m.group(1) is not None else m.group(2))
        return _Match(val)


class _Match:
    def __init__(self, v):
        self.v = v

    def group(self, i):
        return self.v


ATTR = _Attr
PLACEHOLDER_RE = re.compile(r"\{\{\{\s*([^{}\s]+?)\s*\}\}\}|\{\{\s*([^{}\s]+?)\s*\}\}")
IDENT_RE = re.compile(r"[^\w฀-๿]+")


# --- helpers --------------------------------------------------------------------------------------

def field_key(name, used=None):
    """A field name usable in {{ }}: letters (incl. Thai), digits and _."""
    key = IDENT_RE.sub("_", str(name or "").strip()).strip("_") or "field"
    if used is not None:
        base, n = key, 2
        while key in used:
            key, n = f"{base}_{n}", n + 1
        used.add(key)
    return key


def plain(v):
    """MySQL/CSV values → JSON-friendly values."""
    if v is None:
        return ""
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def infer_type(name, values, sql_type=""):
    n, t = name.lower(), (sql_type or "").lower()
    if any(k in n for k in ("image", "img", "photo", "picture", "thumbnail", "avatar", "รูป")):
        return "image"
    if any(k in n for k in ("url", "link", "website", "href")):
        return "link"
    if t.startswith(("int", "tinyint", "smallint", "bigint", "decimal", "float", "double", "mediumint")):
        return "bool" if t.startswith("tinyint(1)") else "number"
    if t.startswith(("date", "datetime", "timestamp")):
        return "date"
    if t.startswith(("text", "mediumtext", "longtext")):
        return "longtext"
    sample = [v for v in values if v not in ("", None)][:50]
    if sample and all(isinstance(v, (int, float)) or re.fullmatch(r"-?\d+(\.\d+)?", str(v)) for v in sample):
        return "number"
    if sample and any(isinstance(v, str) and len(v) > 120 for v in sample):
        return "longtext"
    if sample and all(isinstance(v, str) and re.search(r"\.(png|jpe?g|gif|webp|svg|avif)(\?|$)", v, re.I) for v in sample):
        return "image"
    return "text"


def unique_slug(site, base, exclude_id=None):
    base = slugify_th(base, "data")
    slug, n = base, 2
    while site.collections.filter(slug=slug).exclude(pk=exclude_id).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


# --- MySQL ----------------------------------------------------------------------------------------

def connect(cfg, database=None):
    kw = {"host": cfg.get("host") or "127.0.0.1", "port": int(cfg.get("port") or 3306), "user": cfg.get("user") or "root",
          "password": cfg.get("password") or "", "charset": "utf8mb4", "connect_timeout": 5,
          "cursorclass": pymysql.cursors.DictCursor}
    if cfg.get("socket"):
        kw["unix_socket"] = cfg["socket"]
    db = database if database is not None else cfg.get("name") or cfg.get("database")
    if db:
        kw["database"] = db
    try:
        return pymysql.connect(**kw)
    except pymysql.err.OperationalError as e:
        code = e.args[0] if e.args else 0
        if code == 1045:
            raise RuntimeError("ชื่อผู้ใช้หรือรหัสผ่าน MySQL ไม่ถูกต้อง") from e
        if code == 1049:
            raise RuntimeError(f"ไม่พบฐานข้อมูล “{db}”") from e
        if code in (2002, 2003):
            raise RuntimeError("เชื่อมต่อ MySQL ไม่ได้ — เปิด MySQL ใน XAMPP แล้วหรือยัง?") from e
        raise RuntimeError(f"เชื่อมต่อ MySQL ไม่ได้: {e}") from e


def qname(name):
    return "`" + str(name).replace("`", "``") + "`"


SYSTEM_DBS = {"information_schema", "mysql", "performance_schema", "sys", "phpmyadmin"}


def list_databases(cfg):
    conn = connect(cfg, database="")
    try:
        with conn.cursor() as c:
            c.execute("SHOW DATABASES")
            return [r["Database"] for r in c.fetchall() if r["Database"] not in SYSTEM_DBS]
    finally:
        conn.close()


def list_tables(cfg, database):
    conn = connect(cfg, database=database)
    try:
        with conn.cursor() as c:
            c.execute("SELECT TABLE_NAME AS t, TABLE_ROWS AS n FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s "
                      "AND TABLE_TYPE IN ('BASE TABLE','VIEW') ORDER BY TABLE_NAME", (database,))
            tables = c.fetchall()
            c.execute("SELECT TABLE_NAME AS t, COLUMN_NAME AS c, COLUMN_TYPE AS ty FROM information_schema.COLUMNS "
                      "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME, ORDINAL_POSITION", (database,))
            cols = {}
            for r in c.fetchall():
                cols.setdefault(r["t"], []).append({"name": r["c"], "type": r["ty"]})
        return [{"name": t["t"], "rows": int(t["n"] or 0), "columns": cols.get(t["t"], [])} for t in tables]
    finally:
        conn.close()


def table_columns(cfg, database, table):
    conn = connect(cfg, database=database)
    try:
        with conn.cursor() as c:
            c.execute("SELECT COLUMN_NAME AS c, COLUMN_TYPE AS ty FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s "
                      "AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION", (database, table))
            return [(r["c"], r["ty"]) for r in c.fetchall()]
    finally:
        conn.close()


def fetch_table(cfg, database, table, order="", desc=False, limit=500):
    cols = [c for c, _ in table_columns(cfg, database, table)]
    if not cols:
        raise RuntimeError(f"ไม่พบตาราง “{table}” ในฐานข้อมูล “{database}”")
    sql = f"SELECT * FROM {qname(table)}"
    if order and order in cols:  # only real column names reach the query
        sql += f" ORDER BY {qname(order)} {'DESC' if desc else 'ASC'}"
    sql += f" LIMIT {int(limit)}"
    conn = connect(cfg, database=database)
    try:
        with conn.cursor() as c:
            c.execute(sql)
            return cols, [{k: plain(v) for k, v in r.items()} for r in c.fetchall()]
    finally:
        conn.close()


# --- collections ----------------------------------------------------------------------------------

def make_fields(columns, rows, sql_types=None):
    """columns: original names → [{"name", "label", "type", "source"}] plus a source→key map."""
    used, fields, keymap = set(), [], {}
    for col in columns:
        key = field_key(col, used)
        keymap[col] = key
        values = [r.get(col) for r in rows[:200]]
        fields.append({"name": key, "label": str(col), "type": infer_type(str(col), values, (sql_types or {}).get(col, "")),
                       "source": str(col)})
    return fields, keymap


@transaction.atomic
def create_collection(site, name, columns, rows, sql_types=None, **extra):
    fields, keymap = make_fields(columns, rows, sql_types)
    col = Collection.objects.create(site=site, name=name[:120], slug=unique_slug(site, extra.pop("slug", "") or name),
                                    fields=fields, last_synced=timezone.now(), **extra)
    if col.mode == Collection.COPY:
        Record.objects.bulk_create([
            Record(collection=col, position=i, data={keymap[k]: plain(v) for k, v in r.items() if k in keymap})
            for i, r in enumerate(rows[:MAX_IMPORT_ROWS])
        ], batch_size=500)
    return col


def import_mysql(site, connection, database, table, mode="copy", name=""):
    cfg = connection.as_config(database)
    types = dict(table_columns(cfg, database, table))
    cols, rows = fetch_table(cfg, database, table, limit=MAX_IMPORT_ROWS if mode == "copy" else 200)
    return create_collection(site, name or table, cols, rows, sql_types=types, mode=mode, connection=connection,
                             source_database=database, source_table=table)


@transaction.atomic
def resync(col):
    """Copy mode: replace the rows with the current MySQL table (fields are kept, new columns added)."""
    if not (col.connection and col.source_table):
        raise RuntimeError("ชุดข้อมูลนี้ไม่ได้มาจาก MySQL")
    cfg = col.connection.as_config(col.source_database)
    types = dict(table_columns(cfg, col.source_database, col.source_table))
    cols, rows = fetch_table(cfg, col.source_database, col.source_table, limit=MAX_IMPORT_ROWS)
    by_source = {f.get("source", f["name"]): f["name"] for f in col.fields}
    used = set(col.field_names)
    for c in cols:
        if c not in by_source:
            key = field_key(c, used)
            by_source[c] = key
            col.fields.append({"name": key, "label": c, "type": infer_type(c, [r.get(c) for r in rows[:200]], types.get(c, "")),
                               "source": c})
    col.records.all().delete()
    Record.objects.bulk_create([Record(collection=col, position=i, data={by_source[k]: v for k, v in r.items() if k in by_source})
                                for i, r in enumerate(rows)], batch_size=500)
    col.last_synced = timezone.now()
    col.save()
    invalidate(col)
    return len(rows)


def invalidate(col):
    with _live_lock:
        _live_cache.pop(col.id, None)


def rows_for(col):
    """All rows of a collection as dicts keyed by field name."""
    if col.mode == Collection.LIVE and col.connection_id:
        now = time.time()
        with _live_lock:
            hit = _live_cache.get(col.id)
        if hit and now - hit[0] < LIVE_TTL:
            return hit[1]
        cfg = col.connection.as_config(col.source_database)
        _, rows = fetch_table(cfg, col.source_database, col.source_table, col.live_order, col.live_desc, col.live_limit)
        by_source = {f.get("source", f["name"]): f["name"] for f in col.fields}
        out = [{by_source.get(k, field_key(k)): v for k, v in r.items()} for r in rows]
        with _live_lock:
            _live_cache[col.id] = (now, out)
        return out
    return [r.data for r in col.records.all()]


# --- CSV / .sql import ----------------------------------------------------------------------------

def parse_csv(data):
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader, None)
    if not header:
        raise RuntimeError("ไฟล์ CSV ว่าง")
    header = [h.strip() or f"col{i + 1}" for i, h in enumerate(header)]
    rows = []
    for line in reader:
        if not any(c.strip() for c in line):
            continue
        rows.append({h: (line[i].strip() if i < len(line) else "") for i, h in enumerate(header)})
        if len(rows) >= MAX_IMPORT_ROWS:
            break
    return header, rows


CREATE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?([\w\u0E00-\u0E7F$-]+)[`\"]?\s*\(", re.I)
INSERT_RE = re.compile(r"INSERT\s+(?:IGNORE\s+)?INTO\s+[`\"]?([\w฀-๿$-]+)[`\"]?\s*(\(([^)]*)\))?\s*VALUES\s*", re.I)
COLDEF_RE = re.compile(r"^\s*[`\"]([^`\"]+)[`\"]\s+([a-zA-Z]+(?:\([^)]*\))?(?:\s+unsigned)?)", re.I)


def _sql_values(text, pos):
    """Parse '(..),(..);' starting at pos → (rows, end_pos). Handles quotes, escapes, NULL, numbers."""
    rows, n = [], len(text)
    while pos < n:
        while pos < n and text[pos] in " \t\r\n,":
            pos += 1
        if pos >= n or text[pos] == ";":
            return rows, pos + 1
        if text[pos] != "(":
            return rows, pos
        pos += 1
        row, cur, in_str, quote, buf_is_str = [], [], False, "", False
        while pos < n:
            ch = text[pos]
            if in_str:
                if ch == "\\" and pos + 1 < n:
                    nxt = text[pos + 1]
                    cur.append({"n": "\n", "r": "\r", "t": "\t", "0": "\0", "Z": "\x1a"}.get(nxt, nxt))
                    pos += 2
                    continue
                if ch == quote:
                    if pos + 1 < n and text[pos + 1] == quote:  # '' inside a string
                        cur.append(quote)
                        pos += 2
                        continue
                    in_str = False
                else:
                    cur.append(ch)
                pos += 1
                continue
            if ch in "'\"":
                if not "".join(cur).strip():
                    cur = []  # drop the space between "," and the opening quote
                in_str, quote, buf_is_str = True, ch, True
            elif ch == ",":
                row.append(_sql_value("".join(cur), buf_is_str))
                cur, buf_is_str = [], False
            elif ch == ")":
                row.append(_sql_value("".join(cur), buf_is_str))
                pos += 1
                break
            else:
                cur.append(ch)
            pos += 1
        rows.append(row)
    return rows, pos


def _sql_value(raw, is_str):
    if is_str:
        return raw
    v = raw.strip()
    if v.upper() == "NULL" or v == "":
        return ""
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d*\.\d+(e[+-]?\d+)?", v, re.I):
        f = float(v)
        return int(f) if f.is_integer() else f
    return v


def parse_sql_dump(text):
    """phpMyAdmin/mysqldump output → {table: {"columns": [...], "types": {...}, "rows": [dict, ...]}}."""
    tables = {}
    for m in CREATE_RE.finditer(text):
        depth, i, in_q = 1, m.end(), ""
        while i < len(text) and depth:  # find the matching ")" (column types like decimal(10,2) nest)
            ch = text[i]
            if in_q:
                if ch == in_q:
                    in_q = ""
            elif ch in "'\"`":
                in_q = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        cols, types = [], {}
        for line in text[m.end():i - 1].split("\n"):
            cm = COLDEF_RE.match(line)
            if cm and not re.match(r"^\s*(PRIMARY|UNIQUE|KEY|INDEX|CONSTRAINT|FOREIGN)\b", line, re.I):
                cols.append(cm.group(1))
                types[cm.group(1)] = cm.group(2)
        tables[m.group(1)] = {"columns": cols, "types": types, "rows": []}
    for m in INSERT_RE.finditer(text):
        name = m.group(1)
        t = tables.setdefault(name, {"columns": [], "types": {}, "rows": []})
        cols = [c.strip().strip("`\"") for c in m.group(3).split(",")] if m.group(3) else t["columns"]
        values, _ = _sql_values(text, m.end())
        if not t["columns"]:
            t["columns"] = cols or [f"col{i + 1}" for i in range(len(values[0]) if values else 0)]
        for row in values:
            if len(t["rows"]) >= MAX_IMPORT_ROWS:
                break
            t["rows"].append({c: plain(v) for c, v in zip(cols or t["columns"], row)})
    return tables


# --- rendering ------------------------------------------------------------------------------------

def _apply_query(rows, attrs):
    flt = ATTR("data-bw-filter").search(attrs)
    if flt and flt.group(1).strip():
        for cond in flt.group(1).split(";"):
            m = re.match(r"\s*([^!=~<>\s]+)\s*(!=|=|~|>=|<=|>|<)\s*(.*?)\s*$", cond)
            if not m:
                continue
            f, op, val = m.groups()

            def ok(r, f=f, op=op, val=val):
                v = r.get(f, "")
                if op in (">", "<", ">=", "<="):
                    try:
                        a, b = float(v), float(val)
                    except (TypeError, ValueError):
                        return False
                    return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]
                sv = str(v).lower()
                if op == "~":
                    return val.lower() in sv
                return (sv == val.lower()) == (op == "=")

            rows = [r for r in rows if ok(r)]
    sort = ATTR("data-bw-sort").search(attrs)
    if sort and sort.group(1).strip():
        key = sort.group(1).strip()
        om = ATTR("data-bw-order").search(attrs)
        desc = bool(om) and om.group(1).strip().lower() == "desc"

        def k(r):
            v = r.get(key, "")
            try:
                return (0, float(v), "")
            except (TypeError, ValueError):
                return (1, 0, str(v).lower())

        rows = sorted(rows, key=k, reverse=desc)
    off = ATTR("data-bw-offset").search(attrs)
    if off and off.group(1).strip().isdigit():
        rows = rows[int(off.group(1)):]
    lim = ATTR("data-bw-limit").search(attrs)
    if lim and lim.group(1).strip().isdigit() and int(lim.group(1)) > 0:
        rows = rows[:int(lim.group(1))]
    return rows


def _fill(template, resolve):
    def sub(m):
        raw, key = (m.group(1), False) if m.group(1) is not None else (m.group(2), True)
        value = resolve(raw)
        if value is None:
            return m.group(0)
        return htmllib.escape(str(value)) if key else str(value)

    return PLACEHOLDER_RE.sub(sub, template)


def _match_end(html, tag, start):
    """Index just past the closing tag that matches the element opened right before ``start``."""
    depth = 1
    for m in re.finditer(rf"<(/?){tag}\b[^>]*?(/?)>", html[start:], re.I):
        if m.group(2):
            continue
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return start + m.start(), start + m.end()
    return len(html), len(html)


class Binder:
    def __init__(self, site, page=None):
        self.site, self.page = site, page
        self._cols = None
        self._rows = {}
        self.errors = []

    def collections(self):
        if self._cols is None:
            self._cols = {c.slug: c for c in self.site.collections.select_related("connection")}
        return self._cols

    def rows(self, slug):
        if slug not in self._rows:
            col = self.collections().get(slug)
            if not col:
                self._rows[slug] = None
            else:
                try:
                    self._rows[slug] = rows_for(col)
                except Exception as e:  # a live source being down must not break the page
                    self.errors.append(f"{slug}: {e}")
                    self._rows[slug] = []
        return self._rows[slug]

    def global_value(self, key):
        head, _, rest = key.partition(".")
        if head == "site" and rest in ("name", "description", "slug"):
            return getattr(self.site, rest)
        if head == "page" and self.page is not None and rest in ("title", "slug", "seo_description"):
            return getattr(self.page, rest)
        if head == "now":
            n = timezone.localtime()
            return {"year": n.year, "date": n.strftime("%d/%m/%Y")}.get(rest)
        if rest and head in self.collections():
            rows = self.rows(head) or []
            if rest == "count":
                return len(rows)
            return rows[0].get(rest, "") if rows else ""
        return None

    def render(self, html):
        if "{{" not in html and "data-bw-repeat" not in html:
            return html
        html = self._repeats(html)
        return _fill(html, self.global_value)

    def _repeats(self, html):
        out, pos = [], 0
        while True:
            m = REPEAT_RE.search(html, pos)
            while m and not ATTR("data-bw-repeat").search(m.group(2)):
                m = REPEAT_RE.search(html, m.end())
            if not m:
                out.append(html[pos:])
                return "".join(out)
            tag, slug = m.group(1), ATTR("data-bw-repeat").search(m.group(2)).group(1).strip()
            inner_start = m.end()
            close_start, close_end = _match_end(html, tag, inner_start)
            template = html[inner_start:close_start]
            rows = self.rows(slug)
            out.append(html[pos:inner_start])
            if rows is None:  # unknown collection: leave the template visible
                out.append(template)
            else:
                rows = _apply_query(rows, m.group(2))
                if not rows:
                    empty = ATTR("data-bw-empty").search(m.group(2))
                    out.append(f'<p class="bw-empty">{htmllib.escape(empty.group(1)) if empty else ""}</p>' if empty else "")
                for i, row in enumerate(rows, 1):
                    item = _fill(template, lambda k, row=row, i=i: i if k == "#" else (row.get(k) if k in row else None))
                    out.append(self._repeats(item))  # nested repeats of other collections
            out.append(html[close_start:close_end])
            pos = close_end


def render_html(html, site, page=None):
    return Binder(site, page).render(html)
