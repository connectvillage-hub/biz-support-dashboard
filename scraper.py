# -*- coding: utf-8 -*-
"""지원사업/투자프로그램 공고 수집기.

각 소스에서 공고 목록을 수집해 data.json(누적 저장소)과 data.js(대시보드용)를 갱신한다.
사용법: python scraper.py [--only 소스id]
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import ssl
import sys
import urllib.parse

import requests
import urllib3
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_JSON = os.path.join(BASE_DIR, "data.json")
DATA_JS = os.path.join(BASE_DIR, "data.js")

KST = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(KST).date()
KEEP_DAYS = 120          # 이 기간 지난 공고는 저장소에서 제거
REQUEST_TIMEOUT = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}


class LegacySSLAdapter(HTTPAdapter):
    """구형 TLS(낮은 보안 레벨·레거시 재협상)만 지원하는 공공기관 서버용."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def fetch(url, encoding=None, verify=True, **kwargs):
    """GET 요청.

    - SSL 오류 → 레거시 TLS 설정으로 1회 재시도 (구형 공공기관 서버)
    - GitHub Actions에서 접속 차단(타임아웃) → 공개 프록시로 1회 우회
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=verify, **kwargs)
    except requests.exceptions.SSLError:
        s = requests.Session()
        s.mount("https://", LegacySSLAdapter())
        r = s.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False, **kwargs)
    except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError):
        if not os.environ.get("GITHUB_ACTIONS"):
            raise
        proxied = "https://api.allorigins.win/raw?url=" + urllib.parse.quote(url, safe="")
        r = requests.get(proxied, headers=HEADERS, timeout=60)
    r.raise_for_status()
    if encoding:
        r.encoding = encoding
    elif not r.encoding or r.encoding.lower() in ("iso-8859-1",):
        r.encoding = r.apparent_encoding
    return r


def soup_of(url, encoding=None, **kwargs):
    return BeautifulSoup(fetch(url, encoding=encoding, **kwargs).text, "html.parser")


# ---------------------------------------------------------------------------
# 날짜 파싱
# ---------------------------------------------------------------------------
DATE_RE = re.compile(r"(20\d{2})[.\-/년\s]*(\d{1,2})[.\-/월\s]*(\d{1,2})")


def parse_date(text):
    """문자열에서 첫 번째 날짜(YYYY-MM-DD)를 뽑는다. 실패 시 None."""
    if not text:
        return None
    m = DATE_RE.search(str(text))
    if not m:
        return None
    try:
        d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d.isoformat()
    except ValueError:
        return None


def parse_deadline(text):
    """'2026-07-01 ~ 2026-07-20' 같은 기간 문자열에서 마감일을 뽑는다."""
    if not text:
        return None
    dates = DATE_RE.findall(str(text))
    if not dates:
        return None
    y, m, d = dates[-1]
    try:
        return datetime.date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 분류 (지역 / 유형)
# ---------------------------------------------------------------------------
CATEGORY_KEYWORDS = [
    ("투자", ["투자", "IR", "데모데이", "배치", "액셀러레이", "엑셀러레이", "펀드", "펀딩", "시드", "엔젤", "TIPS", "팁스", "VC"]),
    ("R&D", ["R&D", "RND", "기술개발", "연구개발", "기술혁신", "실증", "테스트베드", "기술사업화"]),
    ("입주기업", ["입주", "보육", "인큐베이", "사무공간", "창업공간", "오피스 지원"]),
    ("특허·지재권", ["특허", "지식재산", "지재권", "IP나래", "IP ", "상표", "디자인권", "기술보호"]),
    ("홍보·마케팅", ["홍보", "마케팅", "판로", "전시회", "박람회", "수출", "바이어", "쇼핑몰", "라이브커머스", "브랜딩", "광고"]),
    ("네트워킹", ["네트워킹", "밋업", "포럼", "세미나", "컨퍼런스", "교류회", "설명회", "간담회", "워크숍", "경진대회 시상"]),
    ("사업화", ["사업화", "창업지원", "예비창업", "초기창업", "창업도약", "재도전", "바우처", "컨설팅", "멘토링", "육성", "지원사업", "모집공고", "아이디어", "경진대회", "오디션", "스케일업", "공모", "창업", "참여기업", "참가기업"]),
]


def classify(title):
    cats = []
    t = title.upper()
    for cat, kws in CATEGORY_KEYWORDS:
        for kw in kws:
            if kw.upper() in t:
                cats.append(cat)
                break
    return cats or ["기타"]


BUSAN_KW = ["부산", "동남권", "부울경"]


def detect_region(title, default_region):
    for kw in BUSAN_KW:
        if kw in title:
            return "부산"
    if "전국" in title:
        return "전국"
    return default_region


# ---------------------------------------------------------------------------
# 공통 아이템 생성
# ---------------------------------------------------------------------------
def make_item(src, title, url, date=None, deadline=None, region=None):
    title = re.sub(r"\s+", " ", (title or "")).strip()
    if not title or not url:
        return None
    uid = hashlib.sha1(f"{src['id']}|{title}".encode("utf-8")).hexdigest()[:16]
    return {
        "id": uid,
        "source": src["id"],
        "sourceName": src["name"],
        "title": title,
        "url": url,
        "date": date,
        "deadline": deadline,
        "region": detect_region(title, region or src.get("region", "전국")),
        "categories": classify(title),
    }


# ===========================================================================
# 소스별 어댑터  (조사 결과에 따라 채워짐)
# 각 어댑터는 item dict 리스트를 반환한다.
# ===========================================================================
SOURCES = []  # register()로 채움


def register(id, name, region, home, fn=None, link_only=False):
    src = {"id": id, "name": name, "region": region, "home": home,
           "fn": fn, "link_only": link_only}
    SOURCES.append(src)
    return src


# --- 전국 주요 기관 ----------------------------------------------------------

def fetch_kstartup(src):
    soup = soup_of("https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do")
    items = []
    for li in soup.select("#bizPbancList ul li.notice"):
        tit = li.select_one("p.tit")
        a = li.select_one('a[href^="javascript:go_view("]')
        if not tit or not a:
            continue
        m = re.search(r"go_view\((\d+)\)", a.get("href", ""))
        if not m:
            continue
        date = deadline = None
        for span in li.select("span.list"):
            t = span.get_text(" ", strip=True)
            if t.startswith("등록일자"):
                date = parse_date(t)
            elif t.startswith("마감일자"):
                deadline = parse_date(t)
        url = f"https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn={m.group(1)}"
        items.append(make_item(src, tit.get_text(strip=True), url, date, deadline))
    return items


BIZINFO_REGION = {"부산": "부산", "전국": "전국"}


def fetch_bizinfo(src):
    soup = soup_of("https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do")
    items = []
    for tr in soup.select("div.table_Type_1 table tbody tr"):
        a = tr.select_one("td.txt_l a")
        tds = tr.select("td")
        if not a or len(tds) < 7:
            continue
        period = tds[3].get_text(" ", strip=True)
        date = parse_date(tds[6].get_text(strip=True))
        region_txt = tds[4].get_text(strip=True)
        region = "부산" if "부산" in region_txt else ("전국" if "전국" in region_txt else "기타")
        href = a.get("href", "")
        url = href if href.startswith("http") else "https://www.bizinfo.go.kr" + href
        items.append(make_item(src, a.get_text(strip=True), url, date,
                               parse_deadline(period), region=region))
    return items


def fetch_mss(src):
    soup = soup_of("https://www.mss.go.kr/site/smba/ex/bbs/List.do?cbIdx=310")
    items = []
    for tr in soup.select('tbody tr[onclick^="doBbsFView"]'):
        a = tr.select_one("td.subject a")
        if not a:
            continue
        m = re.search(r"doBbsFView\('([^']*)','([^']*)','([^']*)','([^']*)'\)",
                      tr.get("onclick", ""))
        if not m:
            continue
        url = (f"https://www.mss.go.kr/site/smba/ex/bbs/View.do"
               f"?cbIdx={m.group(1)}&bcIdx={m.group(2)}&parentSeq={m.group(4)}")
        items.append(make_item(src, a.get_text(strip=True), url,
                               parse_date(tr.get_text(" "))))
    return items


def fetch_kidp(src):
    list_url = "https://kidp.or.kr/?menuno=1202"
    soup = soup_of(list_url)
    items = []
    for tr in soup.select("form#frontBoardVo table.board01-list tbody tr"):
        a = tr.select_one("td.left a")
        tds = tr.select("td")
        if not a or len(tds) < 3:
            continue
        # 상세는 POST 전용이라 목록 페이지로 링크
        items.append(make_item(src, a.get_text(strip=True), list_url,
                               parse_date(tds[2].get_text(strip=True))))
    return items


YY_DATE_RE = re.compile(r"\b(\d{2})\.(\d{1,2})\.(\d{1,2})")


def parse_date_yy(text):
    """'26.07.08' 형식(연도 2자리)."""
    if not text:
        return None
    m = YY_DATE_RE.search(str(text))
    if not m:
        return None
    try:
        return datetime.date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def fetch_kocca(src):
    soup = soup_of("https://www.kocca.kr/kocca/pims/list.do?menuNo=20410")
    items = []
    for tr in soup.select("table tbody tr"):
        a = tr.select_one('td[data-label="제목"] a')
        if not a or not a.get("href"):
            continue
        date = parse_date_yy(tr.select_one('td[data-label="공고일"]').get_text()
                             if tr.select_one('td[data-label="공고일"]') else None)
        period_el = tr.select_one('td[data-label="접수기간"]')
        deadline = None
        if period_el:
            dates = YY_DATE_RE.findall(period_el.get_text(" ", strip=True))
            if dates:
                y, mo, d = dates[-1]
                try:
                    deadline = datetime.date(2000 + int(y), int(mo), int(d)).isoformat()
                except ValueError:
                    deadline = None
        href = a["href"]
        url = href if href.startswith("http") else "https://www.kocca.kr" + href
        items.append(make_item(src, a.get_text(strip=True), url, date, deadline))
    return items


def fetch_arte(src):
    soup = soup_of("https://arte.or.kr/notice/business/notice/Business_BoardList.do")
    items = []
    for tr in soup.select("table tbody tr"):
        a = tr.select_one('a[href^="javascript:fnView("]')
        tds = tr.select("td")
        if not a or len(tds) < 5:
            continue
        m = re.search(r"(BRD_ID\d+)", a.get("href", ""))
        if not m:
            continue
        url = f"https://arte.or.kr/notice/business/notice/Business_BoardView.do?board_id={m.group(1)}"
        items.append(make_item(src, a.get_text(strip=True), url,
                               parse_date(tds[3].get_text(strip=True)),
                               parse_date(tds[4].get_text(strip=True))))
    return items


def fetch_semas(src):
    soup = soup_of("https://www.semas.or.kr/web/board/webBoardList.kmdc?bCd=1&pNm=BOA0101")
    items = []
    for tr in soup.select("table tbody tr"):
        a = tr.select_one("td.left.title a") or tr.select_one("td.title a")
        if not a:
            continue
        m = re.search(r"fncGoDetail\([^\d]*(\d+)", a.get("href", "") + (a.get("onclick") or ""))
        if not m:
            continue
        url = f"https://www.semas.or.kr/web/board/webBoardView.kmdc?bCd=1&b_idx={m.group(1)}&pNm=BOA0101"
        items.append(make_item(src, a.get_text(strip=True), url,
                               parse_date(tr.get_text(" "))))
    return items


def fetch_smtech(src):
    soup = soup_of("https://www.smtech.go.kr/front/ifg/no/notice02_list.do")
    items = []
    for tr in soup.select("table tbody tr"):
        a = tr.select_one('a[href*="notice02_detail.do"]')
        tds = tr.select("td")
        if not a or len(tds) < 6:
            continue
        href = re.sub(r";jsessionid=[^?]*", "", a.get("href", ""))
        url = href if href.startswith("http") else "https://www.smtech.go.kr" + href
        items.append(make_item(src, a.get_text(strip=True), url,
                               parse_date(tds[5].get_text(strip=True)),
                               parse_deadline(tds[4].get_text(" ", strip=True))))
    return items


# --- 부산 지역 -------------------------------------------------------------

def fetch_busanstartup(src):
    r = fetch("https://www.busanstartup.kr/_Api/bizListData?deadline=N&mcode=biz02&pageNo=1")
    data = r.json()
    rows = data.get("list") or (data.get("data") or {}).get("list") or []
    items = []
    for row in rows:
        deadline = row.get("appl_edate")
        if deadline and deadline.startswith("9999"):
            deadline = None
        url = f"https://www.busanstartup.kr/biz_sup/{row.get('busi_code')}?mcode=biz02"
        items.append(make_item(src, row.get("busi_title"), url,
                               parse_date(row.get("regi_date")),
                               parse_date(deadline)))
    return items


def fetch_dcb(src):
    soup = soup_of("https://dcb.or.kr/01_news/?mcode=0401010000")
    items = []
    for tr in soup.select("div.board-text table tbody tr"):
        a = tr.select_one("td.link a")
        if not a or not a.get("href"):
            continue
        d = tr.select_one("td.date")
        href = a["href"]
        url = href if href.startswith("http") else "https://dcb.or.kr" + href
        items.append(make_item(src, a.get_text(strip=True), url,
                               parse_date(d.get_text() if d else None)))
    return items


def fetch_btp(src):
    soup = soup_of("https://www.btp.or.kr/kor/CMS/Board/Board.do?mCode=MN013")
    items = []
    for tr in soup.select("table tbody tr"):
        a = tr.select_one("td.subject a")
        if not a or not a.get("href"):
            continue
        t = a.select_one("span.titleHover")
        title = t.get_text(strip=True) if t else a.get_text(strip=True)
        d = tr.select_one("td.date")
        period = tr.select_one("td.period")
        url = "https://www.btp.or.kr/kor/CMS/Board/Board.do" + a["href"]
        items.append(make_item(src, title, url,
                               parse_date(d.get_text() if d else None),
                               parse_deadline(period.get_text(" ") if period else None)))
    return items


def fetch_bepa(src):
    soup = soup_of("https://www.bepa.kr/kor/view.do?no=1502")
    items = []
    for tr in soup.select("table tbody tr"):
        a = tr.select_one("td.title a")
        if not a or not a.get("href"):
            continue
        d = tr.select_one("td.date")
        href = a["href"]
        url = href if href.startswith("http") else "https://www.bepa.kr" + href
        items.append(make_item(src, a.get_text(strip=True), url,
                               parse_date(d.get_text() if d else None)))
    return items


def fetch_bkic(src):
    soup = soup_of("http://bkic.bepa.kr/bsknow/view.do?no=1477")
    items = []
    for tr in soup.select("table tbody tr"):
        a = tr.select_one("td.l a")
        tds = tr.select("td")
        if not a or not a.get("href") or len(tds) < 4:
            continue
        href = a["href"]
        url = href if href.startswith("http") else "http://bkic.bepa.kr" + href
        items.append(make_item(src, a.get_text(strip=True), url,
                               parse_date(tds[3].get_text(strip=True))))
    return items


# --- 부산 지역 (추가) --------------------------------------------------------

def fetch_bipa(src):
    soup = soup_of("https://bipa.kr/board/business/list")
    items = []
    for a in soup.select('a[href^="/board/business/view?seq="]'):
        tr = a.find_parent("tr")
        date = parse_date(tr.get_text(" ")) if tr else None
        items.append(make_item(src, a.get_text(strip=True),
                               "https://bipa.kr" + a["href"], date))
    return items


def fetch_bistep(src):
    soup = soup_of("https://www.bistep.re.kr/kor/CMS/Board/Board.do?mCode=MN008")
    items = []
    for td in soup.select("td.subject"):
        a = td.select_one("a")
        if not a or not a.get("href"):
            continue
        tr = td.find_parent("tr")
        date_el = tr.select_one("td.date") if tr else None
        items.append(make_item(
            src, a.get_text(strip=True),
            "https://www.bistep.re.kr/kor/CMS/Board/Board.do" + a["href"],
            parse_date(date_el.get_text() if date_el else None)))
    return items


BUSAN_GOSI_FILTER = re.compile(r"모집|공모|창업|지원|육성|바우처")


def fetch_busan_gosi(src):
    items = []
    for page in (1, 2, 3):
        soup = soup_of(f"https://www.busan.go.kr/nbgosi?curPage={page}")
        for a in soup.select('a[href^="/nbgosi/view?sno="]'):
            title = a.get_text(strip=True)
            if not BUSAN_GOSI_FILTER.search(title):
                continue
            tr = a.find_parent("tr")
            date = parse_date(tr.get_text(" ")) if tr else None
            items.append(make_item(src, title,
                                   "https://www.busan.go.kr" + a["href"], date))
    return items


def fetch_bscf(src):
    soup = soup_of("https://www.bscf.or.kr/index.do")
    items, seen = [], set()
    for a in soup.select('a[href*="no=1010"][href*="pbancSn="]'):
        href = a.get("href", "")
        if href in seen:
            continue
        seen.add(href)
        img = a.select_one("img")
        title = (img.get("alt", "").strip() if img else "") or a.get_text(strip=True)
        if not href.startswith("http"):
            href = "https://www.bscf.or.kr" + (href if href.startswith("/") else "/" + href)
        items.append(make_item(src, title, href))
    return items


# --- 액셀러레이터 / 투자 ----------------------------------------------------

def fetch_dcamp(src):
    soup = soup_of("https://dcamp.kr/news/notice")
    items, seen = [], set()
    for a in soup.select('a[href^="/news/notice/"]'):
        href = a.get("href")
        h3 = a.select_one("h3")
        if not h3 or href in seen:
            continue
        seen.add(href)
        p = a.select_one("p")
        items.append(make_item(src, h3.get_text(strip=True),
                               "https://dcamp.kr" + href,
                               parse_date(p.get_text() if p else None)))
    return items


def fetch_sparklabs(src):
    soup = soup_of("https://sparklabs.co.kr/kr/news")
    items = []
    for li in soup.select("li.news-item"):
        a = li.select_one("a.news-subject")
        if not a:
            continue
        d = li.select_one("div.news-date")
        items.append(make_item(src, a.get_text(strip=True), a.get("href", ""),
                               parse_date(d.get_text() if d else None)))
    return items


def fetch_orangeplanet(src):
    r = requests.post("https://www.orangeplanet.or.kr/news/getNewsListJson",
                      json={"p_PageNo": 1, "p_PageSize": 15, "strTag": ""},
                      headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    rows = data.get("newsList") or (data.get("data") or {}).get("newsList") or []
    items = []
    for row in rows:
        link = (row.get("News_ConnectLink") or "").strip()
        if not link:
            link = f"https://orangeplanet.or.kr/news/newsDetail?newsIdx={row.get('News_Idx')}"
        items.append(make_item(src, row.get("News_Title"), link,
                               parse_date(row.get("News_DT"))))
    return items


PRIMER_TITLE_FILTER = re.compile(r"모집|배치|지원|데모데이|클럽")


def fetch_primer(src):
    text = fetch("https://primer.kr/.md").text
    items, seen = [], set()
    for m in re.finditer(r"\[([^\]]+)\]\((https://primer\.kr[^\)\s]*)\)", text):
        title, url = m.group(1).strip(), m.group(2)
        if title in seen or not PRIMER_TITLE_FILTER.search(title):
            continue
        seen.add(title)
        items.append(make_item(src, "프라이머 " + title, url))
    return items


def fetch_yoonmin(src):
    soup = soup_of("https://yoonmin.org/good-starter")
    h1 = soup.select_one("h1")
    if not h1:
        return []
    title = "윤민창의투자재단 " + h1.get_text(strip=True)
    return [make_item(src, title, "https://yoonmin.org/good-starter")]


register("kstartup", "K스타트업", "전국", "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do", fetch_kstartup)
register("bizinfo", "기업마당", "전국", "https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do", fetch_bizinfo)
register("mss", "중소벤처기업부", "전국", "https://www.mss.go.kr/site/smba/ex/bbs/List.do?cbIdx=310", fetch_mss)
register("kidp", "한국디자인진흥원", "전국", "https://kidp.or.kr/?menuno=1202", fetch_kidp)
register("kocca", "한국콘텐츠진흥원", "전국", "https://www.kocca.kr/kocca/pims/list.do?menuNo=20410", fetch_kocca)
register("arte", "한국문화예술교육진흥원", "전국", "https://arte.or.kr/notice/business/notice/Business_BoardList.do", fetch_arte)
register("semas", "소상공인시장진흥공단", "전국", "https://www.semas.or.kr/web/board/webBoardList.kmdc?bCd=1&pNm=BOA0101", fetch_semas)
register("smtech", "중소기업 기술개발(SMTECH)", "전국", "https://www.smtech.go.kr/front/ifg/no/notice02_list.do", fetch_smtech)
register("busanstartup", "부산창업포털", "부산", "https://www.busanstartup.kr/biz_sup?deadline=N&mcode=biz02", fetch_busanstartup)
register("dcb", "부산디자인진흥원", "부산", "https://dcb.or.kr/01_news/?mcode=0401010000", fetch_dcb)
register("btp", "부산테크노파크", "부산", "https://www.btp.or.kr/kor/CMS/Board/Board.do?mCode=MN013", fetch_btp)
register("bepa", "부산경제진흥원", "부산", "https://www.bepa.kr/kor/view.do?no=1502", fetch_bepa)
register("bkic", "부산지식산업센터", "부산", "http://bkic.bepa.kr/bsknow/view.do?no=1477", fetch_bkic)
register("bsia", "부산기술창업투자원", "부산", "https://www.bsia.or.kr/announcements?mcode=news02", link_only=True)
register("bipa", "부산정보산업진흥원", "부산", "https://bipa.kr/board/business/list", fetch_bipa)
register("bistep", "부산산업과학혁신원", "부산", "https://www.bistep.re.kr/kor/CMS/Board/Board.do?mCode=MN008", fetch_bistep)
register("busan_gosi", "부산광역시 고시공고", "부산", "https://www.busan.go.kr/nbgosi", fetch_busan_gosi)
register("bscf", "부산문화재단", "부산", "https://www.bscf.or.kr", fetch_bscf)
register("dcamp", "디캠프(d.camp)", "전국", "https://dcamp.kr/news/notice", fetch_dcamp)
register("sparklabs", "스파크랩", "전국", "https://sparklabs.co.kr/kr/news", fetch_sparklabs)
register("orangeplanet", "오렌지플래닛", "전국", "https://orangeplanet.or.kr/news/newsList", fetch_orangeplanet)
register("primer", "프라이머", "전국", "https://primer.kr", fetch_primer)
register("yoonmin", "윤민창의투자재단", "전국", "https://yoonmin.org/good-starter", fetch_yoonmin)
register("ccei_busan", "부산창조경제혁신센터", "부산", "https://ccei.creativekorea.or.kr/busan/custom/notice_list.do", link_only=True)
register("bluepoint", "블루포인트파트너스", "전국", "https://bluepoint.ac", link_only=True)
register("mashup", "매쉬업벤처스", "전국", "https://www.mashupventures.co", link_only=True)


# ---------------------------------------------------------------------------
# 수집 실행
# ---------------------------------------------------------------------------
def load_store():
    if os.path.exists(DATA_JSON):
        with open(DATA_JSON, encoding="utf-8") as fp:
            return json.load(fp)
    return {"items": {}}


def run(only=None):
    store = load_store()
    known = store.get("items", {})
    source_status = []
    now_iso = datetime.datetime.now(KST).isoformat(timespec="seconds")

    for src in SOURCES:
        if only and src["id"] != only:
            continue
        if src["link_only"]:
            source_status.append({"id": src["id"], "name": src["name"],
                                  "url": src["home"], "status": "link-only", "count": 0})
            continue
        try:
            items = src["fn"](src)
            items = [i for i in items if i]
            for it in items:
                prev = known.get(it["id"])
                it["firstSeen"] = prev["firstSeen"] if prev else TODAY.isoformat()
                if not it["date"]:
                    it["date"] = it["firstSeen"]
                known[it["id"]] = it
            source_status.append({"id": src["id"], "name": src["name"],
                                  "url": src["home"], "status": "ok", "count": len(items)})
            print(f"[OK]   {src['name']}: {len(items)}건")
        except Exception as e:  # noqa: BLE001 - 소스 하나 실패해도 계속
            source_status.append({"id": src["id"], "name": src["name"],
                                  "url": src["home"], "status": "fail", "count": 0,
                                  "error": str(e)[:200]})
            print(f"[FAIL] {src['name']}: {e}")

    # 오래된 공고 제거
    cutoff = (TODAY - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    known = {k: v for k, v in known.items()
             if (v.get("date") or v.get("firstSeen") or "9999") >= cutoff}

    store["items"] = known
    with open(DATA_JSON, "w", encoding="utf-8") as fp:
        json.dump(store, fp, ensure_ascii=False, indent=1)

    out = {
        "generatedAt": now_iso,
        "sources": source_status,
        "items": sorted(known.values(),
                        key=lambda i: (i.get("date") or i.get("firstSeen") or ""),
                        reverse=True),
    }
    with open(DATA_JS, "w", encoding="utf-8") as fp:
        fp.write("window.BIZ_DATA = ")
        json.dump(out, fp, ensure_ascii=False)
        fp.write(";\n")

    ok = sum(1 for s in source_status if s["status"] == "ok")
    fail = sum(1 for s in source_status if s["status"] == "fail")
    print(f"\n완료: 공고 {len(known)}건 / 소스 성공 {ok}, 실패 {fail} → data.js 갱신")
    return fail


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="특정 소스 id만 수집")
    args = ap.parse_args()
    sys.exit(1 if run(only=args.only) and False else 0)
