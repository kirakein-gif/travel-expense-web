from __future__ import annotations

import base64
import html
import re
from pathlib import Path
from datetime import datetime, timedelta
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


def _unit_price_text(result: EstimateResponse) -> str:
    if result.energy_price is None:
        return "-"
    unit = "원/L"
    if result.efficiency_unit == "km/kWh":
        unit = "원/kWh"
    elif result.efficiency_unit == "km/kg":
        unit = "원/kg"
    return f"{float(result.energy_price):,.2f}{unit}"


def _evidence_reason(result: EstimateResponse, evidence_error: str | None) -> str:
    if evidence_error:
        return evidence_error
    if result.evidence_status == "official_ev_rate":
        return f"전기차 공공 충전 기준단가 자동 적용 · {result.price_source or '-'}"
    if result.evidence_status == "manual_hydrogen_price":
        return "수소 충전단가 사용자 직접입력 · 별도 오피넷 증빙 대상 아님"
    if result.evidence_status == "no_vehicle":
        return "차량 없음 · 유가조회 및 단가 증빙 불필요"
    return "해당 차량은 현재 오피넷 화면 증빙 대상이 아닙니다."


def _period(req: TravelRequest) -> str:
    end = req.end_date or req.travel_date
    if end == req.travel_date:
        return req.travel_date.isoformat()
    return f"{req.travel_date.isoformat()} ~ {end.isoformat()}"


def _trip_type(req: TravelRequest) -> str:
    if req.trip_type != "training":
        return "일반출장"
    return "교육훈련(합숙)" if req.training_boarding else "교육훈련(비합숙)"


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


def _toll_evidence_html(paths: list[str] | None) -> str:
    uris = [_image_data_uri(path) for path in (paths or [])]
    uris = [uri for uri in uris if uri]
    if not uris:
        return ""
    count_class = f" count-{min(len(uris), 4)}"
    images = "".join(
        f'<div class="toll-evidence-item"><img class="toll-evidence-img" src="{uri}" alt="통행료 증빙"></div>'
        for uri in uris[:4]
    )
    return (
        '<section class="toll-evidence-section">'
        '<div class="evidence-title">통행료 증빙</div>'
        f'<div class="toll-evidence-grid{count_class}">{images}</div>'
        '</section>'
    )


async def generate_estimate_pdf(
    req: TravelRequest,
    result: EstimateResponse,
    output_path: str,
    *,
    evidence_path: str | None = None,
    evidence_error: str | None = None,
    toll_evidence_paths: list[str] | None = None,
) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    evidence_uri = _image_data_uri(evidence_path)
    toll_evidence_html = _toll_evidence_html(toll_evidence_paths)
    evidence_page_class = " with-toll" if toll_evidence_html else ""
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
        reason = _evidence_reason(result, evidence_error)
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
  .passenger-sign {{ white-space: nowrap; font-size: 14px; }}
  .page2-head {{ display: grid; grid-template-columns: 1fr 1fr; gap: 3mm; margin-bottom: 3mm; }}
  .basis {{ border: 1px solid #cbd5e1; padding: 3mm; line-height: 1.6; min-height: 27mm; font-size: 11.5px; }}
  .evidence-wrap {{ height: 218mm; border: 1px solid #cbd5e1; padding: 2mm; display: flex; align-items: center; justify-content: center; overflow: hidden; background: #fff; }}
  .evidence-img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
  .evidence-empty {{ text-align: center; color: #475569; line-height: 1.8; padding: 20mm; font-size: 12px; }}
  .evidence-page.with-toll .evidence-wrap {{ height: 112mm; }}
  .evidence-title {{ font-size: 11.5px; font-weight: 800; margin: 2mm 0 1mm; color:#334155; }}
  .toll-evidence-section {{ margin-top: 2.5mm; }}
  .toll-evidence-grid {{ height: 82mm; display:grid; grid-template-columns:1fr; gap:2mm; }}
  .toll-evidence-grid.count-2 {{ grid-template-columns:1fr 1fr; }}
  .toll-evidence-grid.count-3,.toll-evidence-grid.count-4 {{ grid-template-columns:1fr 1fr; grid-template-rows:1fr 1fr; }}
  .toll-evidence-item {{ min-width:0; min-height:0; border:1px solid #cbd5e1; padding:1mm; display:flex; align-items:center; justify-content:center; overflow:hidden; background:#fff; }}
  .toll-evidence-img {{ max-width:100%; max-height:100%; object-fit:contain; }}
  .footer {{ position: absolute; bottom: 0; left: 0; right: 0; text-align: center; color: #64748b; font-size: 9.5px; }}
</style>
</head>
<body>
  <section class="page break">
    <h1>국내출장 여비신청서</h1>
    <div class="sub">딸깍 여비정산서 - 실무형 서식</div>

    <table>
      <tr><th class="label">신청인</th><td colspan="3">{_e(applicant)}</td></tr>
      <tr><th>출장기간</th><td>{_e(_period(req))}</td><th>출장유형</th><td>{_e(_trip_type(req))}</td></tr>
      <tr><th>출장목적</th><td colspan="3">{_e(req.purpose)}</td></tr>
      <tr><th>출발지</th><td colspan="3">{_e(origin)}</td></tr>
      <tr><th>출장지</th><td colspan="3">{_e(destination)}</td></tr>
      <tr><th>거리기준</th><td>{_e(result.distance_source)}</td><th>편도거리</th><td>{_num(result.one_way_distance_km)} km</td></tr>
      <tr><th>차량</th><td>{_e(vehicle)}</td><th>연비/전비</th><td>{_e(eff)}</td></tr>
      <tr><th>단가 기준일</th><td>{_e(price_date)}</td><th>적용단가</th><td>{_e(_unit_price_text(result))}</td></tr>
    </table>

    <div class="section">
      <h2>여비 산출내역</h2>
      <table>
        <tr><th>항목</th><th>산출근거</th><th style="width:24%">금액</th></tr>
        <tr><td>운임</td><td>{_e(result.calculation_formula)}</td><td class="money">{_won(result.estimated_transport_cost)}</td></tr>
        <tr><td>일비</td><td>{_e(result.daily_note)}</td><td class="money">{_won(result.daily_allowance)}</td></tr>
        <tr><td>식비</td><td>{_e(result.meal_note)}</td><td class="money">{_won(result.meal_allowance)}</td></tr>
        <tr><td>통행료</td><td>직접 입력</td><td class="money">{_won(result.toll_fee)}</td></tr>
        <tr><td>주차료</td><td>직접 입력</td><td class="money">{_won(result.parking_fee)}</td></tr>
        <tr><td>숙박비</td><td>직접 입력</td><td class="money">{_won(result.lodging_fee)}</td></tr>
        <tr><th colspan="2">합계</th><td class="total">{_won(result.total_expense)}</td></tr>
      </table>
    </div>

    <div class="section">
      <h2>운임 계산 확인</h2>
      <div class="formula">
        편도 기준거리 {_num(result.one_way_distance_km)} km / 왕복횟수 {round_trips}<br>
        {_e(result.calculation_formula)}<br>
        <span class="small">거리 근거: {_e(result.distance_source)} / 단가 출처: {_e(result.price_source)}</span>
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

  <section class="page evidence-page{evidence_page_class}">
    <h1>산출근거 및 증빙</h1>
    <div class="page2-head">
      <div class="basis">
        <b>거리 산출근거</b><br>
        {_e(result.distance_source)}<br>
        편도 {_num(result.one_way_distance_km)} km / 적용거리 {_num(result.transport_distance_km)} km
      </div>
      <div class="basis">
        <b>단가 및 운임</b><br>
        {_e(price_date)} / {_e(_unit_price_text(result))}<br>
        {_e(result.calculation_formula)}
      </div>
    </div>
    <div class="small" style="margin-bottom:2mm">증빙상태: {_e(evidence_status)}</div>
    <div class="evidence-wrap">{evidence_block}</div>
    {toll_evidence_html}
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


PROVINCE_SHORT_NAMES = {
    "서울특별시": "서울", "서울": "서울",
    "부산광역시": "부산", "부산": "부산",
    "대구광역시": "대구", "대구": "대구",
    "인천광역시": "인천", "인천": "인천",
    "광주광역시": "광주", "광주": "광주",
    "대전광역시": "대전", "대전": "대전",
    "울산광역시": "울산", "울산": "울산",
    "세종특별자치시": "세종", "세종시": "세종", "세종": "세종",
    "경기도": "경기", "경기": "경기",
    "강원특별자치도": "강원", "강원도": "강원", "강원": "강원",
    "충청북도": "충북", "충북": "충북",
    "충청남도": "충남", "충남": "충남",
    "전북특별자치도": "전북", "전라북도": "전북", "전북": "전북",
    "전라남도": "전남", "전남": "전남",
    "경상북도": "경북", "경북": "경북",
    "경상남도": "경남", "경남": "경남",
    "제주특별자치도": "제주", "제주도": "제주", "제주": "제주",
}


def _short_province(value: str | None) -> str:
    text = (value or "").strip()
    if text in PROVINCE_SHORT_NAMES:
        return PROVINCE_SHORT_NAMES[text]
    for suffix in ("특별자치도", "특별자치시", "특별시", "광역시", "도"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text or "-"


def _short_local_unit(province: str | None, sigungu: str | None) -> str:
    province_short = _short_province(province)
    parts = [p for p in (sigungu or "").split() if p]

    metro = province_short in {"서울", "부산", "대구", "인천", "광주", "대전", "울산"}
    target = ""
    if metro:
        target = next((p for p in parts if p.endswith(("구", "군"))), parts[0] if parts else province_short)
    else:
        target = next((p for p in parts if p.endswith(("시", "군"))), parts[0] if parts else province_short)

    if target.endswith(("시", "군", "구")) and len(target) > 1:
        target = target[:-1]
    return target or province_short


def _movement_place_labels(result: EstimateResponse) -> tuple[str, str]:
    origin_province = _short_province(result.origin_province)
    destination_province = _short_province(result.province)

    if origin_province == destination_province:
        origin_label = _short_local_unit(result.origin_province, result.origin_sigungu)
        destination_label = _short_local_unit(result.province, result.sigungu)
    else:
        origin_label = origin_province
        destination_label = destination_province

    # 내포는 홍성·예산 행정구역과 별개로 고정거리표의 특수 기준점이다.
    # 실제 거리 판정 결과가 내포 특수 목적지라면 운임 이동내역에도
    # '홍성'/'예산' 대신 '내포'라고 표시해 거리 기준과 문서 표기를 맞춘다.
    if (result.origin_support_office or "").strip() == "내포":
        origin_label = "내포"
    if (result.destination_support_office or "").strip() == "내포":
        destination_label = "내포"

    return origin_label, destination_label


def _regulation_movement_rows(
    req: TravelRequest,
    result: EstimateResponse,
) -> list[dict]:
    """Build one row per actual one-way movement for the regulation-style form."""
    start = req.travel_date
    end = req.end_date or start
    origin_name, destination_name = _movement_place_labels(result)
    one_way_km = float(result.one_way_distance_km or 0)

    unit_price = float(result.energy_price) if result.energy_price is not None else None
    efficiency = float(result.effective_efficiency) if result.effective_efficiency else None
    efficiency_unit = result.efficiency_unit or ""

    if efficiency_unit == "km/kWh":
        price_unit = "원/kWh"
    elif efficiency_unit == "km/kg":
        price_unit = "원/kg"
    else:
        price_unit = "원/L"

    if unit_price is not None and efficiency:
        raw_leg_cost = one_way_km * unit_price / efficiency
        calculation_basis = (
            f"{one_way_km:,.1f}km × {unit_price:,.2f}{price_unit} ÷ "
            f"{efficiency:g}{efficiency_unit}"
        )
    else:
        raw_leg_cost = 0
        calculation_basis = result.calculation_formula or "운임 미지급"

    rows: list[dict] = []

    def add(day_label: str, departure: str, arrival: str):
        rows.append(
            {
                "date": day_label,
                "departure": departure,
                "arrival": arrival,
                "calculation_basis": calculation_basis,
                "fuel_cost": raw_leg_cost,
            }
        )

    if req.trip_type != "training":
        if req.round_trip:
            if end > start and req.normal_stay_mode == "residential":
                add(start.isoformat(), origin_name, destination_name)
                add(end.isoformat(), destination_name, origin_name)
            else:
                current = start
                while current <= end:
                    day = current.isoformat()
                    add(day, origin_name, destination_name)
                    add(day, destination_name, origin_name)
                    current += timedelta(days=1)
        else:
            add(start.isoformat(), origin_name, destination_name)
        return rows

    # 2026 교육훈련여비 지급기준상 근무지외 교육훈련 운임은
    # 합숙·비합숙 모두 교육기간 전체 왕복 1회로 표시합니다.
    add(start.isoformat(), origin_name, destination_name)
    add(end.isoformat(), destination_name, origin_name)
    return rows


def _won_exact(value: int | float | None) -> str:
    if value is None:
        return "-"
    number = float(value)
    if number.is_integer():
        return f"{int(number):,}원"
    return f"{number:,.1f}원"


async def generate_regulation_pdf(
    req: TravelRequest,
    result: EstimateResponse,
    output_path: str,
    *,
    evidence_path: str | None = None,
    evidence_error: str | None = None,
    toll_evidence_paths: list[str] | None = None,
) -> str:
    """Generate a simplified regulation-style domestic travel settlement PDF."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    evidence_uri = _image_data_uri(evidence_path)
    toll_evidence_html = _toll_evidence_html(toll_evidence_paths)
    evidence_page_class = " with-toll" if toll_evidence_html else ""
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
    origin_address = result.resolved_origin_address or req.origin
    destination_address = result.resolved_destination_address or req.destination
    price_date = result.fuel_price_date.isoformat() if result.fuel_price_date else "-"
    vehicle = result.vehicle_label or req.vehicle_type
    efficiency_text = (
        f"{result.effective_efficiency:g} {result.efficiency_unit}"
        if result.effective_efficiency and result.efficiency_unit
        else "-"
    )
    application_date = datetime.now(ZoneInfo("Asia/Seoul")).date()
    application_date_ko = (
        f"{application_date.year}년 {application_date.month}월 {application_date.day}일"
    )

    movement_rows = _regulation_movement_rows(req, result)
    movement_html = "".join(
        "<tr>"
        f'<td>{_e(row["date"])}</td>'
        f'<td>{_e(row["departure"])}</td>'
        f'<td>{_e(row["arrival"])}</td>'
        f'<td class="calc-basis">{_e(row["calculation_basis"])}</td>'
        f'<td class="money">{_won(row["fuel_cost"])}</td>'
        "</tr>"
        for row in movement_rows
    )
    movement_count = len(movement_rows)
    dense_class = " dense" if movement_count > 8 else ""
    compact_page_class = " compact-page" if movement_count >= 6 or len(passenger_names) >= 2 else ""
    if result.efficiency_unit == "km/kWh":
        segment_cost_label = "구간 충전비"
        energy_cost_label = "충전비"
        energy_total_label = "충전비 합계"
    elif result.efficiency_unit == "km/kg":
        segment_cost_label = "구간 수소연료비"
        energy_cost_label = "수소연료비"
        energy_total_label = "수소연료비 합계"
    else:
        segment_cost_label = "구간 연료비"
        energy_cost_label = "연료비"
        energy_total_label = "연료비 합계"

    if evidence_uri:
        evidence_block = f'<img class="evidence-img" src="{evidence_uri}" alt="오피넷 증빙">'
        evidence_status = "오피넷 공식 화면 확인 완료"
    else:
        reason = _evidence_reason(result, evidence_error)
        evidence_block = (
            f'<div class="evidence-empty"><b>증빙 이미지 미첨부</b><br>{_e(reason)}</div>'
        )
        evidence_status = reason

    if result.evidence_status == "official_ev_rate":
        evidence_detail_html = (
            '<div class="compact-evidence">'
            '<b>공식 기준단가 자동 적용</b><br>'
            f'무공해차 통합누리집 공공 급속충전요금 이력 기준 · '
            f'{_e(price_date)} / {_e(_unit_price_text(result))}<br>'
            f'<span class="compact-source">{_e(result.price_source)}</span>'
            '</div>'
        )
    elif result.evidence_status == "manual_hydrogen_price":
        evidence_detail_html = (
            '<div class="compact-evidence">'
            '<b>수소단가 직접입력</b><br>'
            f'적용단가 {_e(_unit_price_text(result))} · '
            '지역별 가격 편차를 고려한 사용자 직접입력값<br>'
            '<span class="compact-source">별도 오피넷 화면 증빙 대상 아님</span>'
            '</div>'
        )
    elif result.evidence_status in {"not_required", "no_vehicle"}:
        evidence_detail_html = (
            '<div class="compact-evidence">'
            '<b>별도 단가 증빙 불필요</b><br>'
            f'{_e(result.price_source)}<br>'
            f'<span class="compact-source">{_e(result.calculation_formula)}</span>'
            '</div>'
        )
    else:
        evidence_detail_html = (
            f'<div class="basis" style="margin-bottom:2mm">'
            f'증빙상태: {_e(evidence_status)}</div>'
            f'<div class="evidence-wrap">{evidence_block}</div>'
        )

    body = f"""
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 9mm 10mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "Noto Sans CJK KR", "Noto Sans KR", "Malgun Gothic", sans-serif;
    color: #111;
    font-size: 12.4px;
  }}
  .page {{ min-height: 279mm; position: relative; }}
  .page.break {{ page-break-after: always; }}
  .form-note {{ font-size: 10.5px; margin: 0 0 2mm; color: #555; }}
  h1 {{
    margin: 0 0 4mm;
    text-align: center;
    font-size: 24px;
    letter-spacing: .11em;
  }}
  table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
  th, td {{
    border: 1px solid #222;
    padding: 2.05mm 1.8mm;
    vertical-align: middle;
    line-height: 1.42;
    text-align: center;
  }}
  th {{ font-weight: 750; background: #fafafa; }}
  td {{ word-break: keep-all; overflow-wrap: anywhere; }}
  .top td, .info td {{ font-weight: 500; }}
  .section-title {{
    margin: 4mm 0 1.5mm;
    font-size: 13.5px;
    font-weight: 800;
  }}
  .move-table th {{ background: #f5f5f5; }}
  .move-table td {{ padding-top: 1.75mm; padding-bottom: 1.75mm; }}
  .move-table.dense td, .move-table.dense th {{
    padding-top: 1.15mm;
    padding-bottom: 1.15mm;
    font-size: 11.2px;
  }}
  .money {{ text-align: center; font-weight: 750; white-space: nowrap; }}
  .basis {{ color: #333; font-size: 11.6px; }}
  .sum-label {{ font-size: 14px; letter-spacing: .16em; }}
  .sum-money {{ text-align: center; font-size: 16px; font-weight: 850; }}
  .declaration {{
    margin-top: 5mm;
    line-height: 1.8;
    font-size: 12.3px;
    text-align: center;
  }}
  .attachment {{ margin-top: 2mm; font-size: 11.5px; text-align: center; }}
  .application-date {{
    margin-top: 4mm;
    text-align: center;
    font-size: 14px;
    font-weight: 650;
  }}
  .signature-block {{
    margin-top: 3.2mm;
    page-break-inside: avoid;
    break-inside: avoid;
    font-size: 14px;
  }}
  .sign-row {{
    min-height: 8mm;
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 3mm;
  }}
  .co-sign-row {{
    min-height: 8mm;
    display: flex;
    justify-content: flex-end;
    align-items: flex-start;
    gap: 3mm;
    margin-top: 1.8mm;
    padding-top: .5mm;
  }}
  .sign-label {{ font-weight: 800; flex: 0 0 auto; font-size: 14.2px; }}
  .passenger-signs {{
    display: flex;
    justify-content: flex-end;
    flex-wrap: wrap;
    gap: 1.8mm 7mm;
    max-width: 82%;
  }}
  .passenger-sign {{ white-space: nowrap; }}

  /* 3일 교육훈련·동승자 등 자주 쓰는 경우에도 1쪽 안에 서명까지 유지 */
  .compact-page h1 {{ margin-bottom: 2.5mm; font-size: 23px; }}
  .compact-page .form-note {{ margin-bottom: 1mm; }}
  .compact-page th, .compact-page td {{
    padding-top: 1.35mm;
    padding-bottom: 1.35mm;
    line-height: 1.32;
  }}
  .compact-page .section-title {{ margin: 2.4mm 0 .9mm; }}
  .compact-page .move-table {{ margin-top: 1.2mm !important; }}
  .compact-page .move-table td,
  .compact-page .move-table th {{
    padding-top: .95mm;
    padding-bottom: .95mm;
  }}
  .compact-page .calc-basis {{ font-size: 10.9px; }}
  .compact-page .move-note {{
    margin-top: .6mm;
    font-size: 9.8px;
    line-height: 1.25;
  }}
  .compact-page .basis {{ font-size: 11px; }}
  .compact-page .declaration {{
    margin-top: 2.2mm;
    line-height: 1.5;
    font-size: 11.4px;
  }}
  .compact-page .attachment {{
    margin-top: .8mm;
    font-size: 10.7px;
  }}
  .compact-page .application-date {{
    margin-top: 1.1mm;
    font-size: 12.8px;
    font-weight: 650;
  }}
  .compact-page .signature-block {{
    margin-top: .8mm;
    font-size: 12.8px;
  }}
  .compact-page .sign-row,
  .compact-page .co-sign-row {{
    min-height: 4.2mm;
  }}
  .compact-page .co-sign-row {{ margin-top: .9mm; padding-top: 0; }}
  .compact-page .sign-label {{ font-size: 13px; }}
  .compact-page .passenger-sign {{ font-size: 12.8px; }}
  .compact-page .passenger-signs {{
    gap: .5mm 4mm;
    max-width: 86%;
  }}

  .page2-title {{ margin-bottom: 4mm; }}
  .page2-head {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 3mm;
    margin-bottom: 3mm;
  }}
  .evidence-basis {{
    border: 1px solid #777;
    padding: 3.5mm;
    min-height: 30mm;
    line-height: 1.6;
    font-size: 12px;
  }}
  .evidence-wrap {{
    height: 210mm;
    border: 1px solid #999;
    padding: 2mm;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    background: #fff;
  }}
  .evidence-img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
  .evidence-page.with-toll .evidence-wrap {{ height: 110mm; }}
  .evidence-title {{ font-size: 11.5px; font-weight: 800; margin: 2mm 0 1mm; color:#333; }}
  .toll-evidence-section {{ margin-top: 2.5mm; }}
  .toll-evidence-grid {{ height: 82mm; display:grid; grid-template-columns:1fr; gap:2mm; }}
  .toll-evidence-grid.count-2 {{ grid-template-columns:1fr 1fr; }}
  .toll-evidence-grid.count-3,.toll-evidence-grid.count-4 {{ grid-template-columns:1fr 1fr; grid-template-rows:1fr 1fr; }}
  .toll-evidence-item {{ min-width:0; min-height:0; border:1px solid #aaa; padding:1mm; display:flex; align-items:center; justify-content:center; overflow:hidden; background:#fff; }}
  .toll-evidence-img {{ max-width:100%; max-height:100%; object-fit:contain; }}
  .evidence-empty {{
    text-align: center;
    color: #555;
    line-height: 1.8;
    padding: 18mm;
    font-size: 12.2px;
  }}
  .compact-evidence {{
    border: 1px solid #999;
    background: #fafafa;
    padding: 4mm 5mm;
    line-height: 1.65;
    font-size: 12px;
    color: #222;
  }}
  .compact-evidence b {{
    font-size: 12.8px;
  }}
  .compact-source {{
    color: #555;
    font-size: 11.3px;
  }}
  .footer {{
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    text-align: center;
    color: #777;
    font-size: 9.5px;
  }}
</style>
</head>
<body>
  <section class="page break{compact_page_class}">
    <div class="form-note">(여비 신청 서식 · 운임 중심 간소형)</div>
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

    <div class="section-title">출장 및 이동내역</div>
    <table class="info">
      <colgroup>
        <col style="width:14%"><col style="width:36%">
        <col style="width:14%"><col style="width:36%">
      </colgroup>
      <tr>
        <th>출발주소</th><td>{_e(origin_address)}</td>
        <th>도착주소</th><td>{_e(destination_address)}</td>
      </tr>
      <tr>
        <th>거리 기준</th><td>{_e(result.distance_source)}</td>
        <th>편도거리</th><td>{_num(result.one_way_distance_km)} km</td>
      </tr>
      <tr>
        <th>차량유형</th><td>{_e(vehicle)}</td>
        <th>연비/전비</th><td>{_e(efficiency_text)}</td>
      </tr>
      <tr>
        <th>단가 기준일</th><td>{_e(price_date)}</td>
        <th>적용단가</th><td>{_e(_unit_price_text(result))}</td>
      </tr>
    </table>

    <table class="move-table{dense_class}" style="margin-top:2mm">
      <colgroup>
        <col style="width:15%">
        <col style="width:18%">
        <col style="width:18%">
        <col style="width:33%">
        <col style="width:16%">
      </colgroup>
      <tr>
        <th>일자</th>
        <th>출발지</th>
        <th>도착지</th>
        <th>산출근거</th>
        <th>{_e(segment_cost_label)}</th>
      </tr>
      {movement_html}
      <tr>
        <th colspan="4">{_e(energy_total_label)}</th>
        <td class="money">{_won(result.estimated_transport_cost)}</td>
      </tr>
    </table>
    <div class="move-note">※ 구간 비용은 산식 확인용이며, 최종 운임은 왕복 1회분 산출 후 10원 미만 절사하여 출장일수·횟수를 반영합니다.</div>

    <div class="section-title">여비 지급내역</div>
    <table class="money-table">
      <colgroup>
        <col style="width:13%">
        <col style="width:14%">
        <col style="width:19%">
        <col style="width:12%">
        <col style="width:16%">
        <col style="width:12%">
        <col style="width:14%">
      </colgroup>
      <tr>
        <th rowspan="2">일비</th>
        <th>단가</th><td>{_rate_won(DAILY_ALLOWANCE_RATE)}</td>
        <th>일수</th><td>{result.trip_days}일</td>
        <th>산출액</th><td class="money">{_won(result.daily_allowance)}</td>
      </tr>
      <tr>
        <th>산출근거</th><td colspan="5" class="basis">{_e(result.daily_note)}</td>
      </tr>
      <tr>
        <th rowspan="2">식비</th>
        <th>단가</th><td>{_rate_won(MEAL_ALLOWANCE_RATE)}</td>
        <th>일수</th><td>{result.trip_days}일</td>
        <th>산출액</th><td class="money">{_won(result.meal_allowance)}</td>
      </tr>
      <tr>
        <th>산출근거</th><td colspan="5" class="basis">{_e(result.meal_note)}</td>
      </tr>
      <tr>
        <th>운임</th>
        <th>{_e(energy_cost_label)}</th><td class="money">{_won(result.estimated_transport_cost)}</td>
        <th>통행료</th><td class="money">{_won(result.toll_fee)}</td>
        <th>주차료</th><td class="money">{_won(result.parking_fee)}</td>
      </tr>
      <tr>
        <th>숙박비</th>
        <td colspan="5">숙박시설 · 직접 입력</td>
        <td class="money">{_won(result.lodging_fee)}</td>
      </tr>
      <tr>
        <th colspan="6" class="sum-label">합&nbsp;&nbsp;&nbsp;&nbsp;계</th>
        <td class="sum-money">{_won(result.total_expense)}</td>
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

  <section class="page evidence-page{evidence_page_class}">
    <h1 class="page2-title">산출근거 및 증빙</h1>
    <div class="page2-head">
      <div class="evidence-basis">
        <b>거리 산출근거</b><br>
        {_e(result.distance_source)}<br>
        {_e(origin)} → {_e(destination)}<br>
        편도 {_num(result.one_way_distance_km)} km / 적용거리 {_num(result.transport_distance_km)} km
      </div>
      <div class="evidence-basis">
        <b>단가 및 운임</b><br>
        차량 {_e(vehicle)} / 연비·전비 {_e(efficiency_text)}<br>
        기준일 {_e(price_date)} / {_e(_unit_price_text(result))}<br>
        {_e(result.price_source)}<br>
        {_e(result.calculation_formula)}
      </div>
    </div>
    {evidence_detail_html}
    {toll_evidence_html}
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
