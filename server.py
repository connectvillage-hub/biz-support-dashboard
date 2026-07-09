# -*- coding: utf-8 -*-
"""로컬 대시보드 앱 서버.

index.html 을 제공하고, '사이트 추가' 버튼이 호출하는 API를 처리한다.
브라우저(정적 파일)에서는 크롤링을 못 하므로, 이 서버가 파이썬 크롤러를 대신 실행한다.

실행:  python server.py   (또는 앱_시작.bat 더블클릭)
"""
import json
import sys
import threading
import urllib.parse
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import scraper

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

PORT = 8765
LOCK = threading.Lock()  # 크롤/저장이 겹치지 않게


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=scraper.BASE_DIR, **k)

    def log_message(self, *a):  # 콘솔 조용히
        pass

    def end_headers(self):
        # data.js 등 정적 파일이 캐시되어 추가 직후 새로고침에서 옛 데이터가 보이는 것 방지
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:  # noqa: BLE001
            return {}

    def _query(self):
        q = urllib.parse.urlparse(self.path).query
        return {k: v[0] for k, v in urllib.parse.parse_qs(q).items()}

    def do_GET(self):
        if self.path.startswith("/api/ping"):
            return self._json({"ok": True})
        if self.path.startswith("/api/sources"):
            return self._json({"ok": True, "sources": scraper.read_custom_sources()})
        if self.path.startswith("/api/detail"):
            url = (self._query().get("url") or "").strip()
            try:
                return self._json({"ok": True, **scraper.fetch_detail(url)})
            except Exception as e:  # noqa: BLE001
                return self._json({"ok": False, "error": str(e)[:200]}, 200)
        if self.path.startswith("/api/download"):
            return self._download()
        return super().do_GET()

    def _download(self):
        q = self._query()
        url = (q.get("url") or "").strip()
        want_name = q.get("name") or ""
        try:
            got_name, content, ctype = scraper.fetch_bytes(url, referer=q.get("ref"))
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": str(e)[:200]}, 200)
        fname = want_name or got_name or (url.split("/")[-1].split("?")[0]) or "download"
        fname = fname.replace("\r", "").replace("\n", "").replace('"', "").strip() or "download"
        quoted = urllib.parse.quote(fname)
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quoted}")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        data = self._body()
        try:
            if self.path.startswith("/api/test"):
                items = scraper.test_crawl((data.get("url") or "").strip())
                return self._json({"ok": True, "count": len(items),
                                   "items": [{"title": i["title"], "date": i["date"],
                                              "url": i["url"]} for i in items[:8]]})
            if self.path.startswith("/api/add"):
                with LOCK:
                    res = scraper.add_custom_source(data)
                    scraper.run(only=res["id"])          # 새 소스만 즉시 수집→data.js 갱신
                return self._json({"ok": True, **res})
            if self.path.startswith("/api/remove"):
                with LOCK:
                    scraper.remove_custom_source((data.get("id") or "").strip())
                    scraper.run(only="__regen__")        # 목록 재생성(삭제분 제거)
                return self._json({"ok": True})
            if self.path.startswith("/api/refresh"):
                with LOCK:
                    scraper.run()
                return self._json({"ok": True})
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": str(e)}, 200)
        return self._json({"ok": False, "error": "unknown endpoint"}, 404)


APP_VERSION = "2026-07-09.7"


def main():
    url = f"http://localhost:{PORT}/index.html"
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        print("=" * 52)
        print(f" [오류] 포트 {PORT} 를 이미 다른 프로그램이 쓰고 있습니다.")
        print(" 이전에 열어둔 검은 창을 모두 닫은 뒤 다시 실행하거나,")
        print(" 컴퓨터를 재부팅한 뒤 앱_시작.bat 을 다시 눌러주세요.")
        print(f"   ({e})")
        print("=" * 52)
        input(" 엔터를 누르면 닫힙니다…")
        return
    print("=" * 52)
    print(f" 지원사업 대시보드 앱 실행됨 (build {APP_VERSION})")
    print(f"  브라우저 주소: {url}")
    print(" 이 창을 닫으면 사이트 추가/상세보기 기능이 꺼집니다.")
    print("=" * 52)
    try:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    except Exception:  # noqa: BLE001
        pass
    httpd.serve_forever()


if __name__ == "__main__":
    main()
