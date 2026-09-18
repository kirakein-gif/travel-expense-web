from __future__ import annotations

import re
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

# Print compact snippets around likely data-loading code and endpoints.
for keyword in [
    "ajax", "fetch(", "XMLHttpRequest", "chargePrice", "ChargePrice",
    "excel", "Excel", "jqGrid", "grid", ".do", "url:"
]:
    print("\n### KEYWORD", keyword)
    hits = [m.start() for m in re.finditer(re.escape(keyword), html, flags=re.I)]
    print("hits:", len(hits))
    for pos in hits[:40]:
        start = max(0, pos - 260)
        end = min(len(html), pos + 500)
        snippet = re.sub(r"\s+", " ", html[start:end])
        print(snippet)

# Extract URL-like .do strings and nearby JS object values.
print("\n### .do literals")
items = sorted(set(re.findall(r'["\']([^"\']+\.do(?:\?[^"\']*)?)["\']', html)))
for item in items:
    print(item)
