from __future__ import annotations

import base64
import html
import re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright

from app.models import EstimateResponse, TravelRequest
from app.services.travel_policy import DAILY_ALLOWANCE_RATE, MEAL_ALLOWANCE_RATE


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


def _passenger_names(value: str | None) -> list[str]:
    if not value:
        return []
    return [name.strip() for name in re.split(r"[,;\n]+", value) if name.strip()]


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
    passenger_names = _passenger_names(req.passengers)
    passenger_signature_html = ""
    if passenger_names:
        passenger_items = "".join(
            f'<span class="passenger-sign">{_e(name)}&nbsp;&nbsp;(서명)</span>'
            for name in passenger_names
        )
        passenger_signature_html = (
            '<div class="co-sign-row"><span class="sign-label">동승자</span>'
            f'<div class="passenger-signs">{passenger_items}</div></div>'
        )

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
  body {{ margin: 0; font-family: "Noto Sans CJK KR", "Noto Sans KR", "Malgun Gothic", sans-serif; color: #111827; font-size: 12px; }}
  .page {{ min-height: 277mm; position: relative; }}
  .page.break {{ page-break-after: always; }}
  h1 {{ margin: 0 0 2.5mm; text-align: center; font-size: 23px; letter-spacing: .07em; }}
  h2 {{ margin: 0 0 1.8mm; font-size: 14.5px; }}
  .sub {{ text-align: center; color: #475569; font-size: 11.5px; margin-bottom: 3mm; }}
  table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
  th, td {{ border: 1px solid #64748b; padding: 1.7mm 2.2mm; vertical-align: middle; line-height: 1.42; }}
  th {{ background: #f1f5f9; font-weight: 700; text-align: center; }}
  .label {{ width: 18%; }}
  .money {{ text-align: right; font-weight: 700; }}
  .total {{ font-size: 16px; font-weight: 800; text-align: right; background: #f8fafc; }}
  .section {{ margin-top: 3mm; }}
  .formula {{ padding: 2.5mm; border: 1px solid #cbd5e1; background: #f8fafc; line-height: 1.58; word-break: keep-all; font-size: 11.5px; }}
  .small {{ font-size: 10.5px; color: #334155; }}
  .declare {{ margin-top: 3.5mm; padding-top: 3mm; border-top: 1px solid #94a3b8; line-height: 1.7; font-size: 11.5px; }}
  .signature-block {{ margin-top: 3.5mm; page-break-inside: avoid; break-inside: avoid; font-size: 12.5px; }}
  .sign-row {{ min-height: 8mm; display: flex; justify-content: flex-end; align-items: center; gap: 3mm; }}
  .co-sign-row {{ min-height: 8mm; display: flex; justify-content: flex-end; align-items: flex-start; gap: 3mm; padding-top: 1mm; }}
  .sign-label {{ font-weight: 700; flex: 0 0 auto; }}
  .passenger-signs {{ display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 2mm 7mm; max-width: 82%; }}
  .passenger-sign {{ white-space: nowrap; }}
  .page2-head {{ display: grid; grid-template-columns: 1fr 1fr; gap: 3mm; margin-bottom: 3mm; }}
  .basis {{ border: 1px solid #cbd5e1; padding: 3mm; line-height: 1.6; min-height: 27mm; font-size: 11.5px; }}
  .evidence-wrap {{ height: 218mm; border: 1px solid #cbd5e1; padding: 2mm; display: flex; align-items: center; justify-content: center; overflow: hidden; background: #fff; }}
  .evidence-img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
  .evidence-empty {{ text-align: center; color: #475569; line-height: 1.8; padding: 20mm; font-size: 12px; }}
  .footer {{ position: absolute; bottom: 0; left: 0; right: 0; text-align: center; color: #64748b; font-size: 9.5px; }}
</style>
</head>
<body>
  <section class="page break">
    <h1>국내출장 여비신청서</h1>
    <div class="sub">여비정산 자동화 - 실무형 서식</div>

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
      「공무원 여비 규정」 제16조 제1항·제2항에 의하여 관계서류를 첨부하여 위와 같이 국내여비의 정산을 신청합니다.
    </div>
    <div class="signature-block">
      <div class="sign-row"><span class="sign-label">신청인</span><span>{_e(req.traveler_name or "________________")}&nbsp;&nbsp;(서명)</span></div>
      {passenger_signature_html}
    </div>
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


def _rate_won(value) -> str:
    return f"{int(value):,}원"


async def generate_regulation_pdf(
    req: TravelRequest,
    result: EstimateResponse,
    output_path: str,
    *,
    evidence_path: str | None = None,
    evidence_error: str | None = None,
) -> str:
    """Generate a simplified regulation-style domestic travel settlement PDF.

    The layout follows the official application's major sections, while
    intentionally omitting rail/ship/air/bus rows that this app does not use.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    evidence_uri = _image_data_uri(evidence_path)
    passenger_names = _passenger_names(req.passengers)
    passenger_signature_html = ""
    if passenger_names:
        passenger_items = "".join(
            f'<span class="passenger-sign">{_e(name)}&nbsp;&nbsp;(서명)</span>'
            for name in passenger_names
        )
        passenger_signature_html = (
            '<div class="co-sign-row"><span class="sign-label">동승인 성명</span>'
            f'<div class="passenger-signs">{passenger_items}</div></div>'
        )

    destination_name = result.resolved_destination_name or req.destination
    origin = _place(result.resolved_origin_name, result.resolved_origin_address, req.origin)
    destination = _place(
        result.resolved_destination_name,
        result.resolved_destination_address,
        req.destination,
    )
    price_date = result.fuel_price_date.isoformat() if result.fuel_price_date else "-"
    application_date = datetime.now(ZoneInfo("Asia/Seoul")).date()
    application_date_ko = (
        f"{application_date.year}년 {application_date.month}월 {application_date.day}일"
    )

    if evidence_uri:
        evidence_block = f'<img class="evidence-img" src="{evidence_uri}" alt="오피넷 증빙">'
        evidence_status = "오피넷 공식 화면 확인 완료"
    else:
        reason = evidence_error or "해당 차량은 현재 오피넷 화면 증빙 대상이 아닙니다."
        evidence_block = (
            f'<div class="evidence-empty"><b>증빙 이미지 미첨부</b><br>{_e(reason)}</div>'
        )
        evidence_status = reason

    body = f"""
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 8mm 9mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "Noto Sans CJK KR", "Noto Sans KR", "Malgun Gothic", sans-serif;
    color: #111;
    font-size: 11.2px;
  }}
  .page {{ min-height: 281mm; position: relative; }}
  .page.break {{ page-break-after: always; }}
  .form-note {{ font-size: 9.5px; margin: 0 0 1.5mm; color: #555; }}
  h1 {{
    margin: 0 0 3mm;
    text-align: center;
    font-size: 22px;
    letter-spacing: .12em;
  }}
  table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
  th, td {{
    border: 1px solid #222;
    padding: 1.45mm 1.6mm;
    vertical-align: middle;
    line-height: 1.38;
  }}
  th {{ text-align: center; font-weight: 700; background: #fafafa; }}
  td {{ word-break: keep-all; overflow-wrap: anywhere; }}
  .top th {{ width: 10.5%; }}
  .center {{ text-align: center; }}
  .money {{ text-align: right; font-weight: 700; white-space: nowrap; }}
  .basis {{ color: #333; font-size: 10.2px; }}
  .sum-label {{ font-size: 13px; letter-spacing: .16em; }}
  .sum-money {{ text-align: right; font-size: 15px; font-weight: 800; }}
  .declaration {{
    margin-top: 4mm;
    line-height: 1.75;
    font-size: 11.2px;
    text-align: left;
  }}
  .attachment {{ margin-top: 1.5mm; font-size: 10.7px; }}
  .application-date {{ margin-top: 3.5mm; text-align: center; font-size: 11.5px; }}
  .signature-block {{
    margin-top: 2.5mm;
    page-break-inside: avoid;
    break-inside: avoid;
    font-size: 12px;
  }}
  .sign-row {{
    min-height: 7mm;
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 3mm;
  }}
  .co-sign-row {{
    min-height: 7mm;
    display: flex;
    justify-content: flex-end;
    align-items: flex-start;
    gap: 3mm;
    padding-top: .5mm;
  }}
  .sign-label {{ font-weight: 700; flex: 0 0 auto; }}
  .passenger-signs {{
    display: flex;
    justify-content: flex-end;
    flex-wrap: wrap;
    gap: 1.5mm 6mm;
    max-width: 82%;
  }}
  .passenger-sign {{ white-space: nowrap; }}
  .page2-title {{ margin-bottom: 3mm; }}
  .page2-head {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 3mm;
    margin-bottom: 3mm;
  }}
  .evidence-basis {{
    border: 1px solid #777;
    padding: 3mm;
    min-height: 28mm;
    line-height: 1.55;
    font-size: 10.8px;
  }}
  .evidence-wrap {{
    height: 219mm;
    border: 1px solid #999;
    padding: 2mm;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    background: #fff;
  }}
  .evidence-img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
  .evidence-empty {{
    text-align: center;
    color: #555;
    line-height: 1.8;
    padding: 18mm;
    font-size: 11.5px;
  }}
  .footer {{
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    text-align: center;
    color: #777;
    font-size: 9px;
  }}
</style>
</head>
<body>
  <section class="page break">
    <div class="form-note">(여비 신청 서식 · 자동차운임 중심 간소형)</div>
    <h1>국내출장 여비 신청서</h1>

    <table class="top">
      <colgroup>
        <col style="width:10%">
        <col style="width:23%">
        <col style="width:12%">
        <col style="width:22%">
        <col style="width:10%">
        <col style="width:23%">
      </colgroup>
      <tr>
        <th>소속</th><td>{_e(req.affiliation)}</td>
        <th>직급(직위)</th><td>{_e(req.position)}</td>
        <th>성명</th><td>{_e(req.traveler_name)}</td>
      </tr>
      <tr>
        <th>출장일정</th><td colspan="2">{_e(_period(req))}</td>
        <th>출장지</th><td colspan="2">{_e(destination_name)}</td>
      </tr>
      <tr>
        <th>출장목적</th><td colspan="5">{_e(req.purpose)}</td>
      </tr>
    </table>

    <table style="margin-top:2.5mm">
      <colgroup>
        <col style="width:12%">
        <col style="width:13%">
        <col style="width:17%">
        <col style="width:12%">
        <col style="width:15%">
        <col style="width:14%">
        <col style="width:17%">
      </colgroup>
      <tr>
        <th rowspan="2">일비</th>
        <th>단가</th><td class="center">{_rate_won(DAILY_ALLOWANCE_RATE)}</td>
        <th>일수</th><td class="center">{result.trip_days}일</td>
        <th>산출액</th><td class="money">{_won(result.daily_allowance)}</td>
      </tr>
      <tr>
        <th>산출근거</th><td colspan="5" class="basis">{_e(result.daily_note)}</td>
      </tr>
      <tr>
        <th rowspan="2">식비</th>
        <th>단가</th><td class="center">{_rate_won(MEAL_ALLOWANCE_RATE)}</td>
        <th>일수</th><td class="center">{result.trip_days}일</td>
        <th>산출액</th><td class="money">{_won(result.meal_allowance)}</td>
      </tr>
      <tr>
        <th>산출근거</th><td colspan="5" class="basis">{_e(result.meal_note)}</td>
      </tr>

      <tr>
        <th rowspan="3">자동차<br>운임</th>
        <th>연료비</th>
        <td colspan="4" class="basis">{_e(result.calculation_formula)}</td>
        <td class="money">{_won(result.estimated_transport_cost)}</td>
      </tr>
      <tr>
        <th>통행료</th>
        <td colspan="4" class="basis">직접 입력</td>
        <td class="money">{_won(result.toll_fee)}</td>
      </tr>
      <tr>
        <th>주차료</th>
        <td colspan="4" class="basis">직접 입력</td>
        <td class="money">{_won(result.parking_fee)}</td>
      </tr>

      <tr>
        <th>숙박비</th>
        <th>숙박시설</th>
        <td colspan="4" class="basis">직접 입력</td>
        <td class="money">{_won(result.lodging_fee)}</td>
      </tr>

      <tr>
        <th colspan="6" class="sum-label">합&nbsp;&nbsp;&nbsp;&nbsp;계</th>
        <td class="sum-money">{_won(result.total_expense)}</td>
      </tr>
    </table>

    <table style="margin-top:2.5mm">
      <colgroup>
        <col style="width:14%">
        <col style="width:36%">
        <col style="width:14%">
        <col style="width:36%">
      </colgroup>
      <tr>
        <th>출발지</th><td>{_e(origin)}</td>
        <th>출장지 확인</th><td>{_e(destination)}</td>
      </tr>
      <tr>
        <th>거리 기준</th><td>{_e(result.distance_source)}</td>
        <th>편도거리</th><td>{_num(result.one_way_distance_km)} km</td>
      </tr>
      <tr>
        <th>유가 기준일</th><td>{_e(price_date)}</td>
        <th>적용단가</th><td>{_won(result.energy_price)}</td>
      </tr>
    </table>

    <div class="declaration">
      「공무원여비규정」 제16조 제1항 및 제2항의 규정에 의하여 관계서류를 첨부하여 위와 같이 여비의 정산을 신청합니다.
    </div>
    <div class="attachment">첨 부 : 산출근거 및 증빙자료 1부.</div>
    <div class="application-date">{_e(application_date_ko)}</div>

    <div class="signature-block">
      <div class="sign-row"><span class="sign-label">신청인 성명</span><span>{_e(req.traveler_name or "________________")}&nbsp;&nbsp;(서명)</span></div>
      {passenger_signature_html}
    </div>
    <div class="footer">1 / 2 · 규정서식 간소형</div>
  </section>

  <section class="page">
    <h1 class="page2-title">산출근거 및 증빙</h1>
    <div class="page2-head">
      <div class="evidence-basis">
        <b>거리 산출근거</b><br>
        {_e(result.distance_source)}<br>
        {_e(origin)} → {_e(destination)}<br>
        편도 {_num(result.one_way_distance_km)} km / 적용거리 {_num(result.transport_distance_km)} km
      </div>
      <div class="evidence-basis">
        <b>유가 및 자동차운임</b><br>
        기준일 {_e(price_date)} / {_won(result.energy_price)}<br>
        {_e(result.calculation_formula)}
      </div>
    </div>
    <div class="basis" style="margin-bottom:2mm">증빙상태: {_e(evidence_status)}</div>
    <div class="evidence-wrap">{evidence_block}</div>
    <div class="footer">2 / 2 · 규정서식 간소형</div>
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
