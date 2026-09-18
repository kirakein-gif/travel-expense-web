from __future__ import annotations

import base64
import re
from urllib.parse import urljoin
from urllib.request import Request, urlopen

PAGE = "https://ev.or.kr/nportal/evcarInfo/initEvcarChargePriceV2.do"


def fetch(url: str) -> str:
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    with urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8", errors="replace")


def js_unescape(value: str) -> str:
    def hx(m):
        return chr(int(m.group(1), 16))
    value = re.sub(r"\\x([0-9a-fA-F]{2})", hx, value)
    value = re.sub(r"\\u([0-9a-fA-F]{4})", hx, value)
    value = value.replace(r"\"", '"').replace(r"\\", "\\")
    return value


def parse_alphabets(js: str) -> list[str]:
    m = re.search(r"var In=\[([\s\S]*?)\],zn=", js) or re.search(r"var In=Array\(([\s\S]*?)\),zn=", js)
    if not m:
        raise RuntimeError("In 문자표 배열 없음")
    fragments = [js_unescape(x) for x in re.findall(r'"((?:\\.|[^"\\])*)"', m.group(1))]
    if not fragments:
        raise RuntimeError("문자표 조각 없음")
    alphabets = []
    for i in range(7):
        e = re.search(rf"o{i}:([^,}}]+)", js)
        if not e:
            raise RuntimeError(f"o{i} 없음")
        idx = [int(x) for x in re.findall(r"In\[(\d+)\]", e.group(1))]
        alphabet = "".join(fragments[j] for j in idx)
        if len(alphabet) < 64:
            raise RuntimeError(f"o{i} 문자표 길이 오류 {len(alphabet)}")
        alphabets.append(alphabet)
    return alphabets


def decode_payload(payload: str, alphabets: list[str]) -> str:
    ai = int(payload[0])
    rotation = int(payload[1])
    base = alphabets[ai]
    alphabet = base[rotation:] + base[:rotation]
    encoded = re.sub(r"[^A-Za-z0-9+/=]", "", payload[2:])
    out = bytearray()
    pos = 0
    while pos < len(encoded):
        chars = encoded[pos:pos+4]
        pos += 4
        vals = [alphabet.find(ch) if ch != "=" else 64 for ch in chars]
        if len(vals) < 2 or vals[0] < 0 or vals[1] < 0:
            break
        a, b = vals[0], vals[1]
        c = vals[2] if len(vals) > 2 else 64
        d = vals[3] if len(vals) > 3 else 64
        out.append((a << 2) | (b >> 4))
        if c >= 0 and c != 64:
            out.append(((b & 15) << 4) | (c >> 2))
            if d >= 0 and d != 64:
                out.append(((c & 3) << 6) | d)
    return out.decode("utf-8", errors="replace")


shell = fetch(PAGE)
script_m = re.search(r'<script[^>]+name=["\']pnp4web["\'][^>]+src=["\']([^"\']+)["\']', shell, flags=re.I)
payload_m = re.search(r'onload=["\'][^"\']*_0xac\(["\']?([A-Za-z0-9+/=]+)["\']?\)', shell, flags=re.I)
if not script_m or not payload_m:
    raise RuntimeError("PNP 보호 데이터 식별 실패")
js_url = urljoin(PAGE, script_m.group(1))
js = fetch(js_url)
decoded = decode_payload(payload_m.group(1), parse_alphabets(js))
print("decoded length", len(decoded))
print("ministry", "기후에너지환경부" in decoded, "325.6", "325.6" in decoded)

flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", decoded))
m = re.search(
    r"기후에너지환경부\s+"
    r"([0-9.]+|-)\s+"
    r"([0-9.]+|-)\s+"
    r"([0-9.]+|-)\s+"
    r"([0-9.]+|-)\s+"
    r"([0-9.]+|-)\s+"
    r"(\d{4}-\d{2}-\d{2})",
    flat,
)
if not m:
    idx = flat.find("기후에너지환경부")
    print("context", flat[idx:idx+500] if idx >= 0 else "not found")
    raise RuntimeError("공식 요금 행 파싱 실패")
print("RATE", m.groups())
