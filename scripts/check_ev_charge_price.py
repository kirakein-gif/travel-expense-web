from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE_URL = "https://ev.or.kr/nportal/evcarInfo/initEvcarChargePriceV2.do"
DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "ev_charge_price_history.json"


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


def _visible_text(html: str) -> str:
    parser = TextExtractor()
    parser.feed(html)
    return re.sub(r"\s+", " ", " ".join(parser.parts))


def _parse_official_rate(text: str) -> dict | None:
    pattern = re.compile(
        r"기후에너지환경부\s+"
        r"([0-9.]+|-)\s+"
        r"([0-9.]+|-)\s+"
        r"([0-9.]+|-)\s+"
        r"([0-9.]+|-)\s+"
        r"([0-9.]+|-)\s+"
        r"(\d{4}-\d{2}-\d{2})"
    )
    match = pattern.search(text)
    if not match:
        return None
    return {
        "slow_under_30": float(match.group(1)),
        "medium_30_49": float(match.group(2)),
        "rapid_50_99": float(match.group(3)),
        "rapid_100_199": float(match.group(4)),
        "ultra_200_plus": float(match.group(5)),
        "source_updated_at": match.group(6),
    }


def _fetch_static_html() -> str:
    req = Request(
        SOURCE_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ddalkkak-travel-expense/1.24; +GitHub Actions)"
        },
    )
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _fetch_rendered_text() -> str:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError as exc:
        raise RuntimeError(
            "동적 요금표 확인에는 selenium이 필요합니다. "
            "GitHub Actions 설치 단계를 확인해주세요."
        ) from exc

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1440,1200")
    options.add_argument("--lang=ko-KR")
    options.page_load_strategy = "eager"

    driver = webdriver.Chrome(options=options)
    try:
        driver.set_page_load_timeout(45)
        driver.get(SOURCE_URL)

        def official_row_ready(drv):
            body = drv.find_element(By.TAG_NAME, "body").text
            return body if "기후에너지환경부" in body and re.search(r"\b325\.6\b", body) else False

        text = WebDriverWait(driver, 45).until(official_row_ready)
        return re.sub(r"\s+", " ", text)
    finally:
        driver.quit()


def fetch_official_rate() -> dict:
    static_text = _visible_text(_fetch_static_html())
    parsed = _parse_official_rate(static_text)
    if parsed:
        print("정적 HTML에서 공식 요금 확인")
        return parsed

    print("정적 HTML에 요금표가 없어 Selenium Chrome으로 동적 화면 확인")
    rendered_text = _fetch_rendered_text()
    parsed = _parse_official_rate(rendered_text)
    if parsed:
        print("동적 화면에서 공식 요금 확인")
        return parsed

    raise RuntimeError(
        "무공해차 누리집에서 기후에너지환경부 요금 행을 찾지 못했습니다. "
        "페이지 구조 또는 데이터 호출 방식을 확인해주세요."
    )


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
            "observed_rate_matrix": official,
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
