from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from urllib.parse import urljoin
from urllib.request import Request, urlopen

SOURCE_URL = "https://ev.or.kr/nportal/evcarInfo/initEvcarChargePriceV2.do"
DATA_PATH = __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "ev_charge_price_history.json"


def _fetch_text(url: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; travel-expense-web/1.0; +GitHub Actions)",
            "Accept-Language": "ko-KR,ko;q=0.9",
        },
    )
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _js_unescape(value: str) -> str:
    def _hex(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    value = re.sub(r"\\x([0-9a-fA-F]{2})", _hex, value)
    value = re.sub(r"\\u([0-9a-fA-F]{4})", _hex, value)
    return value.replace(r"\"", '"').replace(r"\\", "\\")


def _parse_pnp_alphabets(source: str) -> list[str]:
    array_match = re.search(r"var In=\[([\s\S]*?)\],zn=", source)
    if not array_match:
        array_match = re.search(r"var In=Array\(([\s\S]*?)\),zn=", source)
    if not array_match:
        raise RuntimeError("pnp4web 문자표 배열을 찾지 못했습니다.")

    fragments = [
        _js_unescape(value)
        for value in re.findall(r'"((?:\\.|[^"\\])*)"', array_match.group(1))
    ]
    if not fragments:
        raise RuntimeError("pnp4web 문자표가 비어 있습니다.")

    alphabets: list[str] = []
    for index in range(7):
        expression = re.search(rf"o{index}:([^,}}]+)", source)
        if not expression:
            raise RuntimeError(f"pnp4web o{index} 문자표를 찾지 못했습니다.")
        fragment_indexes = [
            int(value) for value in re.findall(r"In\[(\d+)\]", expression.group(1))
        ]
        alphabet = "".join(fragments[item] for item in fragment_indexes)
        if len(alphabet) < 64:
            raise RuntimeError(
                f"pnp4web o{index} 문자표 길이가 올바르지 않습니다: {len(alphabet)}"
            )
        alphabets.append(alphabet)
    return alphabets


def _decode_pnp_payload(payload: str, alphabets: list[str]) -> str:
    if len(payload) < 3:
        raise RuntimeError("보호된 본문 payload가 비어 있습니다.")

    try:
        alphabet_index = int(payload[0])
        rotation = int(payload[1])
    except ValueError as exc:
        raise RuntimeError("보호된 본문의 문자표 식별자가 올바르지 않습니다.") from exc

    base_alphabet = alphabets[alphabet_index]
    alphabet = base_alphabet[rotation:] + base_alphabet[:rotation]
    encoded = re.sub(r"[^A-Za-z0-9+/=]", "", payload[2:])

    decoded = bytearray()
    offset = 0
    while offset < len(encoded):
        block = encoded[offset : offset + 4]
        offset += 4
        if len(block) < 2:
            break

        values = [64 if char == "=" else alphabet.find(char) for char in block]
        a, b = values[0], values[1]
        if a < 0 or b < 0:
            break

        c = values[2] if len(values) > 2 else 64
        d = values[3] if len(values) > 3 else 64
        decoded.append((a << 2) | (b >> 4))

        if c >= 0 and c != 64:
            decoded.append(((b & 15) << 4) | (c >> 2))
            if d >= 0 and d != 64:
                decoded.append(((c & 3) << 6) | d)

    return decoded.decode("utf-8", errors="replace")


def _decode_protected_html(shell_html: str) -> str:
    if not re.search(r"<meta[^>]+name=['\"]penc['\"]", shell_html, flags=re.I):
        return shell_html

    script_tag = re.search(
        r"<script[^>]*name=['\"]pnp4web['\"][^>]*>",
        shell_html,
        flags=re.I,
    )
    if not script_tag:
        raise RuntimeError("pnp4web 스크립트 태그를 찾지 못했습니다.")

    src_match = re.search(r"src=['\"]([^'\"]+)['\"]", script_tag.group(0), flags=re.I)
    if not src_match:
        raise RuntimeError("pnp4web 스크립트 URL을 찾지 못했습니다.")

    payload_match = re.search(
        r"onload=['\"][^'\"]*_0xac\([\"']?([A-Za-z0-9+/=]+)[\"']?\)",
        shell_html,
        flags=re.I,
    )
    if not payload_match:
        raise RuntimeError("보호된 무공해차 누리집 본문을 찾지 못했습니다.")

    pnp_source = _fetch_text(urljoin(SOURCE_URL, src_match.group(1)))
    return _decode_pnp_payload(
        payload_match.group(1),
        _parse_pnp_alphabets(pnp_source),
    )


def _as_float(value, field: str) -> float:
    if value in (None, "", "-"):
        raise RuntimeError(f"공식 요금표의 {field} 값이 비어 있습니다.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"공식 요금표의 {field} 값을 해석하지 못했습니다: {value}") from exc


def _parse_rate_row(decoded_html: str) -> dict:
    # 현재 누리집은 사업자 요금 매트릭스를 페이지 내부 JSON 객체로 포함합니다.
    object_match = re.search(
        r'\{[^{}]*"BNM"\s*:\s*"기후에너지환경부"[^{}]*\}',
        decoded_html,
    )
    if object_match:
        try:
            row = json.loads(object_match.group(0))
        except json.JSONDecodeError as exc:
            raise RuntimeError("기후에너지환경부 요금 행 JSON 해석에 실패했습니다.") from exc

        member = {
            "slow_under_30": _as_float(row.get("M_S1"), "회원가 30kW 미만"),
            "medium_30_49": _as_float(row.get("M_S2"), "회원가 30~49kW"),
            "rapid_50_99": _as_float(row.get("M_S3"), "회원가 50~99kW"),
            "rapid_100_199": _as_float(row.get("M_S4"), "회원가 100~199kW"),
            "ultra_200_plus": _as_float(row.get("M_S5"), "회원가 200kW 이상"),
        }
        nonmember = {
            "slow_under_30": _as_float(row.get("N_S1"), "비회원가 30kW 미만"),
            "medium_30_49": _as_float(row.get("N_S2"), "비회원가 30~49kW"),
            "rapid_50_99": _as_float(row.get("N_S3"), "비회원가 50~99kW"),
            "rapid_100_199": _as_float(row.get("N_S4"), "비회원가 100~199kW"),
            "ultra_200_plus": _as_float(row.get("N_S5"), "비회원가 200kW 이상"),
        }

        # 현재 기후부 행은 회원/비회원 요금이 동일합니다. 향후 달라지면
        # 어떤 값을 여비 기준으로 쓸지 정책 판단이 필요하므로 자동 반영을 멈춥니다.
        if abs(member["rapid_50_99"] - nonmember["rapid_50_99"]) >= 0.0001:
            raise RuntimeError(
                "기후에너지환경부 급속(50~99kW) 회원가와 비회원가가 달라졌습니다. "
                "여비 적용 기준을 수동 검토해주세요."
            )

        return {
            **member,
            "member_rates": member,
            "nonmember_rates": nonmember,
            "source_updated_at": str(row.get("UPD_DT") or "").strip(),
        }

    # 페이지 구조가 표 텍스트 방식으로 바뀐 경우를 위한 보조 파서입니다.
    visible = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", decoded_html))
    match = re.search(
        r"기후에너지환경부\s+"
        r"([0-9.]+|-)\s+"
        r"([0-9.]+|-)\s+"
        r"([0-9.]+|-)\s+"
        r"([0-9.]+|-)\s+"
        r"([0-9.]+|-)\s+"
        r"(\d{4}-\d{2}-\d{2})",
        visible,
    )
    if not match:
        raise RuntimeError(
            "무공해차 누리집에서 기후에너지환경부 요금 행을 찾지 못했습니다. "
            "페이지 구조가 바뀌었는지 확인해주세요."
        )

    return {
        "slow_under_30": float(match.group(1)),
        "medium_30_49": float(match.group(2)),
        "rapid_50_99": float(match.group(3)),
        "rapid_100_199": float(match.group(4)),
        "ultra_200_plus": float(match.group(5)),
        "source_updated_at": match.group(6),
    }


def fetch_official_rate() -> dict:
    shell_html = _fetch_text(SOURCE_URL)
    decoded_html = _decode_protected_html(shell_html)
    result = _parse_rate_row(decoded_html)
    if not result.get("source_updated_at"):
        raise RuntimeError("무공해차 누리집 요금 갱신일을 확인하지 못했습니다.")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--propose",
        action="store_true",
        help="변경이 감지되면 검토용(review_required) 이력 항목을 JSON에 추가합니다.",
    )
    args = parser.parse_args()

    with DATA_PATH.open("r", encoding="utf-8") as fp:
        data = json.load(fp)

    official = fetch_official_rate()
    active = [row for row in data.get("rates", []) if row.get("status") == "active"]
    if not active:
        raise RuntimeError("활성 전기차 기준단가가 없습니다.")

    latest = max(active, key=lambda row: row["effective_from"])
    current = float(latest["price_per_kwh"])
    observed = float(official["rapid_50_99"])

    print(
        json.dumps(
            {
                "current_price": current,
                "observed_price": observed,
                "source_updated_at": official["source_updated_at"],
            },
            ensure_ascii=False,
        )
    )

    if abs(current - observed) < 0.0001:
        print("변경 없음")
        return 0

    if not args.propose:
        print("요금 변경 감지", file=sys.stderr)
        return 2

    updated_at = official["source_updated_at"]
    pending = [
        row
        for row in data.get("rates", [])
        if row.get("status") == "review_required"
        and float(row.get("price_per_kwh", -1)) == observed
        and row.get("source_updated_at") == updated_at
    ]
    if pending:
        print("동일한 검토 대기 항목이 이미 있습니다.")
        return 0

    data["rates"].append(
        {
            # 누리집의 갱신일과 실제 시행일은 다를 수 있어 review_required 상태로만
            # 제안합니다. 병합 전에 공식 공지의 시행일로 고쳐야 실제 계산에 사용됩니다.
            "effective_from": updated_at,
            "price_per_kwh": observed,
            "rate_label": "급속(50~99kW)",
            "source_updated_at": updated_at,
            "source_url": SOURCE_URL,
            "status": "review_required",
            "note": (
                "자동 감지된 변경값입니다. 실제 시행일을 공식 공지에서 확인한 뒤 "
                "effective_from을 수정하고 status를 active로 변경하여 반영하세요."
            ),
            "observed_rate_matrix": {
                "slow_under_30": official["slow_under_30"],
                "medium_30_49": official["medium_30_49"],
                "rapid_50_99": official["rapid_50_99"],
                "rapid_100_199": official["rapid_100_199"],
                "ultra_200_plus": official["ultra_200_plus"],
                "member_rates": official.get("member_rates"),
                "nonmember_rates": official.get("nonmember_rates"),
            },
        }
    )
    data["version"] = date.today().isoformat()

    with DATA_PATH.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
        fp.write("\n")

    print("검토용 이력 항목을 추가했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
