from __future__ import annotations

import base64
import html
from pathlib import Path

from playwright.async_api import async_playwright

from app.models import EstimateResponse, TravelRequest


def _e(value) -> str:
    return html.escape(str(value or "-"))


def _won(value: int | float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}원"


def _num(value: int | float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:,.{digits}f}"


def _period(req: TravelRequest) -> str:
    end = req.end_date or req.travel_date
    if end == req.travel_date:
        return req.travel_date.isoformat()
    return f"{req.travel_date.isoformat()} ~ {end.isoformat()}"


def _trip_type(req: TravelRequest) -> str:
    if req.trip_type != "training":
        return "일반출장"
    stay = {
        "nonresidential": "비숙박",
        "residential": "숙박",
        "custom": "혼합",
    }.get(req.training_stay_mode, req.training_stay_mode)
    return f"교육훈련({stay})"


def _place(name: str | None, address: str | None, fallback: str) -> str:
    if name and address and name != address:
        return f"{name} / {address}"
    return name or address or fallback


def _image_data_uri(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    encoded = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


async def generate_estimate_pdf(
    req: TravelRequest,
    result: EstimateResponse,
    output_path: str,
    *,
    evidence_path: str | None = None,
    evidence_error: str | None = None,
) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    evidence_uri = _image_data_uri(evidence_path)
    origin = _place(result.resolved_origin_name, result.resolved_origin_address, req.origin)
    destination = _place(result.resolved_destination_name, result.resolved_destination_address, req.destination)
    applicant = " / ".join(v for v in [req.affiliation, req.position, req.traveler_name] if v) or "-"
    price_date = result.fuel_price_date.isoformat() if result.fuel_price_date else "-"
    round_trips = "편도" if result.round_trip_count == 0.5 else f"{result.round_trip_count:g}회"
    vehicle = result.vehicle_label or req.vehicle_type
    eff = (
        f"{result.effective_efficiency:g} {result.efficiency_unit}"
        if result.effective_efficiency and result.efficiency_unit
        else "-"
    )

    if evidence_uri:
        evidence_block = f'<img class="evidence-img" src="{evidence_uri}" alt="오피넷 증빙">'
        evidence_status = "오피넷 공식 화면 확인 완료"
    else:
        reason = evidence_error or "해당 차량은 현재 오피넷 화면 증빙 대상이 아닙니다."
        evidence_block = f'<div class="evidence-empty"><b>증빙 이미지 미첨부</b><br>{_e(reason)}</div>'
        evidence_status = reason

    body = f"""
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 10mm; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: "Noto Sans CJK KR", "Noto Sans KR", "Malgun Gothic", sans-serif; color: #111827; font-size: 10.5px; }}
  .page {{ min-height: 277mm; position: relative; }}
  .page.break {{ page-break-after: always; }}
  h1 {{ margin: 0 0 3mm; text-align: center; font-size: 20px; letter-spacing: .08em; }}
  h2 {{ margin: 0 0 2mm; font-size: 13px; }}
  .sub {{ text-align: center; color: #64748b; margin-bottom: 4mm; }}
  table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
  th, td {{ border: 1px solid #64748b; padding: 2.1mm 2.4mm; vertical-align: middle; line-height: 1.45; }}
  th {{ background: #f1f5f9; font-weight: 700; text-align: center; }}
  .label {{ width: 18%; }}
  .money {{ text-align: right; font-weight: 700; }}
  .total {{ font-size: 15px; font-weight: 800; text-align: right; background: #f8fafc; }}
  .section {{ margin-top: 4mm; }}
  .formula {{ padding: 3mm; border: 1px solid #cbd5e1; background: #f8fafc; line-height: 1.65; word-break: keep-all; }}
  .small {{ font-size: 9px; color: #475569; }}
  .declare {{ margin-top: 5mm; padding-top: 4mm; border-top: 1px solid #94a3b8; line-height: 1.8; }}
  .sign {{ text-align: right; margin-top: 7mm; font-size: 11px; }}
  .page2-head {{ display: grid; grid-template-columns: 1fr 1fr; gap: 3mm; margin-bottom: 3mm; }}
  .basis {{ border: 1px solid #cbd5e1; padding: 3mm; line-height: 1.6; min-height: 25mm; }}
  .evidence-wrap {{ height: 228mm; border: 1px solid #cbd5e1; padding: 2mm; display: flex; align-items: center; justify-content: center; overflow: hidden; background: #fff; }}
  .evidence-img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
  .evidence-empty {{ text-align: center; color: #64748b; line-height: 1.8; padding: 20mm; }}
  .footer {{ position: absolute; bottom: 0; left: 0; right: 0; text-align: center; color: #94a3b8; font-size: 8px; }}
</style>
</head>
<body>
  <section class="page break">
    <h1>국내출장 여비신청서</h1>
    <div class="sub">여비정산 자동화 - 실무형 1차 서식</div>

    <table>
      <tr><th class="label">신청인</th><td colspan="3">{_e(applicant)}</td></tr>
      <tr><th>출장기간</th><td>{_e(_period(req))}</td><th>출장유형</th><td>{_e(_trip_type(req))}</td></tr>
      <tr><th>출장목적</th><td colspan="3">{_e(req.purpose)}</td></tr>
      <tr><th>출발지</th><td colspan="3">{_e(origin)}</td></tr>
      <tr><th>출장지</th><td colspan="3">{_e(destination)}</td></tr>
      <tr><th>거리기준</th><td>{_e(result.distance_source)}</td><th>편도거리</th><td>{_num(result.one_way_distance_km)} km</td></tr>
      <tr><th>차량</th><td>{_e(vehicle)}</td><th>연비/전비</th><td>{_e(eff)}</td></tr>
      <tr><th>유가 기준일</th><td>{_e(price_date)} (출장 첫째 날)</td><th>적용단가</th><td>{_won(result.energy_price)}</td></tr>
    </table>

    <div class="section">
      <h2>여비 산출내역</h2>
      <table>
        <tr><th>항목</th><th>산출근거</th><th style="width:24%">금액</th></tr>
        <tr><td>자동차운임</td><td>{_e(result.calculation_formula)}</td><td class="money">{_won(result.estimated_transport_cost)}</td></tr>
        <tr><td>일비</td><td>{_e(result.daily_note)}</td><td class="money">{_won(result.daily_allowance)}</td></tr>
        <tr><td>식비</td><td>{_e(result.meal_note)}</td><td class="money">{_won(result.meal_allowance)}</td></tr>
        <tr><td>통행료</td><td>직접 입력</td><td class="money">{_won(result.toll_fee)}</td></tr>
        <tr><td>주차료</td><td>직접 입력</td><td class="money">{_won(result.parking_fee)}</td></tr>
        <tr><td>숙박비</td><td>직접 입력</td><td class="money">{_won(result.lodging_fee)}</td></tr>
        <tr><th colspan="2">합계</th><td class="total">{_won(result.total_expense)}</td></tr>
      </table>
    </div>

    <div class="section">
      <h2>자동차운임 계산 확인</h2>
      <div class="formula">
        편도 기준거리 {_num(result.one_way_distance_km)} km / 왕복횟수 {round_trips}<br>
        {_e(result.calculation_formula)}<br>
        <span class="small">거리 근거: {_e(result.distance_source)} / 가격 출처: {_e(result.price_source)}</span>
      </div>
    </div>

    <div class="declare">
      위와 같이 국내출장 여비를 신청합니다. 계산값은 입력된 출장정보와 적용 기준에 따라 자동 산출되었습니다.
      최종 지급 전에는 소속 기관의 적용 기준 및 증빙을 확인합니다.
    </div>
    <div class="sign">신청인&nbsp;&nbsp; {_e(req.traveler_name or "________________")} &nbsp;&nbsp;(서명)</div>
    <div class="footer">1 / 2</div>
  </section>

  <section class="page">
    <h1>산출근거 및 증빙</h1>
    <div class="page2-head">
      <div class="basis">
        <b>거리 산출근거</b><br>
        {_e(result.distance_source)}<br>
        편도 {_num(result.one_way_distance_km)} km / 적용거리 {_num(result.transport_distance_km)} km
      </div>
      <div class="basis">
        <b>유가 및 자동차운임</b><br>
        {_e(price_date)} / {_won(result.energy_price)}<br>
        {_e(result.calculation_formula)}
      </div>
    </div>
    <div class="small" style="margin-bottom:2mm">증빙상태: {_e(evidence_status)}</div>
    <div class="evidence-wrap">{evidence_block}</div>
    <div class="footer">2 / 2</div>
  </section>
</body>
</html>
"""

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = await browser.new_page(viewport={"width": 1200, "height": 1600})
        await page.set_content(body, wait_until="networkidle")
        await page.pdf(
            path=output_path,
            format="A4",
            print_background=True,
            prefer_css_page_size=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
        )
        await browser.close()

    return output_path
