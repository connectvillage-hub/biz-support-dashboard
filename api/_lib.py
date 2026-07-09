# -*- coding: utf-8 -*-
"""버셀 서버리스 함수용 공유 라이브러리.

공고 상세 페이지의 본문·첨부파일 추출과 파일 다운로드 프록시를 담당한다.
(로컬 scraper.py 의 상세 관련 함수와 동일한 로직 — 서버리스 배포용 자체 완결형)
"""
import re
import ssl
import time
import urllib.parse

import requests
import urllib3
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

REQUEST_TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}


class LegacySSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def fetch(url, verify=True):
    last_exc = None
    legacy = False
    for attempt in range(3):
        try:
            if legacy:
                s = requests.Session()
                s.mount("https://", LegacySSLAdapter())
                r = s.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False)
            else:
                r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=verify)
            break
        except requests.exceptions.SSLError as e:
            last_exc = e
            if not legacy:
                legacy = True
                continue
            time.sleep(1.5 * (attempt + 1))
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError) as e:
            last_exc = e
            time.sleep(1.5 * (attempt + 1))
    else:
        raise last_exc
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() in ("iso-8859-1",):
        r.encoding = r.apparent_encoding
    return r


def fetch_bytes(url, referer=None):
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, verify=True)
    except requests.exceptions.SSLError:
        s = requests.Session()
        s.mount("https://", LegacySSLAdapter())
        r = s.get(url, headers=headers, timeout=REQUEST_TIMEOUT, verify=False)
    r.raise_for_status()
    name = None
    cd = r.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
    if m:
        name = urllib.parse.unquote(m.group(1))
    return name, r.content, r.headers.get("Content-Type", "application/octet-stream")


FILE_EXT_RE = re.compile(r"\.(hwp|hwpx|pdf|docx?|xlsx?|pptx?|zip|txt|cell|show)(?:$|[?&])", re.I)
DOWNLOAD_HINTS = ("download", "filedown", "atchfile", "getfile", "/fms/", "downfile",
                  "cfs_", "fn_egov_downfile", "nttinfo", "streamdocs", "/uploads/")
GENERIC_NAMES = {"다운로드", "파일다운로드", "첨부", "첨부파일", "download", "view",
                 "미리보기", "바로보기", "preview", "다운", "내려받기",
                 "새창내려받기", "새창열림", "새창", "바로가기"}
BLOCK_HOSTS = ("adobe.com", "microsoft.com", "google.com", "whatsapp", "hancom.com",
               "apple.com", "mozilla.org", "naver.com/whale")
CONTENT_SELECTORS = [
    ".view_cont", ".view-cont", ".board_view", ".bbs_view", ".view_con", ".view-content",
    ".cont_view", ".vw_cont", ".bo_v_con", ".board-view", ".view_area", ".view_body",
    ".board_con", ".dbdata", ".se-main-container", "#content .content", "td.content",
    ".table_view", "article .content", ".detail_cont", ".contents_view",
]
SAFE_TAGS = {"p", "br", "b", "strong", "i", "em", "u", "s", "ul", "ol", "li",
             "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption",
             "h1", "h2", "h3", "h4", "h5", "h6", "span", "div", "img", "a", "hr",
             "blockquote", "pre", "figure", "figcaption", "small", "sub", "sup"}
DROP_TAGS = ["script", "style", "noscript", "iframe", "object", "embed", "svg",
             "form", "input", "button", "select", "textarea", "header", "footer", "nav"]


def _abs(base, href):
    try:
        return urllib.parse.urljoin(base, href)
    except Exception:  # noqa: BLE001
        return href


def attachment_abs_url(href, base):
    if not href:
        return None
    low = href.strip().lower()
    if low.startswith(("mailto:", "tel:", "javascript", "#")):
        return None
    is_file = bool(FILE_EXT_RE.search(low))
    is_dl = any(h in low for h in DOWNLOAD_HINTS)
    if not (is_file or is_dl):
        return None
    url = _abs(base, href.strip())
    host = urllib.parse.urlparse(url).netloc
    base_host = urllib.parse.urlparse(base).netloc
    if any(b in (host + low) for b in BLOCK_HOSTS):
        return None
    if is_dl and not is_file and host and host != base_host:
        return None
    return url


def proxy_download_url(file_url, name, ref):
    return "/api/download?" + urllib.parse.urlencode(
        {"url": file_url, "name": (name or "첨부파일")[:150], "ref": ref})


def parse_download_funcs(html_text):
    funcs = {}
    for m in re.finditer(r"function\s+(\w+)\s*\(([^)]*)\)\s*\{(.*?)submit\s*\(\)", html_text, re.S):
        name, sig, body = m.group(1), m.group(2), m.group(3)
        am = re.search(r"""action\s*=\s*['"]([^'"]+)['"]""", body)
        if not am:
            continue
        params = [p.strip() for p in sig.split(",") if p.strip()]
        field_by_param = {}
        for fm in re.finditer(r"\.(\w+)\.value\s*=\s*(\w+)", body):
            field_by_param[fm.group(2)] = fm.group(1)
        fields = [field_by_param.get(p) for p in params]
        if any(fields):
            funcs[name] = {"endpoint": am.group(1), "fields": fields}
    return funcs


def resolve_onclick_download(onclick, base, dl_funcs):
    if not onclick or not dl_funcs:
        return None
    for m in re.finditer(r"(\w+)\s*\(([^)]*)\)", onclick):
        info = dl_funcs.get(m.group(1))
        if not info:
            continue
        raw = m.group(2).strip()
        args = [a.strip().strip("'\"") for a in raw.split(",")] if raw else []
        params = {}
        for i, field in enumerate(info["fields"]):
            if field and i < len(args):
                params[field] = args[i]
        if not params:
            continue
        ep = _abs(base, info["endpoint"])
        return ep + ("&" if "?" in ep else "?") + urllib.parse.urlencode(params)
    return None


def extract_attachments(soup, base, dl_funcs=None):
    base_host = urllib.parse.urlparse(base).netloc
    out, seen = [], set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        low = href.lower()
        if low.startswith(("mailto:", "tel:")):
            continue
        is_file = bool(FILE_EXT_RE.search(low))
        is_dl = any(h in low for h in DOWNLOAD_HINTS)
        if is_file or is_dl:
            url = _abs(base, href)
            host = urllib.parse.urlparse(url).netloc
            if any(b in (host + low) for b in BLOCK_HOSTS):
                continue
            if is_dl and not is_file and host and host != base_host:
                continue
        else:
            url = resolve_onclick_download(a.get("onclick", ""), base, dl_funcs)
            if not url:
                continue
        if url in seen:
            continue
        seen.add(url)
        raw = a.get("title") or a.get_text(" ", strip=True) or ""
        raw = re.sub(r"\s+", " ", raw).strip()
        if not raw or raw.replace(" ", "").lower() in GENERIC_NAMES:
            parent = a.find_parent(["li", "tr", "td", "div", "p", "dd"])
            cand = ""
            if parent:
                m = re.search(r"[^\s/\\<>]+\.(?:hwp|hwpx|pdf|docx?|xlsx?|pptx?|zip|txt)",
                              parent.get_text(" ", strip=True), re.I)
                if m:
                    cand = m.group(0)
            raw = cand or (url.split("/")[-1].split("?")[0] if is_file else "") or "첨부파일"
        name = raw[:150]
        m2 = FILE_EXT_RE.search(low) or FILE_EXT_RE.search(name.lower())
        ext = m2.group(1).lower() if m2 else ""
        out.append({"name": name, "url": url, "ext": ext})
    return out[:20]


def clean_content_html(node, base, dl_funcs=None):
    for t in node.find_all(DROP_TAGS):
        t.decompose()
    for tag in node.find_all(True):
        if tag.name not in SAFE_TAGS:
            tag.unwrap()
            continue
        attrs = {}
        if tag.name == "a":
            href = tag.get("href", "")
            dl = attachment_abs_url(href, base) or resolve_onclick_download(
                tag.get("onclick", ""), base, dl_funcs)
            if dl:
                nm = (tag.get("title") or re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()
                      or dl.split("/")[-1].split("?")[0] or "첨부파일")
                attrs = {"href": proxy_download_url(dl, nm, base),
                         "class": "d-inline-file", "download": nm}
            elif href and not href.lower().startswith(("javascript", "#")):
                attrs = {"href": _abs(base, href), "target": "_blank", "rel": "noopener"}
        elif tag.name == "img":
            src = tag.get("src") or tag.get("data-src") or tag.get("data-original")
            if src:
                attrs = {"src": _abs(base, src), "loading": "lazy"}
        elif tag.name in ("td", "th"):
            for k in ("colspan", "rowspan"):
                if tag.get(k):
                    attrs[k] = tag.get(k)
        tag.attrs = attrs
    return str(node)[:200000]


def pick_content(soup):
    for sel in CONTENT_SELECTORS:
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 40:
            return el
    best, best_score = None, 0
    for el in soup.find_all(["div", "td", "article", "section"]):
        txt = el.get_text(strip=True)
        n = len(txt)
        if n < 60 or n > 60000:
            continue
        links = len(el.find_all("a"))
        score = n - 60 * links
        if score > best_score:
            best, best_score = el, score
    return best


def fetch_detail(url):
    resp = fetch(url)
    dl_funcs = parse_download_funcs(resp.text)
    soup = BeautifulSoup(resp.text, "html.parser")
    for t in soup(DROP_TAGS):
        t.decompose()
    ttl = soup.select_one(".view_title, .bo_v_title, .subject, .board_title")
    title = re.sub(r"\s+", " ", ttl.get_text(" ", strip=True)).strip() if ttl else ""
    attachments = extract_attachments(soup, url, dl_funcs)
    cont = pick_content(soup)
    html = clean_content_html(cont, url, dl_funcs) if cont else ""
    text_len = len(BeautifulSoup(html, "html.parser").get_text(strip=True)) if html else 0
    return {"title": title[:250], "html": html, "text_len": text_len,
            "attachments": attachments, "url": url}
