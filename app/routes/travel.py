import os
import shutil
import tempfile

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.models import (
    DistanceResponse,
    EstimateResponse,
    EvidenceRequest,
    PriceRequest,
    PriceResponse,
    TravelRequest,
)
from app.services.opinet_api_service import check_opinet_api_status
from app.services.opinet_evidence_service import generate_opinet_evidence
from app.services.pdf_service import generate_estimate_pdf, generate_regulation_pdf
from app.services.travel_service import estimate_travel, resolve_distance, resolve_price
from app.services.travel_pdf_import import parse_travel_pdf

router = APIRouter(tags=["travel"])


def _evidence_vehicle(req: TravelRequest) -> str | None:
    if req.vehicle_type in {"gasoline", "diesel", "lpg"}:
        return req.vehicle_type
    if req.vehicle_type == "hybrid":
        return "gasoline"
    if req.vehicle_type == "phev" and req.phev_energy_source == "gasoline":
        return "gasoline"
    return None


@router.post("/import-travel-pdf")
async def import_travel_pdf(file: UploadFile = File(...)):
    filename = file.filename or "출장신청서.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드할 수 있습니다.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF 파일은 15MB 이하만 업로드할 수 있습니다.")
    try:
        return parse_travel_pdf(data, filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"출장신청서 분석 실패: {e}")


@router.get("/opinet-status")
async def opinet_status():
    return await check_opinet_api_status()


@router.post("/distance", response_model=DistanceResponse)
async def distance(req: TravelRequest):
    try:
        return await resolve_distance(req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/price", response_model=PriceResponse)
async def price(req: PriceRequest):
    try:
        return await resolve_price(req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/opinet-evidence.png")
async def opinet_evidence(req: EvidenceRequest, background_tasks: BackgroundTasks):
    evidence_dir = tempfile.mkdtemp(prefix="opinet_evidence_")
    try:
        output_path = await generate_opinet_evidence(
            travel_date=req.travel_date,
            province_name=req.province,
            sigungu_name=req.sigungu,
            vehicle_type=req.vehicle_type,
            expected_price=req.expected_price,
            evidence_dir=evidence_dir,
        )
        background_tasks.add_task(shutil.rmtree, evidence_dir, ignore_errors=True)
        return FileResponse(
            output_path,
            media_type="image/png",
            filename=(
                f"opinet_{req.travel_date.isoformat()}_"
                f"{req.sigungu}_{req.vehicle_type}.png"
            ),
        )
    except Exception as e:
        shutil.rmtree(evidence_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/estimate", response_model=EstimateResponse)
async def estimate(req: TravelRequest):
    try:
        return await estimate_travel(req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/report.pdf")
async def report_pdf(req: TravelRequest, background_tasks: BackgroundTasks):
    evidence_dir = tempfile.mkdtemp(prefix="report_evidence_")
    output_path = None
    try:
        result = await estimate_travel(req)
        fd, output_path = tempfile.mkstemp(prefix="travel_expense_", suffix=".pdf")
        os.close(fd)

        evidence_path = None
        evidence_error = None
        evidence_vehicle = _evidence_vehicle(req)

        if result.evidence_status == "manual_price":
            evidence_error = "당일 오피넷 일평균 미제공으로 적용 유가를 사용자가 직접 입력했습니다."
        elif (
            evidence_vehicle
            and result.energy_price is not None
            and not req.public_vehicle
        ):
            try:
                evidence_path = await generate_opinet_evidence(
                    travel_date=result.fuel_price_date or req.travel_date,
                    province_name=result.province,
                    sigungu_name=result.sigungu,
                    vehicle_type=evidence_vehicle,
                    expected_price=float(result.energy_price),
                    evidence_dir=evidence_dir,
                )
            except Exception as e:
                evidence_error = str(e)

        await generate_estimate_pdf(
            req,
            result,
            output_path,
            evidence_path=evidence_path,
            evidence_error=evidence_error,
        )

        background_tasks.add_task(os.remove, output_path)
        background_tasks.add_task(shutil.rmtree, evidence_dir, ignore_errors=True)

        return FileResponse(
            output_path,
            media_type="application/pdf",
            filename=f"travel_expense_{req.travel_date.isoformat()}.pdf",
        )
    except Exception as e:
        if output_path and os.path.exists(output_path):
            os.remove(output_path)
        shutil.rmtree(evidence_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/report-regulation.pdf")
async def report_regulation_pdf(req: TravelRequest, background_tasks: BackgroundTasks):
    evidence_dir = tempfile.mkdtemp(prefix="regulation_report_evidence_")
    output_path = None
    try:
        result = await estimate_travel(req)
        fd, output_path = tempfile.mkstemp(
            prefix="travel_expense_regulation_", suffix=".pdf"
        )
        os.close(fd)

        evidence_path = None
        evidence_error = None
        evidence_vehicle = _evidence_vehicle(req)

        if result.evidence_status == "manual_price":
            evidence_error = "당일 오피넷 일평균 미제공으로 적용 유가를 사용자가 직접 입력했습니다."
        elif (
            evidence_vehicle
            and result.energy_price is not None
            and not req.public_vehicle
        ):
            try:
                evidence_path = await generate_opinet_evidence(
                    travel_date=result.fuel_price_date or req.travel_date,
                    province_name=result.province,
                    sigungu_name=result.sigungu,
                    vehicle_type=evidence_vehicle,
                    expected_price=float(result.energy_price),
                    evidence_dir=evidence_dir,
                )
            except Exception as e:
                evidence_error = str(e)

        await generate_regulation_pdf(
            req,
            result,
            output_path,
            evidence_path=evidence_path,
            evidence_error=evidence_error,
        )

        background_tasks.add_task(os.remove, output_path)
        background_tasks.add_task(shutil.rmtree, evidence_dir, ignore_errors=True)

        return FileResponse(
            output_path,
            media_type="application/pdf",
            filename=f"travel_expense_regulation_{req.travel_date.isoformat()}.pdf",
        )
    except Exception as e:
        if output_path and os.path.exists(output_path):
            os.remove(output_path)
        shutil.rmtree(evidence_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(e))
