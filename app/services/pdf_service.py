from __future__ import annotations

import html
from pathlib import Path

from playwright.async_api import async_playwright

from app.models import EstimateResponse, TravelRequest


def _won(value: int | float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}원"


async def generate_estimate_pdf(
    req: TravelRequest,
    result: EstimateResponse,
    output_path: str,
) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    body = f"""
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: "Noto Sans CJK KR", "Noto Sans KR", sans-serif; margin: 34px; color: #1f2937; }}
  h1 {{ font-size: 24px; margin-bottom: 8px; }}
  .sub {{ color: #64748b; margin-bottom: 28px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 10px; text-align: left; }}
  th {{ background: #f1f5f9; width: 28%; }}
  .amount {{ font-size: 18px; font-weight: 700; }}
  .note {{ margin-top: 22px; font-size: 10px; color: #64748b; }}
</style>
</head>
<body>
  <h1>자동차운임 산출내역</h1>
  <div class="sub">여비정산 자동화 시스템</div>
  <table>
    <tr><th>출장일</th><td>{html.escape(str(req.travel_date))}</td></tr>
    <tr><th>출발지</th><td>{html.escape(req.origin)}</td></tr>
    <tr><th>출장지</th><td>{html.escape(req.destination)}</td></tr>
    <tr><th>총 운행거리</th><td>{result.distance_km:,.1f} km</td></tr>
    <tr><th>거리 기준</th><td>{html.escape(result.distance_source)}</td></tr>
    <tr><th>차량 종류</th><td>{html.escape(req.vehicle_type)}</td></tr>
    <tr><th>연비/전비</th><td>{req.efficiency:g}</td></tr>
    <tr><th>적용 단가</th><td>{_won(result.energy_price)}</td></tr>
    <tr><th>가격 출처</th><td>{html.escape(result.price_source or "-")}</td></tr>
    <tr><th>자동차운임</th><td class="amount">{_won(result.estimated_transport_cost)}</td></tr>
  </table>
  <div class="note">실제 지급 전에는 소속 기관의 여비 규정, 고정거리표 및 증빙 기준을 확인해야 합니다.</div>
</body>
</html>
"""

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = await browser.new_page()
        await page.set_content(body, wait_until="networkidle")
        await page.pdf(
            path=output_path,
            format="A4",
            print_background=True,
            margin={"top": "12mm", "right": "12mm", "bottom": "12mm", "left": "12mm"},
        )
        await browser.close()

    return output_path
