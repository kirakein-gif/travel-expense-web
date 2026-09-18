from __future__ import annotations

import json
from datetime import date
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "ev_charge_price_history.json"


def _load() -> dict:
    with DATA_PATH.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def get_electric_rate(travel_date: date) -> dict:
    """Return the active public rapid-charge rate effective on travel_date."""
    data = _load()
    active = [
        row
        for row in data.get("rates", [])
        if row.get("status") == "active"
        and date.fromisoformat(row["effective_from"]) <= travel_date
    ]
    if not active:
        raise ValueError(
            "선택한 출장일에 적용할 전기차 충전요금 이력이 없습니다. "
            "기준단가를 확인한 뒤 관리자에게 갱신을 요청해주세요."
        )

    row = max(active, key=lambda item: item["effective_from"])
    policy = data.get("policy", {})
    return {
        "price": float(row["price_per_kwh"]),
        "effective_from": date.fromisoformat(row["effective_from"]),
        "source_updated_at": row.get("source_updated_at"),
        "rate_label": row.get("rate_label") or policy.get("rate_label", "급속"),
        "source_url": row.get("source_url") or policy.get("source_url"),
        "provider": policy.get("provider", "기후에너지환경부"),
    }
