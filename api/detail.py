# -*- coding: utf-8 -*-
"""버셀 서버리스: 공고 상세 본문·첨부 추출. GET /api/detail?url=..."""
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import fetch_detail  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        url = (q.get("url", [""])[0] or "").strip()
        try:
            data = {"ok": True}
            data.update(fetch_detail(url))
        except Exception as e:  # noqa: BLE001
            data = {"ok": False, "error": str(e)[:200]}
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=600")
        self.end_headers()
        self.wfile.write(body)
