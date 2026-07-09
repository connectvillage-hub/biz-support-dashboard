# -*- coding: utf-8 -*-
"""버셀 서버리스: 서버 존재/기능 확인용. (상세·다운로드만 지원, 사이트추가는 미지원)"""
import json
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"ok": True, "features": {"detail": True, "add": False}}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
