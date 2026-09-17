import os
import shutil
import tempfile

from fastapi import APIRouter, BackgroundTasks, HTTPException
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
from app.services.pdf_service import generate_estimate_pdf
from app.services.travel_service import estimate_travel, resolve_distance, resolve_price

router = APIRouter(tags=["travel"])


def _evidence_vehicle(req: TravelRequest) -> str | None:
    if req.vehicle_type in {"gasoline", "diesel", "lpg"}:
        return req.vehicle_type
    if req.vehicle_type == "hybrid":
        return "gasoline"
    if req.vehicle_type == "phev" and req.phev_energy_source == "gasoline":
        return "gasoline"
    return None


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

        # PDF generation may be slower than the normal calculation because the
        # official Opinet evidence is generated only at this final-output stage.
        if (
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
                # Keep the report printable even if the website evidence changes.
                # Page 2 will show the evidence error instead of silently omitting it.
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
