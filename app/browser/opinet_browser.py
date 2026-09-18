from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from playwright.async_api import Page, async_playwright

OIL_URL = "https://www.opinet.co.kr/user/dopospdrg/dopOsPdrgAreaView.do"
LPG_URL = "https://www.opinet.co.kr/user/dopvsavsel/dopVsAreaselSelect.do"

PROVINCE_ALIASES = {
    "서울특별시": "서울", "서울": "서울", "부산광역시": "부산", "부산": "부산",
    "대구광역시": "대구", "대구": "대구", "인천광역시": "인천", "인천": "인천",
    "광주광역시": "광주", "광주": "광주", "대전광역시": "대전", "대전": "대전",
    "울산광역시": "울산", "울산": "울산", "세종특별자치시": "세종", "세종": "세종",
    "경기도": "경기", "경기": "경기", "강원특별자치도": "강원", "강원도": "강원", "강원": "강원",
    "충청북도": "충북", "충북": "충북", "충청남도": "충남", "충남": "충남",
    "전북특별자치도": "전북", "전라북도": "전북", "전북": "전북",
    "전라남도": "전남", "전남": "전남", "경상북도": "경북", "경북": "경북",
    "경상남도": "경남", "경남": "경남", "제주특별자치도": "제주", "제주": "제주",
}

# 2026 OPINET added/changed some region labels. Evidence selection therefore uses
# exact visible labels first instead of depending on historical checkbox numbers.
REGION_LABELS = [
    "서울", "부산", "대구", "인천", "전남광주", "대전", "울산", "경기",
    "강원", "충북", "충남", "전북", "경북", "경남", "제주", "세종", "광주", "전남",
]

SIDO_IDS = {
    "서울": "chk2_1", "부산": "chk2_2", "대구": "chk2_3", "인천": "chk2_4",
    "광주": "chk2_5", "대전": "chk2_6", "울산": "chk2_7", "경기": "chk2_8",
    "강원": "chk2_9", "충북": "chk2_10", "충남": "chk2_11", "전북": "chk2_12",
    "전남": "chk2_13", "경북": "chk2_14", "경남": "chk2_15", "제주": "chk2_16", "세종": "chk2_17",
}

PRODUCT_IDS = {"gasoline": "chk3_2", "diesel": "chk3_3"}
PRODUCT_LABELS = {"gasoline": "보통휘발유", "diesel": "자동차용경유", "lpg": "자동차부탄"}


@dataclass
class OpinetRegionResult:
    prices: dict[str, float]
    province: str
    product_label: str
    evidence_path: str
    source_url: str


def normalize_province(value: str) -> str:
    value = value.strip()
    if value in PROVINCE_ALIASES:
        return PROVINCE_ALIASES[value]
    for long_name, short_name in PROVINCE_ALIASES.items():
        if long_name and long_name in value:
            return short_name
    raise ValueError(f"오피넷 지역명으로 변환할 수 없습니다: {value}")


def normalize_sigungu(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _province_option_candidates(province: str) -> list[str]:
    values = [province]
    for long_name, short_name in PROVINCE_ALIASES.items():
        if short_name == province and long_name not in values:
            values.append(long_name)
    return values


async def _find_checkbox_by_exact_label(page: Page, label_text: str):
    labels = page.locator("label")
    for i in range(await labels.count()):
        label = labels.nth(i)
        text = re.sub(r"\s+", " ", (await label.inner_text()).strip())
        if text != label_text:
            continue

        inside = label.locator('input[type="checkbox"]')
        if await inside.count():
            return inside.first

        for_attr = await label.get_attribute("for")
        if for_attr:
            target = page.locator(f"#{for_attr}")
            if await target.count():
                input_type = await target.first.get_attribute("type")
                if input_type == "checkbox":
                    return target.first
    return None


async def _select_single_province_checkbox(page: Page, province: str) -> None:
    """Select exactly one province so OPINET returns the sigungu table.

    OPINET's own help says sigungu averages are shown only when one province is
    selected. Do not use the styled sido dropdown for this purpose; the result
    mode is controlled by the province checkboxes above it.
    """
    target = await _find_checkbox_by_exact_label(page, province)

    # Uncheck every province checkbox we can identify by its visible label.
    found_any = False
    for region_label in REGION_LABELS:
        checkbox = await _find_checkbox_by_exact_label(page, region_label)
        if checkbox is None:
            continue
        found_any = True
        try:
            if await checkbox.is_checked():
                await checkbox.uncheck(force=True)
        except Exception:
            await checkbox.evaluate(
                """
                (el) => {
                    el.checked = false;
                    el.dispatchEvent(new Event('input', {bubbles:true}));
                    el.dispatchEvent(new Event('change', {bubbles:true}));
                }
                """
            )

    if target is None:
        # Historical-ID fallback only when exact label lookup fails.
        base_id = SIDO_IDS.get(province)
        candidates = [base_id, f"area_{base_id}" if base_id else None]
        for element_id in candidates:
            if not element_id:
                continue
            loc = page.locator(f"#{element_id}")
            if await loc.count():
                target = loc.first
                break

    if target is None:
        raise RuntimeError(f"오피넷 지역 체크박스에서 {province}을(를) 찾지 못했습니다.")

    try:
        await target.check(force=True)
    except Exception:
        await target.evaluate(
            """
            (el) => {
                el.checked = true;
                el.dispatchEvent(new Event('input', {bubbles:true}));
                el.dispatchEvent(new Event('change', {bubbles:true}));
                el.dispatchEvent(new Event('click', {bubbles:true}));
            }
            """
        )

    if not found_any:
        # Give old pages a moment to synchronize any custom checkbox UI.
        await page.wait_for_timeout(300)
    await page.wait_for_timeout(500)


async def _select_by_id_or_label(page: Page, element_id: str, label_text: str) -> None:
    labels = page.locator("label", has_text=label_text)
    for i in range(await labels.count()):
        label = labels.nth(i)
        if (await label.inner_text()).strip() != label_text:
            continue
        candidate = label.locator('input[type="checkbox"], input[type="radio"]')
        if await candidate.count():
            await candidate.check(force=True)
            return
        for_attr = await label.get_attribute("for")
        if for_attr:
            target = page.locator(f"#{for_attr}")
            if await target.count():
                await target.check(force=True)
                return

    candidate = page.get_by_text(label_text, exact=True)
    if await candidate.count():
        try:
            await candidate.first.click(force=True)
            return
        except Exception:
            pass

    locator = page.locator(f"#{element_id}")
    if await locator.count():
        await locator.check(force=True)
        return
    raise RuntimeError(f"오피넷 선택항목을 찾지 못했습니다: {label_text}")


async def _select_date(page: Page, target: date) -> None:
    values = {
        "STA_Y": str(target.year), "STA_M": f"{target.month:02d}", "STA_D": f"{target.day:02d}",
        "END_Y": str(target.year), "END_M": f"{target.month:02d}", "END_D": f"{target.day:02d}",
    }
    for element_id, value in values.items():
        loc = page.locator(f"#{element_id}")
        if not await loc.count():
            raise RuntimeError(f"오피넷 날짜 선택요소를 찾지 못했습니다: {element_id}")
        try:
            await loc.select_option(value=value)
        except Exception:
            label = str(int(value)) if element_id.endswith(("_M", "_D")) else value
            await loc.select_option(label=label)


async def _clear_all_regions(page: Page) -> None:
    # Kept for compatibility with older OPINET pages. New evidence flow uses
    # _select_single_province_checkbox because the old all-select button toggles.
    for region_label in REGION_LABELS:
        checkbox = await _find_checkbox_by_exact_label(page, region_label)
        if checkbox is not None:
            try:
                if await checkbox.is_checked():
                    await checkbox.uncheck(force=True)
            except Exception:
                pass


async def _set_hidden_select_by_label(page: Page, selector: str, labels: list[str]) -> bool:
    locator = page.locator(selector)
    if not await locator.count():
        return False

    result = await locator.first.evaluate(
        """
        (select, labels) => {
            const norm = (v) => (v || '').replace(/\\s+/g, ' ').trim();
            const wanted = labels.map(norm);
            const options = Array.from(select.options || []);
            const option = options.find((o) => wanted.includes(norm(o.textContent)))
                || options.find((o) => wanted.includes(norm(o.label)))
                || options.find((o) => wanted.includes(norm(o.value)));
            if (!option) return null;
            select.value = option.value;
            option.selected = true;
            select.dispatchEvent(new Event('input', { bubbles: true }));
            select.dispatchEvent(new Event('change', { bubbles: true }));
            return { value: option.value, text: norm(option.textContent) };
        }
        """,
        labels,
    )
    return result is not None


async def _select_province_dropdown(page: Page, province: str) -> None:
    candidates = _province_option_candidates(province)
    if await _set_hidden_select_by_label(page, "#sido_cd", candidates):
        await page.wait_for_timeout(1200)
        return

    selects = page.locator("select")
    for si in range(await selects.count()):
        select = selects.nth(si)
        options = select.locator("option")
        option_count = await options.count()
        if option_count < 2:
            continue
        texts = [
            re.sub(r"\s+", " ", (await options.nth(oi).inner_text()).strip())
            for oi in range(option_count)
        ]
        if not any(candidate in texts for candidate in candidates):
            continue
        result = await select.evaluate(
            """
            (el, labels) => {
                const norm = (v) => (v || '').replace(/\\s+/g, ' ').trim();
                const wanted = labels.map(norm);
                const option = Array.from(el.options || []).find(
                    (o) => wanted.includes(norm(o.textContent)) || wanted.includes(norm(o.label))
                );
                if (!option) return false;
                el.value = option.value;
                option.selected = true;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }
            """,
            candidates,
        )
        if result:
            await page.wait_for_timeout(1200)
            return
    raise RuntimeError(f"오피넷 시도 선택 드롭다운에서 {province}을(를) 찾지 못했습니다.")


async def _click_search(page: Page) -> None:
    button = page.locator("#btn_Search")
    if await button.count():
        await button.click(force=True)
    else:
        button = page.get_by_text("조회", exact=True)
        if not await button.count():
            raise RuntimeError("오피넷 조회 버튼을 찾지 못했습니다.")
        await button.first.click(force=True)
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(900)


def _parse_number(text: str) -> Optional[float]:
    match = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    return float(match.group(0)) if match else None


async def _extract_region_price_table(page: Page, product_label: str) -> dict[str, float]:
    prices: dict[str, float] = {}
    tables = page.locator("table")

    for ti in range(await tables.count()):
        table = tables.nth(ti)
        rows = table.locator("tr")
        row_count = await rows.count()
        if row_count < 2:
            continue

        header_row_index: Optional[int] = None
        product_index: Optional[int] = None
        for ri in range(min(row_count, 7)):
            cells = rows.nth(ri).locator("th, td")
            texts = [
                re.sub(r"\s+", " ", (await cells.nth(i).inner_text()).strip())
                for i in range(await cells.count())
            ]
            for ci, text in enumerate(texts):
                if product_label in text:
                    header_row_index = ri
                    product_index = ci
                    break
            if product_index is not None:
                break

        if product_index is None or header_row_index is None:
            continue

        for ri in range(header_row_index + 1, row_count):
            cells = rows.nth(ri).locator("th, td")
            if await cells.count() <= product_index:
                continue
            texts = [
                re.sub(r"\s+", " ", (await cells.nth(i).inner_text()).strip())
                for i in range(await cells.count())
            ]
            if not texts:
                continue
            row_name = texts[0].strip()
            if not row_name or row_name in {"지역", "구분", "합계", "평균"}:
                continue
            value = _parse_number(texts[product_index])
            if value is not None:
                prices[normalize_sigungu(row_name)] = value

    if not prices:
        raise RuntimeError(f"오피넷 결과에서 {product_label} 지역별 가격표를 찾지 못했습니다.")
    return prices


async def _highlight_evidence_target(
    page: Page,
    product_label: str,
    sigungu_name: str,
    expected_price: float | None = None,
) -> bool:
    """Visually mark the region row and applied price cell for evidence screenshots."""
    target = re.sub(r"\s+", "", normalize_sigungu(sigungu_name))
    if not target:
        return False

    tables = page.locator("table")
    for ti in range(await tables.count()):
        table = tables.nth(ti)
        rows = table.locator("tr")
        row_count = await rows.count()
        if row_count < 2:
            continue

        header_row_index: Optional[int] = None
        product_index: Optional[int] = None
        for ri in range(min(row_count, 7)):
            cells = rows.nth(ri).locator("th, td")
            texts = [
                re.sub(r"\s+", " ", (await cells.nth(i).inner_text()).strip())
                for i in range(await cells.count())
            ]
            for ci, text in enumerate(texts):
                if product_label in text:
                    header_row_index = ri
                    product_index = ci
                    break
            if product_index is not None:
                break

        if product_index is None or header_row_index is None:
            continue

        for ri in range(header_row_index + 1, row_count):
            row = rows.nth(ri)
            cells = row.locator("th, td")
            if await cells.count() <= product_index:
                continue

            row_name = re.sub(
                r"\s+",
                " ",
                (await cells.nth(0).inner_text()).strip(),
            )
            row_key = re.sub(r"\s+", "", normalize_sigungu(row_name))
            if not row_key:
                continue

            matches = (
                row_key == target
                or row_key.endswith(target)
                or target.endswith(row_key)
                or target in row_key
            )
            if not matches:
                continue

            price_cell = cells.nth(product_index)
            price_value = _parse_number(await price_cell.inner_text())
            if (
                expected_price is not None
                and price_value is not None
                and abs(price_value - float(expected_price)) > 0.05
            ):
                continue

            # Use inline !important styles only in the temporary browser DOM used
            # for the screenshot. This does not alter OPINET source data.
            await row.evaluate(
                """
                (el) => {
                    for (const cell of el.querySelectorAll('th, td')) {
                        cell.style.setProperty('background-color', '#fff8cc', 'important');
                    }
                }
                """
            )
            await cells.nth(0).evaluate(
                """
                (el) => {
                    el.style.setProperty('font-weight', '700', 'important');
                }
                """
            )
            await price_cell.evaluate(
                """
                (el) => {
                    el.style.setProperty('background-color', '#ffe28a', 'important');
                    el.style.setProperty('box-shadow', 'inset 0 0 0 2px #b7791f', 'important');
                    el.style.setProperty('font-weight', '800', 'important');
                }
                """
            )
            return True

    return False


async def _prepare_oil_page(page: Page, travel_date: date, province: str, vehicle_type: str) -> None:
    await page.goto(OIL_URL, wait_until="networkidle", timeout=60_000)
    await _select_date(page, travel_date)
    await _select_single_province_checkbox(page, province)

    try:
        await _select_by_id_or_label(page, PRODUCT_IDS[vehicle_type], PRODUCT_LABELS[vehicle_type])
    except Exception:
        pass

    await _click_search(page)


async def _prepare_lpg_page(page: Page, travel_date: date, province: str) -> None:
    await page.goto(LPG_URL, wait_until="networkidle", timeout=60_000)
    await _select_date(page, travel_date)
    await _select_single_province_checkbox(page, province)
    await _click_search(page)


async def query_opinet_region_prices(
    travel_date: date,
    province_name: str,
    vehicle_type: str,
    evidence_dir: str = "/tmp/evidence",
    highlight_sigungu: str | None = None,
    highlight_expected_price: float | None = None,
) -> OpinetRegionResult:
    if vehicle_type not in {"gasoline", "diesel", "lpg"}:
        raise ValueError("OPINET 조회 대상 차량이 아닙니다.")

    province = normalize_province(province_name)
    product_label = PRODUCT_LABELS[vehicle_type]
    output_dir = Path(evidence_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = output_dir / f"opinet_{travel_date.isoformat()}_{province}_{vehicle_type}.png"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1600},
            locale="ko-KR",
        )
        page = await context.new_page()

        if vehicle_type == "lpg":
            await _prepare_lpg_page(page, travel_date, province)
            source_url = LPG_URL
        else:
            await _prepare_oil_page(page, travel_date, province, vehicle_type)
            source_url = OIL_URL

        prices = await _extract_region_price_table(page, product_label)
        if highlight_sigungu:
            try:
                await _highlight_evidence_target(
                    page,
                    product_label,
                    highlight_sigungu,
                    highlight_expected_price,
                )
            except Exception:
                # Highlighting is presentation-only; never block a valid evidence capture.
                pass
        await page.screenshot(path=str(evidence_path), full_page=True)
        await browser.close()

    return OpinetRegionResult(
        prices=prices,
        province=province,
        product_label=product_label,
        evidence_path=str(evidence_path),
        source_url=source_url,
    )