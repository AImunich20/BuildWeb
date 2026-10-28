"""Site data: collections imported from XAMPP MySQL (copied or read live), .sql dumps or CSV, and the
render-time templating that binds them to pages.

In page HTML:
  <div data-bw-repeat="products" data-bw-limit="6" data-bw-sort="price" data-bw-order="desc"
       data-bw-filter="category=coffee"> ...{{name}} {{price}} <img src="{{image}}"> ... </div>
      The element's content is repeated for every row. {{field}} is HTML-escaped, {{{field}}} is raw,
      {{#}} is the row number.
  Anywhere: {{products.count}}, {{products.name}} (first row), {{site.name}}, {{page.title}}, {{now.year}}.
  Filters: {{date|date}} (28 ต.ค. 2569), {{price|number}} (1,250), {{detail|truncate:120}}, {{content|text}}.
  Rows of a collection that has a detail page also get {{_url}} (link to that row's page) and {{_slug}}.
  data-bw-if="field" (or "!field") on any element keeps it only when the field has a value.
  data-bw-search / data-bw-facet="category" / data-bw-paginate="9" on a repeat add a search box, category
  buttons and paging (done in the browser by site.js).
A detail page (Page.collection) is rendered once per row at <page>/<row>.html, where {{field}} is that row
and {{_prev_url}} / {{_next_url}} link to its neighbours.
Placeholders that do not resolve are left untouched, so imported sites using {{ }} for something else keep
working.
"""
import csv
import html as htmllib
import io
import json
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


_pk_cache = {}


def primary_key(col):
    """The primary-key column of a live collection's MySQL table (cached), or None."""
    if not (col.connection_id and col.source_table):
        return None
    k = (col.id, col.source_database, col.source_table)
    if k not in _pk_cache:
        conn = connect(col.connection.as_config(col.source_database), database=col.source_database)
        try:
            with conn.cursor() as c:
                c.execute("SELECT COLUMN_NAME AS c FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
                          "AND COLUMN_KEY='PRI' ORDER BY ORDINAL_POSITION LIMIT 1", (col.source_database, col.source_table))
                r = c.fetchone()
            _pk_cache[k] = r["c"] if r else None
        finally:
            conn.close()
    return _pk_cache[k]


def _live_exec(col, sql, args):
    conn = connect(col.connection.as_config(col.source_database), database=col.source_database)
    try:
        with conn.cursor() as c:
            c.execute(sql, args)
            last = c.lastrowid
        conn.commit()
        return last
    except pymysql.err.MySQLError as e:
        raise RuntimeError(f"MySQL: {e.args[1] if len(e.args) > 1 else e}") from e
    finally:
        conn.close()


def _live_columns(col, values):
    source = {f["name"]: f.get("source", f["name"]) for f in col.fields}
    return {source[k]: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
            for k, v in values.items() if k in source}


def live_insert(col, values, approved=True):
    """INSERT a row into a live collection's table; returns the new id (auto-increment) if any."""
    row = _live_columns(col, values)
    if "approved" in col.field_names:
        row[{f["name"]: f.get("source", f["name"]) for f in col.fields}["approved"]] = 1 if approved else 0
    cols = list(row)
    if not cols:
        raise RuntimeError("ไม่มีข้อมูลที่จะบันทึก")
    sql = (f"INSERT INTO {qname(col.source_table)} ({', '.join(qname(c) for c in cols)}) "
           f"VALUES ({', '.join(['%s'] * len(cols))})")
    return _live_exec(col, sql, [row[c] for c in cols])


def live_update(col, pk_value, values):
    pk = primary_key(col)
    row = {c: v for c, v in _live_columns(col, values).items() if c != pk}
    if not row:
        return
    sql = (f"UPDATE {qname(col.source_table)} SET {', '.join(f'{qname(c)}=%s' for c in row)} "
           f"WHERE {qname(pk)}=%s LIMIT 1")
    _live_exec(col, sql, list(row.values()) + [pk_value])


def live_delete(col, pk_value):
    pk = primary_key(col)
    _live_exec(col, f"DELETE FROM {qname(col.source_table)} WHERE {qname(pk)}=%s LIMIT 1", [pk_value])


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
        if col.opt("forms") and "approved" in col.field_names:  # rows sent from the site wait for approved=1
            out = [r for r in out if str(r.get("approved", "1")).strip().lower() not in ("0", "", "false", "no")]
        with _live_lock:
            _live_cache[col.id] = (now, out)
        return out
    return [{**r.data, "_id": r.id, "_owner": r.owner_id} for r in col.records.filter(approved=True)]


# --- detail pages ---------------------------------------------------------------------------------

SLUG_CHARS_RE = re.compile(r"[^a-z0-9\u0E00-\u0E7F]+")
TITLE_NAMES = ("title", "name", "ชื่อ", "หัวข้อ", "product_name", "productname", "post_title", "subject", "label")


def title_field(fields):
    """The field that names a row: title/name/ชื่อ…, else the first plain text field that is not an id."""
    names = {f["name"].lower(): f["name"] for f in fields}
    for n in TITLE_NAMES:
        if n in names:
            return names[n]
    for f in fields:
        if f.get("type", "text") == "text" and not re.fullmatch(r"(id|slug|_?id|.*_id)", f["name"], re.I):
            return f["name"]
    return fields[0]["name"] if fields else ""


def slug_text(value):
    """A URL-safe name; Thai letters are kept (browsers and static hosts handle them)."""
    return SLUG_CHARS_RE.sub("-", str(value or "").lower()).strip("-")[:80].strip("-")


def detail_rows(col, field=""):
    """[(slug, row)] for every row of ``col``, each row with _slug, _prev_url and _next_url."""
    rows = rows_for(col)
    slugs = row_slugs(col, rows, field)
    return [(s, r) for s, r in zip(slugs, rows)]


def detail_href(page, slug):
    """Link to a row's page, relative to the site root (detail pages use <base href="../">)."""
    from urllib.parse import quote

    return f"{page.slug}/{quote(slug)}.html"


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

def filter_rows(rows, expr, blocked=()):
    """Rows matching "field=value;price>50;name~lat" (=, !=, ~ contains, >, <, >=, <=)."""
    for cond in (expr or "").split(";"):
        m = re.match(r"\s*([^!=~<>\s]+)\s*(!=|=|~|>=|<=|>|<)\s*(.*?)\s*$", cond)
        if not m or m.group(1) in blocked:
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
    return rows


def _apply_query(rows, attrs):
    flt = ATTR("data-bw-filter").search(attrs)
    if flt and flt.group(1).strip():
        rows = filter_rows(rows, flt.group(1))
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


THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(v):
    return re.sub(r"\s+", " ", htmllib.unescape(TAG_RE.sub(" ", str(v or "")))).strip()


def parse_date(v):
    if isinstance(v, (date, datetime)):
        return v
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(v or "").strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def apply_filter(value, name, arg):
    if name == "date":
        d = parse_date(value)
        if not d:
            return value
        if arg == "en":
            return d.strftime("%-d %b %Y") if hasattr(d, "strftime") else value
        return f"{d.day} {THAI_MONTHS[d.month - 1]} {d.year + 543}"
    if name == "number":
        try:
            f = float(str(value).replace(",", ""))
        except ValueError:
            return value
        digits = int(arg) if arg.isdigit() else (0 if f.is_integer() else 2)
        return f"{f:,.{digits}f}"
    if name == "text":
        return strip_tags(value)
    if name == "truncate":
        text, n = strip_tags(value), int(arg) if arg.isdigit() else 120
        return text if len(text) <= n else text[:n].rstrip() + "…"
    if name == "upper":
        return str(value).upper()
    if name == "lower":
        return str(value).lower()
    if name == "default":
        return value if str(value or "").strip() else arg
    return value


def _fill(template, resolve):
    def sub(m):
        raw, key = (m.group(1), False) if m.group(1) is not None else (m.group(2), True)
        name, *filters = raw.split("|")
        value = resolve(name)
        if value is None:
            return m.group(0)
        for f in filters:
            fname, _, arg = f.partition(":")
            value = apply_filter(value, fname, arg)
        return htmllib.escape(str(value)) if key else str(value)

    return PLACEHOLDER_RE.sub(sub, template)


def truthy(v):
    return v not in (None, "", 0, "0", False, "false", "False") and str(v).strip() != ""


def _conditions(html, resolve):
    """Remove elements whose data-bw-if field (resolved by ``resolve``) is empty; "!field" inverts.
    Fields that do not resolve here (e.g. inside a nested repeat) are left for a later pass."""
    if "data-bw-if" not in html:
        return html
    out, pos = [], 0
    while True:
        m = REPEAT_RE.search(html, pos)
        while m and not ATTR("data-bw-if").search(m.group(2)):
            m = REPEAT_RE.search(html, m.end())
        if not m:
            out.append(html[pos:])
            return "".join(out)
        cond = ATTR("data-bw-if").search(m.group(2)).group(1).strip()
        neg = cond.startswith("!")
        value = resolve(cond.lstrip("!").strip())
        if value is None:  # unknown here: keep as is
            out.append(html[pos:m.end()])
            pos = m.end()
            continue
        if truthy(value) != neg:  # kept: continue inside it (nested conditions)
            out.append(html[pos:m.end()])
            pos = m.end()
        else:
            out.append(html[pos:m.start()])
            pos = _match_end(html, m.group(1), m.end())[1]


ROOT_TAG_RE = re.compile(r"\s*<([a-zA-Z][\w-]*)")


def _mark_item(item, row, facet):
    """Tag one rendered row for the browser-side search/category/paging of site.js."""
    text = strip_tags(" ".join(str(v) for k, v in row.items() if not str(k).startswith("_")))[:600].lower()
    attrs = f' data-bw-item data-bw-s="{htmllib.escape(text)}"'
    if facet:
        attrs += f' data-bw-c="{htmllib.escape(str(row.get(facet, "")).strip())}"'
    m = ROOT_TAG_RE.match(item)
    if m:
        open_m = REPEAT_RE.match(item, m.start(1) - 1)
        end = _match_end(item, m.group(1), open_m.end())[1] if open_m else len(item)
        if not item[end:].strip():  # a single root element: put the attributes on it
            return item[:m.end()] + attrs + item[m.end():]
    return f'<div style="display:contents"{attrs}>{item}</div>'


VOID_TAGS = {"img", "input", "br", "hr", "source", "meta", "link", "area", "col", "embed", "track", "wbr", "param"}


def _match_end(html, tag, start):
    """Index just past the closing tag that matches the element opened right before ``start``."""
    if tag.lower() in VOID_TAGS:  # no closing tag: the element ends with its start tag
        return start, start
    depth = 1
    for m in re.finditer(rf"<(/?){tag}\b[^>]*?(/?)>", html[start:], re.I):
        if m.group(2):
            continue
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return start + m.start(), start + m.end()
    return len(html), len(html)


class Binder:
    """Fills one page: repeats, {{placeholders}} and data-bw-if. ``row`` is the row a detail page shows."""

    def __init__(self, site, page=None, row=None, include_drafts=False, user=None):
        self.site, self.page, self.row, self.include_drafts, self.user = site, page, row, include_drafts, user
        self._cols = None
        self._rows = {}
        self._detail = None
        self._by_id = {}
        self.errors = []

    def collections(self):
        if self._cols is None:
            self._cols = {c.slug: c for c in self.site.collections.select_related("connection")}
        return self._cols

    def detail_pages(self):
        """{collection_id: Page} — the page each collection's rows link to through {{_url}}."""
        if self._detail is None:
            from .models import Page

            qs = self.site.pages.filter(collection__isnull=False)
            if not self.include_drafts:
                qs = qs.filter(status=Page.PUBLISHED)
            self._detail = {}
            for p in qs:
                self._detail.setdefault(p.collection_id, p)
        return self._detail

    def rows(self, slug):
        if slug not in self._rows:
            col = self.collections().get(slug)
            if not col:
                self._rows[slug] = None
            else:
                try:
                    rows = rows_for(col)
                    dp = self.detail_pages().get(col.id)
                    if dp:
                        rows = [{**r, "_slug": s, "_url": detail_href(dp, s)}
                                for s, r in zip(row_slugs(col, rows, dp.detail_field), rows)]
                    self._rows[slug] = rows
                except Exception as e:  # a live source being down must not break the page
                    self.errors.append(f"{slug}: {e}")
                    self._rows[slug] = []
        return self._rows[slug]

    def related(self, col, row, key):
        """{{author.name}}: a field of the row(s) a relation field points to."""
        head, _, rest = key.partition(".")
        f = next((x for x in (col.fields if col else []) if x["name"] == head and x.get("type") == "relation"), None)
        if not f or not rest:
            return None
        target = self.collections().get(f.get("relation"))
        if not target or target.mode != target.COPY:
            return None
        if target.slug not in self._by_id:
            self._by_id[target.slug] = {r.id: r.data for r in target.records.filter(approved=True)}
        by_id = self._by_id[target.slug]
        v = row.get(head)
        ids = v if isinstance(v, list) else [v]
        return ", ".join(str(by_id[i].get(rest, "")) for i in ids if i in by_id)

    def global_value(self, key):
        if self.row is not None and key in self.row:
            return self.row[key]
        if self.row is not None and self.page is not None and self.page.collection_id and key in self.page.collection.field_names:
            return ""
        if self.row is not None and "." in key and self.page is not None and self.page.collection_id:
            v = self.related(self.page.collection, self.row, key)
            if v is not None:
                return v
        head, _, rest = key.partition(".")
        if head == "user":  # the signed-in member ("" when nobody, so data-bw-if="user" hides)
            if self.user is None:
                return "" if rest in ("", "name", "email", "role", "id") or rest.startswith("profile.") else None
            if not rest:
                return self.user.email
            if rest.startswith("profile."):
                return (self.user.profile or {}).get(rest[8:], "")
            return {"name": self.user.name or self.user.email.split("@")[0], "email": self.user.email,
                    "role": self.user.role, "id": self.user.id}.get(rest)
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
        if "{{" not in html and "data-bw-repeat" not in html and "data-bw-if" not in html:
            return html
        html = self._repeats(html)
        html = _conditions(html, self.global_value)
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
            tag, attrs = m.group(1), m.group(2)
            slug = ATTR("data-bw-repeat").search(attrs).group(1).strip()
            inner_start = m.end()
            close_start, close_end = _match_end(html, tag, inner_start)
            template = html[inner_start:close_start]
            rows = self.rows(slug)
            out.append(html[pos:inner_start])
            if rows is None:  # unknown collection: leave the template visible
                out.append(template)
            else:
                rows = _apply_query(rows, attrs)
                if re.search(r"(?:^|\s)data-bw-mine(?:\s|=|$)", attrs):  # only the signed-in member's rows
                    rows = [r for r in rows if self.user is not None and r.get("_owner") == self.user.id]
                interactive = any(ATTR(a).search(attrs) or re.search(rf"(?:^|\s){a}(?:\s|=|$)", attrs)
                                  for a in ("data-bw-search", "data-bw-facet", "data-bw-paginate"))
                facet_m = ATTR("data-bw-facet").search(attrs)
                facet = facet_m.group(1).strip() if facet_m else ""
                if not rows:
                    empty = ATTR("data-bw-empty").search(attrs)
                    out.append(f'<p class="bw-empty">{htmllib.escape(empty.group(1)) if empty else ""}</p>' if empty else "")
                col = self.collections().get(slug)
                for i, row in enumerate(rows, 1):
                    def resolve(k, row=row, i=i):
                        if k == "#":
                            return i
                        if k in row:
                            return row.get(k)
                        if col is not None and k in col.field_names:
                            return ""  # a field of the collection that this row leaves empty
                        return self.related(col, row, k) if "." in k else None

                    item = _fill(_conditions(template, resolve), resolve)
                    item = self._repeats(item)  # nested repeats of other collections
                    out.append(_mark_item(item, row, facet) if interactive else item)
            out.append(html[close_start:close_end])
            pos = close_end


def row_slugs(col, rows, field=""):
    """Unique URL names for ``rows`` of ``col``: from ``field``, a "slug" field, or the title field."""
    names = col.field_names
    field = field if field in names else ("slug" if "slug" in names else title_field(col.fields))
    out, used = [], set()
    for i, row in enumerate(rows):
        base = slug_text(row.get(field)) or (str(row["id"]) if str(row.get("id", "")).isdigit() else f"item-{i + 1}")
        slug, n = base, 2
        while slug in used:
            slug, n = f"{base}-{n}", n + 1
        used.add(slug)
        out.append(slug)
    return out


def render_html(html, site, page=None, row=None, include_drafts=False, user=None):
    return Binder(site, page, row, include_drafts, user).render(html)
