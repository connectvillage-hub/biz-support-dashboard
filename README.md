# 지원사업 통합 대시보드

정부지원사업 / R&D / 투자프로그램 공고를 매일 자동 수집해서 한 화면에서 보는 대시보드.

## 사용법 (로컬)

| 하고 싶은 것 | 방법 |
|---|---|
| 공고 보기 | `index.html` 더블클릭 |
| 지금 바로 새 공고 수집 | `업데이트.bat` 더블클릭 |
| 2시간마다 자동 수집 켜기 | `자동실행등록.bat` 더블클릭 (1회만) |

- 공고를 클릭하면 원문이 새 탭으로 열리고 **읽음(회색)** 처리됩니다.
- 미확인 공고가 항상 위로, 그다음 최신순으로 정렬됩니다.
- 지역(부산/전국)·유형(사업화/투자/네트워킹/입주기업/특허·지재권/홍보·마케팅) 필터 제공.
- 읽음 상태는 브라우저에 저장되므로 PC와 폰은 각각 따로 관리됩니다.

## 구조

```
scraper.py   ← 소스별 수집 + 분류 (requests + BeautifulSoup)
data.json    ← 누적 저장소 (최근 120일)
data.js      ← 대시보드가 읽는 데이터
index.html   ← 대시보드 (단일 파일)
.github/workflows/daily.yml ← GitHub Actions 2시간마다 자동 수집
```

## GitHub Pages

이 저장소를 GitHub에 올리면 Actions가 매일 새벽 자동 수집하고,
Pages 주소로 폰에서도 접속할 수 있습니다.

## 소스 추가 (코드 수정 없이)

`custom_sources.json` 파일의 `sources` 목록에 항목을 넣고 저장한 뒤 `업데이트.bat`을 실행하면 됩니다.

**① 바로가기 링크만 추가** (가장 쉬움 — 자동수집은 안 하고 대시보드 하단에 링크 카드로 노출):

```json
{
  "enabled": true,
  "name": "부산창조경제혁신센터",
  "url": "https://ccei.creativekorea.or.kr/busan",
  "region": "부산",
  "mode": "link"
}
```

**② 자동수집 추가** (게시판을 긁어와 공고 카드로 표시). 대상 사이트의 목록 페이지 구조에 맞는 CSS 셀렉터가 필요합니다:

```json
{
  "enabled": true,
  "name": "○○진흥원",
  "region": "부산",
  "mode": "board",
  "list_url": "https://사이트/board/list",
  "base_url": "https://사이트",
  "item_selector": "table tbody tr",
  "title_selector": "td.title a",
  "date_selector": "td.date",
  "link_selector": "td.title a"
}
```

- `item_selector`: 공고 한 줄(행)을 감싸는 요소
- `title_selector` / `link_selector`: 그 안에서 제목/링크(`<a>`)를 가리키는 선택자
- `date_selector`: 등록일 요소 (없으면 행 전체에서 날짜를 자동 추출)
- `base_url`: 링크가 `/board/...`처럼 상대경로일 때 앞에 붙일 주소
- 지역은 `부산` / `전국` / `기타`, 유형은 제목에서 자동 분류됩니다.

> 셀렉터를 직접 찾기 어려우면, 추가하고 싶은 **사이트 주소만 알려주면** 자동수집 설정을 만들어 드립니다.
> `mode`가 `board`인데 수집이 0건이면 셀렉터가 맞지 않는 것이니 `link` 모드로 두거나 문의하세요.
> `enabled`를 `false`로 두면 그 항목은 무시됩니다. 항목을 지우면 해당 소스의 공고도 다음 수집 때 자동 제거됩니다.
