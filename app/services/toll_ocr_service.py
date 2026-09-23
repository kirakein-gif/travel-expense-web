from __future__ import annotations

import io
import logging
import re
import unicodedata
import time
from collections import Counter, defaultdict

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat
import pytesseract
from pytesseract import Output

logger = logging.getLogger("uvicorn.error")

_AMOUNT_TOKEN = r"([0-9]{1,3}(?:[\s,.][0-9]{3})+(?:[48])?|[0-9]{2,6})"
_VEHICLE_RE = re.compile(r"([1-6])\s*종")
_SUPPLY_RE = re.compile(
    rf"공\s*급\s*가\s*액[^0-9]{{0,14}}{_AMOUNT_TOKEN}\s*원?"
)
_VAT_RE = re.compile(
    rf"부\s*가\s*세(?:\s*액)?[^0-9]{{0,14}}{_AMOUNT_TOKEN}\s*원?"
)
_CLASS_TOTAL_RE = re.compile(
    rf"([1-6])\s*종[^0-9]{{0,18}}{_AMOUNT_TOKEN}\s*원?"
)
_SPLIT_WORD_RE = re.compile(
    rf"\b(KEC|CNE)\b[^0-9]{{0,18}}{_AMOUNT_TOKEN}\s*원?",
    re.IGNORECASE,
)
_ANY_AMOUNT_RE = re.compile(_AMOUNT_TOKEN)
_OPERATOR_RE = re.compile(r"\\b(KEC|CNE)\\b", re.IGNORECASE)


def _money(value: str | None, *, cleanup_won_glyph: bool = False) -> int | None:
    if not value:
        return None
    raw = (
        value.replace(",", "")
        .replace(".", "")
        .replace(":", "")
        .replace(" ", "")
        .replace("\u00a0", "")
    )
    if cleanup_won_glyph and len(raw) >= 4 and raw[-1] in {"4", "8"}:
        trimmed = raw[:-1]
        if trimmed.isdigit() and int(trimmed) >= 100 and int(trimmed) % 10 == 0:
            raw = trimmed
    if not raw.isdigit():
        return None
    number = int(raw)
    if number < 10 or number > 500000:
        return None
    return number


def _normalize_line(line: str) -> str:
    value = unicodedata.normalize("NFKC", line or "")
    value = value.replace("：", ":").replace("₩", "원")
    value = re.sub(r"(?<=\\d)[,.:]\\s*[,.](?=\\d{3}(?:\\D|$))", ",", value)
    value = re.sub(r"(?<=\\d):(?=\\d{3}(?:\\D|$))", ",", value)
    # Restrict OCR-token correction to isolated operator words.
    value = re.sub(r"\bK[E3]C\b", "KEC", value, flags=re.IGNORECASE)
    value = re.sub(r"\bCN[E3]\b", "CNE", value, flags=re.IGNORECASE)
    return " ".join(value.split())


def _normalize_lines(lines: list[str]) -> list[str]:
    return [_normalize_line(line) for line in lines if (line or "").strip()]


def _source_a(text: str) -> tuple[int | None, dict]:
    supply_match = _SUPPLY_RE.search(text)
    vat_match = _VAT_RE.search(text)
    supply = _money(supply_match.group(1)) if supply_match else None
    vat = _money(vat_match.group(1)) if vat_match else None
    if supply is None or vat is None:
        return None, {"supply": supply, "vat": vat}
    return supply + vat, {"supply": supply, "vat": vat}


def _source_b(lines: list[str]) -> tuple[int | None, int | None]:
    for index, line in enumerate(lines):
        match = _CLASS_TOTAL_RE.search(line)
        if match:
            vehicle_class = int(match.group(1))
            amount = _money(match.group(2), cleanup_won_glyph=True)
            if amount is not None:
                return amount, vehicle_class

        # Sparse-text OCR often separates "1종" and "2,400원" into
        # neighboring lines. Pair only with the next two lines.
        vehicle_match = _VEHICLE_RE.search(line)
        if not vehicle_match:
            continue

        vehicle_class = int(vehicle_match.group(1))
        candidates = [line[vehicle_match.end():]] + lines[index + 1 : index + 3]
        for candidate in candidates:
            amount_match = _ANY_AMOUNT_RE.search(candidate)
            if not amount_match:
                continue
            amount = _money(amount_match.group(1), cleanup_won_glyph=True)
            if amount is not None:
                return amount, vehicle_class

    return None, None


def _source_c(lines: list[str]) -> tuple[int | None, list[dict]]:
    parts: list[dict] = []
    for index, line in enumerate(lines):
        matched_on_line = False
        for match in _SPLIT_WORD_RE.finditer(line):
            amount = _money(match.group(2), cleanup_won_glyph=True)
            if amount is not None:
                parts.append({"operator": match.group(1).upper(), "amount": amount})
                matched_on_line = True

        if matched_on_line:
            continue

        # PSM 11 can emit KEC/CNE and its amount on separate lines.
        operator_match = _OPERATOR_RE.search(line)
        if not operator_match:
            continue
        for candidate in lines[index + 1 : index + 3]:
            amount_match = _ANY_AMOUNT_RE.search(candidate)
            if not amount_match:
                continue
            amount = _money(amount_match.group(1), cleanup_won_glyph=True)
            if amount is not None:
                parts.append(
                    {"operator": operator_match.group(1).upper(), "amount": amount}
                )
                break

    if not parts:
        return None, []

    unique: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for part in parts:
        key = (part["operator"], part["amount"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(part)

    return sum(part["amount"] for part in unique), unique


def analyze_receipt_lines(lines: list[str]) -> dict:
    lines = _normalize_lines(lines)
    text = "\n".join(lines)

    amount_a, detail_a = _source_a(text)
    amount_b, vehicle_from_b = _source_b(lines)
    amount_c, detail_c = _source_c(lines)

    vehicle_matches = [int(value) for value in _VEHICLE_RE.findall(text)]
    vehicle_class = vehicle_from_b or (vehicle_matches[0] if vehicle_matches else None)

    source_values = {"A": amount_a, "B": amount_b, "C": amount_c}
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
        or any(
            keyword in text
            for keyword in ("영수증", "하이패스", "공급가액", "부가세", "KEC", "CNE")
        )
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


def _prepare_base_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGB")
    max_side = max(image.width, image.height)
    if max_side < 1800:
        scale = min(2.2, 1800 / max(max_side, 1))
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    elif max_side > 3600:
        scale = 3600 / max_side
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    return image


def _gray_for_ocr(image: Image.Image) -> Image.Image:
    gray = ImageOps.autocontrast(ImageOps.grayscale(_prepare_base_image(image)))
    mean = ImageStat.Stat(gray).mean[0]
    if mean < 105:
        gray = ImageOps.invert(gray)
        gray = ImageOps.autocontrast(gray)
    return gray


def _ocr_variant(image: Image.Image, *, psm: int, binary: bool = False) -> list[str]:
    gray = _gray_for_ocr(image)
    if binary:
        # Keep anti-aliased text from disappearing: autocontrast first, then a
        # moderately permissive fixed threshold.
        gray = gray.point(lambda px: 255 if px > 185 else 0)
    else:
        gray = ImageEnhance.Contrast(gray).enhance(1.12)
        gray = gray.filter(ImageFilter.UnsharpMask(radius=1.0, percent=135, threshold=3))

    config = f"--oem 3 --psm {psm} -c preserve_interword_spaces=1"
    try:
        data = pytesseract.image_to_data(
            gray,
            lang="kor+eng",
            config=config,
            output_type=Output.DICT,
        )
    except pytesseract.TesseractError:
        data = pytesseract.image_to_data(
            gray,
            lang="eng",
            config=config,
            output_type=Output.DICT,
        )

    grouped: dict[tuple[int, int, int], list[tuple[int, str]]] = defaultdict(list)
    total = len(data.get("text", []))
    block_nums = data.get("block_num", [0] * total)
    par_nums = data.get("par_num", [0] * total)
    line_nums = data.get("line_num", [0] * total)
    lefts = data.get("left", [0] * total)
    confs = data.get("conf", ["-1"] * total)

    for i in range(total):
        token = (data["text"][i] or "").strip()
        if not token:
            continue
        try:
            confidence = float(confs[i])
        except (TypeError, ValueError):
            confidence = -1
        if 0 <= confidence < 18:
            continue
        key = (int(block_nums[i]), int(par_nums[i]), int(line_nums[i]))
        grouped[key].append((int(lefts[i]), token))

    lines: list[str] = []
    for key in sorted(grouped):
        line = " ".join(
            token for _, token in sorted(grouped[key], key=lambda item: item[0])
        ).strip()
        if line:
            lines.append(line)
    return lines


def _source_consensus(results: list[dict]) -> dict[str, int | None]:
    consensus: dict[str, int | None] = {"A": None, "B": None, "C": None}
    for source in consensus:
        values = [
            int(result["sources"][source])
            for result in results
            if result.get("sources", {}).get(source) is not None
        ]
        if values:
            consensus[source] = Counter(values).most_common(1)[0][0]
    return consensus


def _merge_pass_results(pass_results: list[tuple[str, list[str], dict]]) -> dict:
    if not pass_results:
        return analyze_receipt_lines([])

    results = [entry[2] for entry in pass_results]
    consensus = _source_consensus(results)
    source_counts = Counter(value for value in consensus.values() if value is not None)

    amount = None
    confirmed = False
    if source_counts:
        candidate, count = source_counts.most_common(1)[0]
        if count >= 2:
            amount = candidate
            confirmed = True

    # When only one semantic pattern survives, repeated agreement across
    # independent OCR passes is useful but still remains a review result.
    all_amount_votes = Counter(
        int(result["amount"])
        for result in results
        if result.get("amount") is not None
    )
    stable_pass_amount = None
    stable_pass_votes = 0
    if all_amount_votes:
        stable_pass_amount, stable_pass_votes = all_amount_votes.most_common(1)[0]

    if amount is None:
        a_value = consensus.get("A")
        amount = (
            a_value
            if a_value is not None
            else stable_pass_amount
            if stable_pass_amount is not None
            else next((v for v in consensus.values() if v is not None), None)
        )

    best_name, best_lines, best = max(
        pass_results,
        key=lambda entry: (
            1 if entry[2].get("status") == "confirmed" else 0,
            sum(value is not None for value in entry[2].get("sources", {}).values()),
            len("".join(entry[1])),
        ),
    )

    vehicle_votes = Counter(
        int(result["vehicle_class"])
        for result in results
        if result.get("vehicle_class") is not None
    )
    vehicle_class = vehicle_votes.most_common(1)[0][0] if vehicle_votes else None
    vehicle_warning = vehicle_class in {2, 3, 4, 5}
    vehicle_note = None
    if vehicle_class:
        vehicle_note = f"{vehicle_class}종"
        if vehicle_warning:
            vehicle_note += " · 차종 확인"

    if confirmed:
        status = "confirmed"
        status_label = "확정"
        note = "복수 OCR 판독 · 두 개 이상 패턴 일치"
    else:
        status = "review"
        status_label = "확인 필요"
        if amount is None:
            note = "복수 OCR 판독에도 금액 패턴 미인식"
        elif stable_pass_votes >= 2:
            note = f"복수 OCR 판독값 일치({stable_pass_votes}회) · 확인 필요"
        else:
            note = best.get("note") or "금액 확인 필요"

    return {
        "amount": amount,
        "status": status,
        "status_label": status_label,
        "note": note,
        "sources": consensus,
        "source_a_detail": best.get("source_a_detail", {}),
        "source_c_detail": best.get("source_c_detail", []),
        "vehicle_class": vehicle_class,
        "vehicle_warning": vehicle_warning,
        "vehicle_note": vehicle_note,
        "has_signal": any(result.get("has_signal") for result in results),
        "lines": best_lines,
        "ocr_pass": best_name,
        "ocr_pass_count": len(pass_results),
    }


def _analyze_region(image: Image.Image) -> dict:
    passes: list[tuple[str, list[str], dict]] = []

    def run(name: str, *, psm: int) -> dict:
        lines = _ocr_variant(image, psm=psm, binary=False)
        result = analyze_receipt_lines(lines)
        passes.append((name, lines, result))
        return result

    # Recommended "보고서 인쇄" receipts are sparse and consistently laid out.
    # One PSM 11 pass is normally enough after adjacent-line amount pairing.
    first = run("gray_psm11", psm=11)
    if first["status"] == "confirmed":
        merged = _merge_pass_results(passes)
        merged["note"] = "보고서 인쇄 빠른 판독 · 두 개 이상 패턴 일치"
        return merged

    # Only the receipt that was not confirmed gets one additional layout pass.
    run("gray_psm4", psm=4)
    return _merge_pass_results(passes)


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            found.append((start, index - 1))
            start = None
    if start is not None:
        found.append((start, len(flags) - 1))
    return found


def _find_vertical_separators(image: Image.Image) -> list[int]:
    """Detect strong divider lines or wide blank gutters between receipts."""
    gray = ImageOps.autocontrast(ImageOps.grayscale(ImageOps.exif_transpose(image)))
    if gray.width > 1400:
        scale = 1400 / gray.width
        gray = gray.resize(
            (1400, max(1, int(gray.height * scale))),
            Image.Resampling.BILINEAR,
        )
    width, height = gray.size
    if width < 280 or height < 120:
        return []

    # Ignore very top/bottom margins, where browser chrome or labels can create
    # unrelated long lines.
    y0 = int(height * 0.10)
    y1 = max(y0 + 1, int(height * 0.90))
    band_height = max(1, y1 - y0)
    px = gray.load()

    dark_ratio: list[float] = []
    for x in range(width):
        dark = 0
        for y in range(y0, y1):
            if px[x, y] < 120:
                dark += 1
        dark_ratio.append(dark / band_height)

    # Candidate 1: long vertical divider line.
    line_flags = [ratio >= 0.52 for ratio in dark_ratio]
    candidates: list[tuple[float, int]] = []
    for start, end in _runs(line_flags):
        center = (start + end) // 2
        if width * 0.16 <= center <= width * 0.84:
            score = max(dark_ratio[start : end + 1]) + min(0.20, (end - start + 1) / 20)
            candidates.append((score + 1.0, center))

    # Candidate 2: a genuinely blank gutter. Require activity on both sides so
    # ordinary white receipt margins are not mistaken for separators.
    blank_flags = [ratio <= 0.002 for ratio in dark_ratio]
    min_blank = max(8, int(width * 0.008))
    neighborhood = max(15, int(width * 0.025))
    for start, end in _runs(blank_flags):
        if end - start + 1 < min_blank:
            continue
        center = (start + end) // 2
        if not (width * 0.18 <= center <= width * 0.82):
            continue
        left = dark_ratio[max(0, start - neighborhood) : start]
        right = dark_ratio[end + 1 : min(width, end + 1 + neighborhood)]
        if not left or not right:
            continue
        if max(left) < 0.015 or max(right) < 0.015:
            continue
        gutter_width = end - start + 1
        candidates.append((0.7 + min(0.25, gutter_width / max(width, 1)), center))

    if not candidates:
        return []

    # Keep at most two well-separated separators. Prefer stronger structural
    # signals, then restore left-to-right order.
    candidates.sort(reverse=True)
    chosen: list[int] = []
    min_region = int(width * 0.22)
    for _, x in candidates:
        if any(abs(x - prior) < int(width * 0.12) for prior in chosen):
            continue
        trial = sorted(chosen + [x])
        edges = [0] + trial + [width]
        if min(b - a for a, b in zip(edges, edges[1:])) < min_region:
            continue
        chosen.append(x)
        if len(chosen) == 2:
            break

    if not chosen:
        return []

    # Convert separator coordinates back to the source image width.
    scale_back = image.width / width
    return sorted(int(round(x * scale_back)) for x in chosen)


def _regions_from_separators(image: Image.Image, separators: list[int]) -> list[Image.Image]:
    if not separators:
        return [image]

    bounds = [0] + sorted(separators) + [image.width]
    pad = max(2, int(image.width * 0.004))
    regions: list[Image.Image] = []
    for left, right in zip(bounds, bounds[1:]):
        crop_left = min(max(0, left + pad), image.width)
        crop_right = max(min(image.width, right - pad), crop_left + 1)
        if crop_right - crop_left >= 100:
            regions.append(image.crop((crop_left, 0, crop_right, image.height)))
    return regions or [image]


def _equal_split_regions(image: Image.Image, count: int) -> list[Image.Image]:
    overlap = max(8, int(image.width * 0.012))
    regions: list[Image.Image] = []
    for index in range(count):
        left = max(0, int(image.width * index / count) - overlap)
        right = min(image.width, int(image.width * (index + 1) / count) + overlap)
        regions.append(image.crop((left, 0, right, image.height)))
    return regions


def _plan_score(results: list[dict]) -> tuple[int, int, int, int]:
    confirmed = sum(1 for result in results if result.get("status") == "confirmed")
    recognized = sum(1 for result in results if result.get("amount") is not None)
    signaled = sum(1 for result in results if result.get("has_signal"))
    # Fewer spurious regions wins ties.
    return confirmed, recognized, signaled, -len(results)


def _analyze_plan(regions: list[Image.Image]) -> list[dict]:
    return [_analyze_region(region) for region in regions]


def extract_toll_ocr(image_bytes: bytes) -> dict:
    started_at = time.perf_counter()
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        image = ImageOps.exif_transpose(image).convert("RGB")
    except Exception as exc:
        raise ValueError("통행료 증빙 이미지 형식을 확인해주세요.") from exc

    if image.width < 100 or image.height < 60:
        raise ValueError("통행료 증빙 이미지가 너무 작습니다.")

    separators = _find_vertical_separators(image)
    plans: list[tuple[str, list[Image.Image]]] = []

    analyzed: list[tuple[str, list[dict]]] = []

    if separators:
        # For the recommended report-print capture, structural separators are
        # trusted. Re-reading the whole image was the main source of latency.
        separator_regions = _regions_from_separators(image, separators)
        analyzed.append(("separator", _analyze_plan(separator_regions)))
    else:
        analyzed.append(("whole", _analyze_plan([image])))

    best_name, receipts = max(analyzed, key=lambda item: _plan_score(item[1]))

    # Only attempt geometric fallback when structure detection found nothing
    # and the whole-image result is not already reliable.
    whole_result = next((items for name, items in analyzed if name == "whole"), [])
    whole_confirmed = bool(
        len(whole_result) == 1 and whole_result[0].get("status") == "confirmed"
    )
    ratio = image.width / max(image.height, 1)
    if not separators and not whole_confirmed and ratio >= 1.25:
        fallback_counts = [2]
        if ratio >= 2.15:
            fallback_counts.append(3)
        for count in fallback_counts:
            regions = _equal_split_regions(image, count)
            results = _analyze_plan(regions)
            analyzed.append((f"equal_{count}", results))
            if _plan_score(results) > _plan_score(receipts):
                best_name, receipts = f"equal_{count}", results

    usable_receipts = [
        receipt
        for receipt in receipts
        if receipt.get("has_signal")
        or receipt.get("amount") is not None
        or len("".join(receipt.get("lines", []))) >= 10
    ]
    if usable_receipts:
        receipts = usable_receipts

    for index, receipt in enumerate(receipts, start=1):
        receipt["receipt_index"] = index
        receipt["segmentation"] = best_name
        receipt.pop("has_signal", None)

    recognized = [receipt for receipt in receipts if receipt.get("amount") is not None]
    total_amount = sum(int(receipt["amount"]) for receipt in recognized)
    confirmed_count = sum(
        1 for receipt in recognized if receipt["status"] == "confirmed"
    )
    review_count = len(receipts) - confirmed_count

    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "[TOLL_OCR] segmentation=%s separators=%s receipts=%s recognized=%s confirmed=%s total=%s elapsed_ms=%s",
        best_name,
        separators,
        len(receipts),
        len(recognized),
        confirmed_count,
        total_amount,
        elapsed_ms,
    )

    return {
        "receipts": receipts,
        "total_amount": total_amount,
        "recognized_count": len(recognized),
        "confirmed_count": confirmed_count,
        "review_count": review_count,
        "overall_status": "confirmed" if recognized and review_count == 0 else "review",
        "segmentation": best_name,
    }
