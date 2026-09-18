from urllib.request import Request, urlopen

PAGE = "https://ev.or.kr/nportal/evcarInfo/initEvcarChargePriceV2.do"
UAS = {
    "chrome": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36",
    "googlebot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "bingbot": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "curl": "curl/8.5.0",
}

for name, ua in UAS.items():
    req = Request(PAGE, headers={"User-Agent": ua, "Accept-Language": "ko-KR,ko;q=0.9"})
    try:
        with urlopen(req, timeout=30) as res:
            raw = res.read()
            text = raw.decode("utf-8", errors="replace")
            print(name, "status", getattr(res, "status", None), "len", len(text),
                  "ministry", "기후에너지환경부" in text, "price", "325.6" in text,
                  "content-type", res.headers.get("Content-Type"))
            print("prefix", text[:180].replace("\n", " "))
    except Exception as e:
        print(name, "ERROR", repr(e))
