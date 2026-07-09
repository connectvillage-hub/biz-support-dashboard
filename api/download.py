# -*- coding: utf-8 -*-
"""버셀 서버리스: 첨부파일 다운로드 프록시. GET /api/download?url=...&name=...&ref=..."""
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import fetch_bytes  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        url = (q.get("url", [""])[0] or "").strip()
        want = q.get("name", [""])[0]
        ref = q.get("ref", [None])[0]
        try:
            got, content, ctype = fetch_bytes(url, referer=ref)
        except Exception as e:  # noqa: BLE001
            body = json.dumps({"ok": False, "error": str(e)[:200]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            return
        fname = (want or got or url.split("/")[-1].split("?")[0] or "download")
        fname = fname.replace("\r", "").replace("\n", "").replace('"', "").strip() or "download"
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Disposition",
                         "attachment; filename*=UTF-8''" + urllib.parse.quote(fname))
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)
