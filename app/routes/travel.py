import os
import tempfile

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from app.models import (
    DistanceResponse,
    EstimateResponse,
    PriceRequest,
    PriceResponse,
    TravelRequest,
)
from app.services.pdf_service import generate_estimate_pdf
from app.services.travel_service import estimate_travel, resolve_distance, resolve_price

router = APIRouter(tags=["travel"])


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


@router.post("/estimate", response_model=EstimateResponse)
async def estimate(req: TravelRequest):
    try:
        return await estimate_travel(req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/report.pdf")
async def report_pdf(req: TravelRequest, background_tasks: BackgroundTasks):
    try:
        result = await estimate_travel(req)
        fd, output_path = tempfile.mkstemp(prefix="travel_expense_", suffix=".pdf")
        os.close(fd)

        await generate_estimate_pdf(req, result, output_path)
        background_tasks.add_task(os.remove, output_path)

        return FileResponse(
            output_path,
            media_type="application/pdf",
            filename=f"travel_expense_{req.travel_date.isoformat()}.pdf",
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
