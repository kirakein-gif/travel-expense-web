from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin
from urllib.request import Request, urlopen

PAGE = "https://ev.or.kr/nportal/evcarInfo/initEvcarChargePriceV2.do"


def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8", errors="replace")


html = fetch(PAGE)
print("HTML length:", len(html))
print("Contains ministry:", "기후에너지환경부" in html)
print("Contains 325.6:", "325.6" in html)

scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, flags=re.I)
print("script count:", len(scripts))
for src in scripts:
    url = urljoin(PAGE, unescape(src))
    print("SCRIPT", url)
    try:
        js = fetch(url)
    except Exception as e:
        print("FETCH_FAIL", type(e).__name__, e)
        continue
    patterns = re.findall(r'["\']([^"\']*(?:charge|Charge|price|Price|excel|Excel)[^"\']*)["\']', js)
    for item in patterns[:80]:
        if ".do" in item or "ajax" in item.lower() or "excel" in item.lower() or "price" in item.lower():
            print("MATCH", item[:500])
