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


@dataclass
class OpinetEvidenceComparison:
    current_path: str
    print_path: str
    province: str
    sigungu: str
    product_label: str
    print_url: str


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


METROPOLITAN_PROVINCES = {"서울", "부산", "대구", "인천", "광주", "대전", "울산"}


def normalize_opinet_sigungu(province_name: str, sigungu_name: str) -> str:
    """Convert Kakao administrative names to the level OPINET uses.

    Provincial cities can include a lower district in Kakao (for example
    '화성시 만세구' or '수원시 영통구'), while OPINET's regional average table
    is keyed by the parent city ('화성시', '수원시'). Metropolitan cities keep
    their gu/gun level because that is the OPINET lookup unit.
    """
    province = normalize_province(province_name)
    sigungu = normalize_sigungu(sigungu_name)
    if province == "세종":
        return "세종"
    if province in METROPOLITAN_PROVINCES:
        return sigungu
    first = sigungu.split(" ", 1)[0]
    if first.endswith(("시", "군")):
        return first
    return sigungu


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


async def _uncheck_by_exact_label(page: Page, label_text: str) -> bool:
    """Uncheck an optional product column by its visible OPINET label."""
    checkbox = await _find_checkbox_by_exact_label(page, label_text)
    if checkbox is None:
        return False
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
    return True


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


async def _assert_evidence_date(page: Page, target: date) -> None:
    body = re.sub(r"\s+", "", await page.locator("body").inner_text())
    candidates = {
        f"{target.year}년{target.month:02d}월{target.day:02d}일",
        f"{target.year}년{target.month}월{target.day}일",
        target.isoformat(),
        target.strftime("%Y.%m.%d"),
    }
    normalized = {re.sub(r"\s+", "", value) for value in candidates}
    if not any(value in body for value in normalized):
        raise RuntimeError(
            f"오피넷 증빙 날짜가 요청일({target.isoformat()})과 일치하는지 확인할 수 없습니다."
        )


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


async def _bring_sigungu_into_view(
    page: Page,
    product_label: str,
    sigungu_name: str,
) -> bool:
    """Find a sigungu even when OPINET renders it below an internal scroll area.

    OPINET's long province tables (notably Gyeonggi) can live inside a fixed-height
    overflow container. A full-page screenshot does not expand that container, and
    some revisions render rows lazily while scrolling. Walk the relevant scroll
    containers, locate the requested row, and leave it centered for evidence capture.
    """
    target = re.sub(r"\s+", "", normalize_sigungu(sigungu_name))
    if not target:
        return False

    return bool(
        await page.evaluate(
            """
            async ({ productLabel, target }) => {
                const compact = (v) => (v || '').replace(/\s+/g, '').trim();
                const productKey = compact(productLabel);
                const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                const matches = (value) => {
                    const key = compact(value);
                    if (!key) return false;
                    return key === target
                        || key.endsWith(target)
                        || target.endsWith(key)
                        || key.includes(target);
                };

                const relevantTables = () => Array.from(document.querySelectorAll('table'))
                    .filter((table) => compact(table.innerText).includes(productKey));

                const findRow = () => {
                    for (const table of relevantTables()) {
                        for (const row of Array.from(table.querySelectorAll('tr'))) {
                            const cells = row.querySelectorAll('th, td');
                            if (!cells.length) continue;
                            if (matches(cells[0].innerText || cells[0].textContent)) {
                                return row;
                            }
                        }
                    }
                    return null;
                };

                const scrollContainers = () => {
                    const found = [];
                    for (const table of relevantTables()) {
                        let node = table.parentElement;
                        while (node && node !== document.body && node !== document.documentElement) {
                            if (node.scrollHeight > node.clientHeight + 8 && !found.includes(node)) {
                                found.push(node);
                            }
                            node = node.parentElement;
                        }
                    }
                    return found;
                };

                const centerRow = async (row) => {
                    row.scrollIntoView({ block: 'center', inline: 'nearest' });
                    await sleep(80);
                    for (const container of scrollContainers()) {
                        if (!container.contains(row)) continue;
                        const rowRect = row.getBoundingClientRect();
                        const boxRect = container.getBoundingClientRect();
                        const delta = rowRect.top - boxRect.top
                            - Math.max(0, (container.clientHeight - rowRect.height) / 2);
                        if (Math.abs(delta) > 2) container.scrollTop += delta;
                    }
                    await sleep(80);
                };

                let row = findRow();
                if (row) {
                    await centerRow(row);
                    return true;
                }

                // Some OPINET result lists are lazy/virtualized. Traverse every
                // relevant overflow container and rescan after each scroll step.
                const containers = scrollContainers();
                for (const container of containers) {
                    const maxScroll = Math.max(0, container.scrollHeight - container.clientHeight);
                    const step = Math.max(140, Math.floor(container.clientHeight * 0.72));
                    container.scrollTop = 0;
                    container.dispatchEvent(new Event('scroll', { bubbles: true }));
                    await sleep(100);

                    for (let pos = 0; pos <= maxScroll + step; pos += step) {
                        container.scrollTop = Math.min(pos, maxScroll);
                        container.dispatchEvent(new Event('scroll', { bubbles: true }));
                        await sleep(110);
                        row = findRow();
                        if (row) {
                            await centerRow(row);
                            return true;
                        }
                        if (container.scrollTop >= maxScroll - 1) break;
                    }
                }

                // Last fallback for pages whose result list follows window scroll.
                const pageStep = Math.max(400, Math.floor(window.innerHeight * 0.7));
                const maxPageScroll = Math.max(
                    0,
                    document.documentElement.scrollHeight - window.innerHeight
                );
                for (let y = 0; y <= maxPageScroll + pageStep; y += pageStep) {
                    window.scrollTo(0, Math.min(y, maxPageScroll));
                    await sleep(100);
                    row = findRow();
                    if (row) {
                        await centerRow(row);
                        return true;
                    }
                    if (window.scrollY >= maxPageScroll - 1) break;
                }
                return false;
            }
            """,
            {"productLabel": product_label, "target": target},
        )
    )


async def _highlight_evidence_target(
    page: Page,
    product_label: str,
    sigungu_name: str,
    expected_price: float | None = None,
) -> bool:
    """Visually mark the region row and applied price cell for evidence screenshots."""
    await _bring_sigungu_into_view(page, product_label, sigungu_name)
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


async def _open_print_view(page: Page) -> Page:
    """Open OPINET's own '화면인쇄' view when available."""
    button = page.locator("#btn_Print")
    if not await button.count():
        button = page.get_by_text("화면인쇄", exact=True)
    if not await button.count():
        raise RuntimeError("오피넷 화면인쇄 버튼을 찾지 못했습니다.")

    existing = list(page.context.pages)
    try:
        async with page.context.expect_page(timeout=10_000) as page_info:
            await button.first.click(force=True)
        print_page = await page_info.value
    except Exception as exc:
        # Some OPINET revisions create the window slightly after the click.
        await page.wait_for_timeout(1200)
        candidates = [p for p in page.context.pages if p not in existing]
        if not candidates:
            raise RuntimeError("오피넷 화면인쇄 창이 열리지 않았습니다.") from exc
        print_page = candidates[-1]

    try:
        await print_page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:
        await print_page.wait_for_load_state("domcontentloaded", timeout=10_000)
    await print_page.wait_for_timeout(700)
    return print_page


async def _expand_print_result(page: Page, product_label: str) -> None:
    """Expand OPINET print-result containers so long provinces are not clipped."""
    await page.evaluate(
        """
        (productLabel) => {
            const compact = (v) => (v || '').replace(/\s+/g, '').trim();
            const productKey = compact(productLabel);
            const tables = Array.from(document.querySelectorAll('table'))
                .filter((table) => compact(table.innerText).includes(productKey));
            const nodes = new Set();
            for (const table of tables) {
                nodes.add(table);
                for (const child of table.querySelectorAll('*')) {
                    if (child.scrollHeight > child.clientHeight + 4) nodes.add(child);
                }
                let node = table.parentElement;
                while (node && node !== document.documentElement) {
                    nodes.add(node);
                    node = node.parentElement;
                }
            }
            nodes.add(document.body);
            nodes.add(document.documentElement);
            for (const node of nodes) {
                if (!node || !node.style) continue;
                node.style.setProperty('height', 'auto', 'important');
                node.style.setProperty('max-height', 'none', 'important');
                node.style.setProperty('overflow', 'visible', 'important');
                node.style.setProperty('overflow-y', 'visible', 'important');
            }
            window.scrollTo(0, 0);
        }
        """,
        product_label,
    )
    await page.wait_for_timeout(200)


PDF_EVIDENCE_MAX_HEIGHT_PX = 900


async def _fold_print_result(
    page: Page,
    product_label: str,
    sigungu_name: str,
    *,
    max_height_px: int = PDF_EVIDENCE_MAX_HEIGHT_PX,
) -> bool:
    """Fold long OPINET print tables for legible A4 evidence.

    The query header is always kept. If the full official print view already fits
    the PDF evidence slot, nothing is changed. Otherwise the province-average row
    and the target sigungu with nearby rows are kept, while omitted ranges are
    replaced by explicit notice rows.
    """
    target = re.sub(r"\s+", "", normalize_sigungu(sigungu_name))
    if not target:
        return False

    result = await page.evaluate(
        """
        ({ productLabel, target, maxHeight }) => {
            const compact = (v) => (v || '').replace(/\s+/g, '').trim();
            const productKey = compact(productLabel);
            const matches = (value) => {
                const key = compact(value);
                return Boolean(
                    key && (
                        key === target
                        || key.endsWith(target)
                        || target.endsWith(key)
                        || key.includes(target)
                    )
                );
            };

            const pageHeight = Math.max(
                document.documentElement.scrollHeight || 0,
                document.body?.scrollHeight || 0
            );
            if (pageHeight <= maxHeight) {
                return { folded: false, height: pageHeight, reason: 'within-limit' };
            }

            const tables = Array.from(document.querySelectorAll('table'))
                .filter((table) => compact(table.innerText).includes(productKey));
            let table = null;
            let rows = [];
            let headerIndex = -1;
            let targetDataIndex = -1;

            for (const candidate of tables) {
                const candidateRows = Array.from(candidate.querySelectorAll('tr'));
                let candidateHeader = -1;
                for (let i = 0; i < Math.min(candidateRows.length, 8); i += 1) {
                    if (compact(candidateRows[i].innerText).includes(productKey)) {
                        candidateHeader = i;
                        break;
                    }
                }
                if (candidateHeader < 0) continue;

                const dataRows = candidateRows.slice(candidateHeader + 1);
                const found = dataRows.findIndex((row) => {
                    const first = row.querySelector('th, td');
                    return first && matches(first.innerText || first.textContent);
                });
                if (found >= 0) {
                    table = candidate;
                    rows = candidateRows;
                    headerIndex = candidateHeader;
                    targetDataIndex = found;
                    break;
                }
            }

            if (!table || targetDataIndex < 0) {
                return { folded: false, height: pageHeight, reason: 'target-not-found' };
            }

            const dataRows = rows.slice(headerIndex + 1);
            const dataCount = dataRows.length;
            const keep = new Set();

            // Keep the province summary at the top for context.
            if (dataCount) keep.add(0);

            // Keep enough neighboring rows to make the target row easy to verify.
            const radius = 3;
            const start = Math.max(0, targetDataIndex - radius);
            const end = Math.min(dataCount - 1, targetDataIndex + radius);
            for (let i = start; i <= end; i += 1) keep.add(i);

            // If this would barely shorten the page, keep the original official view.
            if (keep.size >= dataCount - 2) {
                return { folded: false, height: pageHeight, reason: 'little-to-omit' };
            }

            const omittedRanges = [];
            let rangeStart = null;
            for (let i = 0; i < dataCount; i += 1) {
                if (!keep.has(i) && rangeStart === null) rangeStart = i;
                const atEnd = i === dataCount - 1;
                if (rangeStart !== null && (keep.has(i) || atEnd)) {
                    const rangeEnd = keep.has(i) ? i - 1 : i;
                    omittedRanges.push([rangeStart, rangeEnd]);
                    rangeStart = null;
                }
            }

            // Hide omitted rows first.
            for (let i = 0; i < dataCount; i += 1) {
                if (!keep.has(i)) dataRows[i].style.setProperty('display', 'none', 'important');
            }

            const colCount = Math.max(
                1,
                ...rows.map((row) => row.querySelectorAll('th, td').length)
            );
            for (const [from, to] of omittedRanges) {
                const count = to - from + 1;
                const marker = document.createElement('tr');
                marker.setAttribute('data-opinet-fold-marker', '1');
                const cell = document.createElement('td');
                cell.colSpan = colCount;
                cell.textContent = `※ 동일 오피넷 조회결과 중 ${count}개 지역 행 생략`;
                cell.style.setProperty('text-align', 'center', 'important');
                cell.style.setProperty('font-weight', '700', 'important');
                cell.style.setProperty('color', '#475569', 'important');
                cell.style.setProperty('background', '#f8fafc', 'important');
                cell.style.setProperty('border-top', '1px dashed #94a3b8', 'important');
                cell.style.setProperty('border-bottom', '1px dashed #94a3b8', 'important');
                cell.style.setProperty('padding', '10px 6px', 'important');
                marker.appendChild(cell);

                const nextVisibleIndex = Array.from(keep)
                    .filter((idx) => idx > to)
                    .sort((a, b) => a - b)[0];
                if (nextVisibleIndex !== undefined) {
                    dataRows[nextVisibleIndex].parentNode.insertBefore(
                        marker,
                        dataRows[nextVisibleIndex]
                    );
                } else {
                    dataRows[dataRows.length - 1].parentNode.appendChild(marker);
                }
            }

            const note = document.createElement('div');
            note.setAttribute('data-opinet-fold-note', '1');
            note.textContent =
                '※ 정산서 가독성을 위해 동일 조회결과의 일부 지역 행을 생략하여 표시했습니다.';
            note.style.setProperty('margin', '8px 0 0', 'important');
            note.style.setProperty('font-size', '12px', 'important');
            note.style.setProperty('color', '#475569', 'important');
            table.insertAdjacentElement('afterend', note);

            window.scrollTo(0, 0);
            return {
                folded: true,
                height: pageHeight,
                targetIndex: targetDataIndex,
                dataCount,
                keptCount: keep.size,
                omittedCount: dataCount - keep.size,
            };
        }
        """,
        {"productLabel": product_label, "target": target, "maxHeight": max_height_px},
    )
    if result and result.get("folded"):
        await page.wait_for_timeout(180)
        return True
    return False


async def capture_opinet_evidence_comparison(
    travel_date: date,
    province_name: str,
    sigungu_name: str,
    vehicle_type: str,
    evidence_dir: str = "/tmp/evidence_compare",
) -> OpinetEvidenceComparison:
    """Capture the current OPINET page and its official print view for visual comparison."""
    if vehicle_type not in {"gasoline", "diesel", "lpg"}:
        raise ValueError("OPINET 비교 캡처 대상 차량이 아닙니다.")

    province = normalize_province(province_name)
    target_sigungu = normalize_opinet_sigungu(province_name, sigungu_name)
    product_label = PRODUCT_LABELS[vehicle_type]
    output_dir = Path(evidence_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    current_path = output_dir / (
        f"01_조회본_{travel_date.isoformat()}_{province}_{vehicle_type}.png"
    )
    print_path = output_dir / (
        f"02_인쇄본_{travel_date.isoformat()}_{province}_{vehicle_type}.png"
    )

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
        else:
            await _prepare_oil_page(page, travel_date, province, vehicle_type)

        # Apply the same presentation-only highlight to both candidates.
        try:
            await _highlight_evidence_target(
                page,
                product_label,
                target_sigungu,
                None,
            )
        except Exception:
            pass
        await page.screenshot(path=str(current_path), full_page=True)

        print_page = await _open_print_view(page)
        await _assert_evidence_date(print_page, travel_date)
        await _expand_print_result(print_page, product_label)
        await _fold_print_result(print_page, product_label, target_sigungu)
        try:
            await _highlight_evidence_target(
                print_page,
                product_label,
                target_sigungu,
                None,
            )
        except Exception:
            pass
        await print_page.screenshot(path=str(print_path), full_page=True)
        print_url = print_page.url
        await browser.close()

    return OpinetEvidenceComparison(
        current_path=str(current_path),
        print_path=str(print_path),
        province=province,
        sigungu=target_sigungu,
        product_label=product_label,
        print_url=print_url,
    )


async def _prepare_oil_page(page: Page, travel_date: date, province: str, vehicle_type: str) -> None:
    await page.goto(OIL_URL, wait_until="networkidle", timeout=60_000)
    await _select_date(page, travel_date)
    await _select_single_province_checkbox(page, province)

    # Evidence only needs the common road-vehicle fuels. Remove premium gasoline
    # and kerosene from OPINET's own result selection so the captured table is
    # narrower and easier to read, while leaving regular gasoline and diesel intact.
    for unused_label in ("고급휘발유", "실내등유", "등유"):
        try:
            await _uncheck_by_exact_label(page, unused_label)
        except Exception:
            pass

    try:
        await _select_by_id_or_label(page, PRODUCT_IDS[vehicle_type], PRODUCT_LABELS[vehicle_type])
    except Exception:
        pass

    await _click_search(page)
    await _assert_evidence_date(page, travel_date)


async def _prepare_lpg_page(page: Page, travel_date: date, province: str) -> None:
    await page.goto(LPG_URL, wait_until="networkidle", timeout=60_000)
    await _select_date(page, travel_date)
    await _select_single_province_checkbox(page, province)
    await _click_search(page)
    await _assert_evidence_date(page, travel_date)


async def query_opinet_region_prices(
    travel_date: date,
    province_name: str,
    vehicle_type: str,
    evidence_dir: str = "/tmp/evidence",
    highlight_sigungu: str | None = None,
    highlight_expected_price: float | None = None,
    evidence_view: str = "current",
) -> OpinetRegionResult:
    if vehicle_type not in {"gasoline", "diesel", "lpg"}:
        raise ValueError("OPINET 조회 대상 차량이 아닙니다.")

    province = normalize_province(province_name)
    product_label = PRODUCT_LABELS[vehicle_type]
    normalized_highlight_sigungu = (
        normalize_opinet_sigungu(province_name, highlight_sigungu)
        if highlight_sigungu
        else None
    )
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

        if normalized_highlight_sigungu:
            await _bring_sigungu_into_view(page, product_label, normalized_highlight_sigungu)
        prices = await _extract_region_price_table(page, product_label)
        if evidence_view == "print":
            print_page = await _open_print_view(page)
            await _assert_evidence_date(print_page, travel_date)
            await _expand_print_result(print_page, product_label)
            if normalized_highlight_sigungu:
                await _fold_print_result(
                    print_page,
                    product_label,
                    normalized_highlight_sigungu,
                )
                try:
                    await _highlight_evidence_target(
                        print_page,
                        product_label,
                        normalized_highlight_sigungu,
                        highlight_expected_price,
                    )
                except Exception:
                    pass
            await print_page.screenshot(path=str(evidence_path), full_page=True)
        else:
            if normalized_highlight_sigungu:
                try:
                    await _highlight_evidence_target(
                        page,
                        product_label,
                        normalized_highlight_sigungu,
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