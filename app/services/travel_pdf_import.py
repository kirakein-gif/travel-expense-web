from __future__ import annotations

from io import BytesIO
import re
from typing import Any

from pypdf import PdfReader


_DATE_START_RE = re.compile(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})\s*부터")
_DATE_END_RE = re.compile(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})\s*까지")
_TIME_RE = re.compile(r"(\d{1,2}:\d{2})\s*[~～-]\s*(\d{1,2}:\d{2})")


def _iso(match: re.Match[str] | None) -> str | None:
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _clean(text: str) -> str:
    return " ".join((text or "").replace("\n", " ").split())


def _compact(parts: list[str]) -> str:
    return "".join(p.strip() for p in parts if p and p.strip())


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _page_chunks(page) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []

    def visitor(text, cm, tm, font_dict, font_size):
        value = _clean(text)
        if value:
            chunks.append({"x": float(tm[4]), "y": float(tm[5]), "text": value})

    page.extract_text(visitor_text=visitor)
    return chunks


def _detect_type(reader: PdfReader) -> str:
    sample = "\n".join((page.extract_text() or "") for page in reader.pages[:2])
    if "서명 또는 날인" in sample and "다음과 같이 출장을 명함" in sample:
        return "approval"
    return "list"


def _metadata(reader: PdfReader) -> tuple[str | None, str | None]:
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    affiliation = None
    owner = None

    department = re.search(r"\(부서\s*:\s*([^\)]+)\)", text)
    if department:
        affiliation = department.group(1).strip()

    footer = re.search(
        r"(?m)^\s*([^/\n]{2,60})/(\d{14})/[^/\n]+/([^/\n]+)\s*$",
        text,
    )
    if footer:
        affiliation = affiliation or footer.group(1).strip()
        owner = footer.group(3).strip()
    return affiliation, owner


def _ranges(doc_type: str) -> list[tuple[float, float]]:
    if doc_type == "list":
        return [(-1e9, 100), (100, 160), (160, 350), (350, 470), (470, 1e9)]
    return [(-1e9, 100), (100, 160), (160, 285), (285, 390), (390, 465), (465, 1e9)]


def _records_from_page(page, page_number: int, doc_type: str) -> list[dict[str, Any]]:
    chunks = _page_chunks(page)
    ranges = _ranges(doc_type)
    period_range = ranges[3]

    starts = [
        c
        for c in chunks
        if period_range[0] <= c["x"] < period_range[1] and _DATE_START_RE.search(c["text"])
    ]
    ends = [
        c
        for c in chunks
        if period_range[0] <= c["x"] < period_range[1] and _DATE_END_RE.search(c["text"])
    ]
    starts.sort(key=lambda c: -c["y"])

    rows: list[dict[str, Any]] = []
    for index, start in enumerate(starts):
        next_y = starts[index + 1]["y"] if index + 1 < len(starts) else -1e9
        end_candidates = [e for e in ends if next_y < e["y"] < start["y"]]
        end = max(end_candidates, key=lambda e: e["y"]) if end_candidates else None
        low = (end["y"] - 8) if end else (next_y + 1)
        high = start["y"] + 8
        band = [c for c in chunks if low <= c["y"] <= high]

        columns: list[list[dict[str, Any]]] = []
        for left, right in ranges:
            values = [c for c in band if left <= c["x"] < right]
            values.sort(key=lambda c: (-c["y"], c["x"]))
            columns.append(values)

        def texts(col: int) -> list[str]:
            return [c["text"] for c in columns[col]]

        names = texts(1)
        name = next((n for n in names if re.fullmatch(r"[가-힣]{2,5}", n)), None)
        if not name:
            continue

        period_text = " ".join(texts(3))
        start_match = _DATE_START_RE.search(period_text)
        end_match = _DATE_END_RE.search(period_text)
        time_match = _TIME_RE.search(period_text)
        start_date = _iso(start_match)
        if not start_date:
            continue

        position_parts = [t for t in texts(0) if "직" not in t or "급" not in t]
        purpose = _compact(texts(2))
        destination = _compact(texts(4))
        signature = texts(5)[0] if doc_type == "approval" and len(columns) > 5 and texts(5) else None

        rows.append(
            {
                "page": page_number,
                "position": " ".join(dict.fromkeys(position_parts)),
                "name": name,
                "purpose": purpose,
                "start_date": start_date,
                "end_date": _iso(end_match) or start_date,
                "time": f"{time_match.group(1)}~{time_match.group(2)}" if time_match else "",
                "destination": destination,
                "signature": signature,
            }
        )
    return rows


def parse_travel_pdf(data: bytes, filename: str = "") -> dict[str, Any]:
    reader = PdfReader(BytesIO(data))
    if not reader.pages:
        raise ValueError("PDF에 읽을 수 있는 페이지가 없습니다.")

    doc_type = _detect_type(reader)
    affiliation, owner = _metadata(reader)

    rows: list[dict[str, Any]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        rows.extend(_records_from_page(page, page_number, doc_type))

    if not rows:
        raise ValueError("출장신청서에서 출장 내역을 찾지 못했습니다.")

    groups: list[dict[str, Any]] = []
    group_index: dict[tuple[str, ...], int] = {}
    for row in rows:
        key = (
            row["start_date"],
            row["end_date"],
            row["time"],
            _norm(row["purpose"]),
            _norm(row["destination"]),
        )
        if key not in group_index:
            group_index[key] = len(groups)
            groups.append(
                {
                    "id": f"trip-{len(groups) + 1}",
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "time": row["time"],
                    "purpose": row["purpose"],
                    "destination": row["destination"],
                    "pages": [],
                    "participants": [],
                }
            )
        group = groups[group_index[key]]
        if row["page"] not in group["pages"]:
            group["pages"].append(row["page"])
        group["participants"].append(
            {"name": row["name"], "position": row["position"], "signature": row["signature"]}
        )

    groups.sort(key=lambda g: (g["start_date"], g["time"], g["destination"]), reverse=True)
    for number, group in enumerate(groups, start=1):
        group["id"] = f"trip-{number}"
        applicant = next((p for p in group["participants"] if owner and p["name"] == owner), None)
        applicant = applicant or group["participants"][0]
        group["default_applicant"] = applicant["name"]
        group["label"] = (
            f'{group["start_date"]} · {group["destination"]} · '
            f'{applicant["name"]}'
            + (f' 외 {len(group["participants"]) - 1}명' if len(group["participants"]) > 1 else "")
        )

    return {
        "filename": filename,
        "document_type": doc_type,
        "document_type_label": "결재용" if doc_type == "approval" else "리스트용",
        "affiliation": affiliation,
        "owner_name": owner,
        "page_count": len(reader.pages),
        "row_count": len(rows),
        "trip_count": len(groups),
        "trips": groups,
    }
