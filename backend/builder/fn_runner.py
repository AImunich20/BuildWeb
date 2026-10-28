"""Runs one server function in its own Python process (started by logic.call_function with ``python -I``).

stdin: {"code", "request", "api_base", "secrets"} · stdout (last line): {"ok", "status", "body", "logs"}.
The function talks to the site's data through the site's own REST API on 127.0.0.1 with owner rights, so the
same validation and webhooks apply as for any other client.
"""
import contextlib
import io
import json
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request


class BwError(Exception):
    def __init__(self, status, body):
        msg = body.get("error", {}).get("message") if isinstance(body, dict) else str(body)
        super().__init__(f"{status}: {msg}")
        self.status, self.body = status, body


class Bw:
    def __init__(self, api_base, secrets):
        self._base, self._secrets = api_base, secrets

    def _call(self, method, path, body=None, params=None):
        url = self._base + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json", "User-Agent": "BuildWeb-fn"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                text = r.read().decode("utf-8")
                return json.loads(text) if text else None
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            try:
                raise BwError(e.code, json.loads(text))
            except ValueError:
                raise BwError(e.code, text)

    def list(self, collection, **params):
        return self._call("GET", collection, params=params)

    def all(self, collection, **params):
        """Every row (follows the pages)."""
        out, page = [], 1
        while True:
            r = self.list(collection, **{**params, "page": page, "per_page": 200})
            out += r["items"]
            if page >= r["total_pages"]:
                return out
            page += 1

    def get(self, collection, id):
        return self._call("GET", f"{collection}/{id}")

    def create(self, collection, data):
        return self._call("POST", collection, data)

    def update(self, collection, id, data):
        return self._call("PATCH", f"{collection}/{id}", data)

    def delete(self, collection, id):
        return self._call("DELETE", f"{collection}/{id}")

    def secret(self, name, default=""):
        return self._secrets.get(name, default)

    def http(self, method, url, json=None, headers=None, data=None, timeout=20):
        """Call any external API. Returns {"status", "json" (or None), "text"}."""
        import json as _json

        body = _json.dumps(json).encode() if json is not None else (data.encode() if isinstance(data, str) else data)
        h = {"User-Agent": "BuildWeb-fn", **({"Content-Type": "application/json"} if json is not None else {}), **(headers or {})}
        req = urllib.request.Request(url, data=body, method=method.upper(), headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status, text = r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status, text = e.code, e.read().decode("utf-8", "replace")
        try:
            parsed = _json.loads(text)
        except ValueError:
            parsed = None
        return {"status": status, "json": parsed, "text": text}

    def log(self, *args):
        print(*args)


def main():
    job = json.loads(sys.stdin.read())
    logs = io.StringIO()
    result = {"ok": False, "status": 500, "body": None}
    try:
        with contextlib.redirect_stdout(logs):
            scope = {"__name__": "bw_function"}
            exec(compile(job["code"], "function.py", "exec"), scope)
            handler = scope.get("handler")
            if not callable(handler):
                raise RuntimeError("ต้องมีฟังก์ชัน handler(request, bw)")
            out = handler(job["request"], Bw(job["api_base"], job.get("secrets") or {}))
        status, body = (out if isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], int) else (200, out))
        json.dumps(body)  # must be JSON
        result = {"ok": 200 <= status < 400, "status": status, "body": body}
    except BwError as e:
        result = {"ok": False, "status": 502, "body": {"error": {"code": "data_error", "message": str(e)}}}
        logs.write(traceback.format_exc(limit=3))
    except Exception as e:
        result = {"ok": False, "status": 500, "body": {"error": {"code": "function_error", "message": f"{type(e).__name__}: {e}"}}}
        logs.write(traceback.format_exc(limit=5))
    result["logs"] = logs.getvalue()[-8000:]
    sys.stdout.write("\n" + json.dumps(result, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    main()
