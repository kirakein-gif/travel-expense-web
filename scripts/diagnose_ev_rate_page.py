from __future__ import annotations

import re
from html import unescape
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

BASE = "https://www.me.go.kr"
SEARCHES = [
    f"{BASE}/home/web/board/list.do?boardMasterId=1&menuId=286&maxPageItems=20&pagerOffset=0&searchKey=title&searchValue={quote('충전요금')}",
    f"{BASE}/home/web/board/list.do?boardMasterId=39&menuId=290&maxPageItems=20&pagerOffset=0&searchKey=title&searchValue={quote('충전요금')}",
]


def fetch(url: str) -> str:
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    with urlopen(req, timeout=30) as res:
        text = res.read().decode("utf-8", errors="replace")
        print("FETCH", res.status, len(text), url)
        return text


for url in SEARCHES:
    html = fetch(url)
    print("contains 2026 title:", "전기차 공공 충전 요금 체계 개편" in html)
    print("contains charge price:", "충전요금" in html)
    links = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, flags=re.I|re.S)
    for href, label in links:
        label_text = re.sub(r"<[^>]+>", " ", unescape(label))
        label_text = re.sub(r"\s+", " ", label_text).strip()
        if "충전" in label_text and "요금" in label_text:
            print("MATCH_LINK", label_text[:180], urljoin(url, unescape(href)))
