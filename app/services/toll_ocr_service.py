from __future__ import annotations

import io
import re
from collections import Counter, defaultdict

from PIL import Image, ImageOps
import pytesseract
from pytesseract import Output


_AMOUNT_TOKEN = r"([0-9]{1,3}(?:[,.][0-9]{3})+(?:[48])?|[0-9]{2,6})"
_VEHICLE_RE = re.compile(r"([1-6])\s*종")
_SUPPLY_RE = re.compile(rf"공\s*급\s*가\s*액[^0-9]{{0,10}}{_AMOUNT_TOKEN}\s*원?")
_VAT_RE = re.compile(rf"부\s*가\s*세[^0-9]{{0,10}}{_AMOUNT_TOKEN}\s*원?")
_CLASS_TOTAL_RE = re.compile(rf"([1-6])\s*종[^0-9]{{0,14}}{_AMOUNT_TOKEN}\s*원?")
_SPLIT_WORD_RE = re.compile(rf"\b(KEC|CNE)\b[^0-9]{{0,14}}{_AMOUNT_TOKEN}\s*원?", re.IGNORECASE)


def _money(value: str | None, *, cleanup_won_glyph: bool = False) -> int | None:
    if not value:
        return None
    raw = value.replace(",", "").replace(".", "")
    if cleanup_won_glyph and len(raw) >= 4 and raw[-1] in {"4", "8"}:
        trimmed = raw[:-1]
        if trimmed.isdigit() and int(trimmed) >= 100 and int(trimmed) % 10 == 0:
            raw = trimmed
    number = int(raw)
    if number < 10 or number > 500000:
        return None
    return number


def _normalize_lines(lines: list[str]) -> list[str]:
    return [" ".join((line or "").replace("：", ":").split()) for line in lines if (line or "").strip()]


def _source_a(text: str) -> tuple[int | None, dict]:
    supply_match = _SUPPLY_RE.search(text)
    vat_match = _VAT_RE.search(text)
    supply = _money(supply_match.group(1)) if supply_match else None
    vat = _money(vat_match.group(1)) if vat_match else None
    if supply is None or vat is None:
        return None, {"supply": supply, "vat": vat}
    return supply + vat, {"supply": supply, "vat": vat}


def _source_b(lines: list[str]) -> tuple[int | None, int | None]:
    for line in lines:
        match = _CLASS_TOTAL_RE.search(line)
        if not match:
            continue
        vehicle_class = int(match.group(1))
        amount = _money(match.group(2), cleanup_won_glyph=True)
        if amount is not None:
            return amount, vehicle_class
    return None, None


def _source_c(lines: list[str]) -> tuple[int | None, list[dict]]:
    parts: list[dict] = []
    for line in lines:
        for match in _SPLIT_WORD_RE.finditer(line):
            amount = _money(match.group(2), cleanup_won_glyph=True)
            if amount is not None:
                parts.append({"operator": match.group(1).upper(), "amount": amount})
    if not parts:
        return None, []
    return sum(part["amount"] for part in parts), parts


def analyze_receipt_lines(lines: list[str]) -> dict:
    lines = _normalize_lines(lines)
    text = "\n".join(lines)

    amount_a, detail_a = _source_a(text)
    amount_b, vehicle_from_b = _source_b(lines)
    amount_c, detail_c = _source_c(lines)

    vehicle_matches = [int(value) for value in _VEHICLE_RE.findall(text)]
    vehicle_class = vehicle_from_b or (vehicle_matches[0] if vehicle_matches else None)

    source_values = {
        "A": amount_a,
        "B": amount_b,
        "C": amount_c,
    }
    detected = {key: value for key, value in source_values.items() if value is not None}

    counts = Counter(detected.values())
    agreed_amount = None
    agreed_count = 0
    if counts:
        agreed_amount, agreed_count = counts.most_common(1)[0]

    confirmed = agreed_count >= 2
    if confirmed:
        amount = agreed_amount
        status = "confirmed"
        status_label = "확정"
        note = "두 개 이상 패턴 일치"
    else:
        amount = amount_a if amount_a is not None else amount_b if amount_b is not None else amount_c
        status = "review"
        status_label = "확인 필요"
        if amount is None:
            note = "금액 패턴을 읽지 못함"
        elif amount_a is not None and len(detected) == 1:
            note = "A만 인식 · 10원 단위 확인" if amount_a % 10 == 0 else "A만 인식 · 10원 단위 아님"
        elif amount_a is not None and len(set(detected.values())) > 1:
            note = "A 우선 적용 · 대조값 불일치"
        elif amount_a is None:
            note = "A 미인식 · B/C 값 확인"
        else:
            note = "금액 확인 필요"

    vehicle_warning = vehicle_class in {2, 3, 4, 5}
    vehicle_note = None
    if vehicle_class:
        vehicle_note = f"{vehicle_class}종"
        if vehicle_warning:
            vehicle_note += " · 차종 확인"

    has_signal = bool(
        detected
        or vehicle_class
        or any(keyword in text for keyword in ("영수증", "하이패스", "공급가액", "부가세", "KEC", "CNE"))
    )

    return {
        "amount": amount,
        "status": status,
        "status_label": status_label,
        "note": note,
        "sources": source_values,
        "source_a_detail": detail_a,
        "source_c_detail": detail_c,
        "vehicle_class": vehicle_class,
        "vehicle_warning": vehicle_warning,
        "vehicle_note": vehicle_note,
        "has_signal": has_signal,
    }


def _ocr_lines(image: Image.Image) -> list[str]:
    image = ImageOps.exif_transpose(image).convert("RGB")
    max_side = max(image.width, image.height)
    if max_side < 1800:
        scale = min(2.2, 1800 / max(max_side, 1))
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.Resampling.LANCZOS,
        )

    gray = ImageOps.autocontrast(ImageOps.grayscale(image))
    try:
        data = pytesseract.image_to_data(
            gray,
            lang="kor+eng",
            config="--psm 6",
            output_type=Output.DICT,
        )
    except pytesseract.TesseractError:
        data = pytesseract.image_to_data(
            gray,
            lang="eng",
            config="--psm 6",
            output_type=Output.DICT,
        )

    grouped: dict[tuple[int, int, int], list[tuple[int, str]]] = defaultdict(list)
    total = len(data.get("text", []))
    for i in range(total):
        token = (data["text"][i] or "").strip()
        if not token:
            continue
        key = (
            int(data.get("block_num", [0] * total)[i]),
            int(data.get("par_num", [0] * total)[i]),
            int(data.get("line_num", [0] * total)[i]),
        )
        grouped[key].append((int(data.get("left", [0] * total)[i]), token))

    lines = []
    for key in sorted(grouped):
        line = " ".join(
            token for _, token in sorted(grouped[key], key=lambda item: item[0])
        ).strip()
        if line:
            lines.append(line)
    return lines


def _receipt_regions(image: Image.Image) -> list[Image.Image]:
    image = ImageOps.exif_transpose(image).convert("RGB")
    ratio = image.width / max(image.height, 1)
    if ratio >= 1.55:
        count = 3
    elif ratio >= 0.95:
        count = 2
    else:
        count = 1

    if count == 1:
        return [image]

    overlap = max(8, int(image.width * 0.012))
    regions: list[Image.Image] = []
    for index in range(count):
        left = max(0, int(image.width * index / count) - overlap)
        right = min(image.width, int(image.width * (index + 1) / count) + overlap)
        regions.append(image.crop((left, 0, right, image.height)))
    return regions


def extract_toll_ocr(image_bytes: bytes) -> dict:
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except Exception as exc:
        raise ValueError("통행료 증빙 이미지 형식을 확인해주세요.") from exc

    if image.width < 100 or image.height < 60:
        raise ValueError("통행료 증빙 이미지가 너무 작습니다.")

    receipts = []
    for region in _receipt_regions(image):
        lines = _ocr_lines(region)
        result = analyze_receipt_lines(lines)
        if result["has_signal"] or len("".join(lines)) >= 10:
            result["lines"] = lines
            receipts.append(result)

    if not receipts:
        lines = _ocr_lines(image)
        result = analyze_receipt_lines(lines)
        result["lines"] = lines
        receipts = [result]

    for index, receipt in enumerate(receipts, start=1):
        receipt["receipt_index"] = index
        receipt.pop("has_signal", None)

    recognized = [receipt for receipt in receipts if receipt.get("amount") is not None]
    total_amount = sum(int(receipt["amount"]) for receipt in recognized)
    confirmed_count = sum(1 for receipt in recognized if receipt["status"] == "confirmed")
    review_count = len(receipts) - confirmed_count

    return {
        "receipts": receipts,
        "total_amount": total_amount,
        "recognized_count": len(recognized),
        "confirmed_count": confirmed_count,
        "review_count": review_count,
        "overall_status": "confirmed" if recognized and review_count == 0 else "review",
    }
