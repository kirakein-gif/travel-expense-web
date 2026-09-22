from __future__ import annotations

import io
import re
from collections import defaultdict

from PIL import Image, ImageOps
import pytesseract
from pytesseract import Output


_AMOUNT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{3,6})(?:\s*원)?(?!\d)")
_MONEY_WORDS = ("통행료", "이용금액", "결제금액", "금액", "요금", "원")


def _is_date_or_time_number(line: str, raw: str, value: int) -> bool:
    compact = raw.replace(",", "")
    plain = line.replace(",", "")
    if 1900 <= value <= 2100 and re.search(rf"{re.escape(compact)}\s*(?:[./-]|년)", plain):
        return True
    if len(compact) in {3, 4} and re.search(rf"(?<!\d){re.escape(compact)}\s*:", plain):
        return True
    return False


def extract_amount_candidates_from_lines(lines: list[str]) -> list[dict]:
    candidates: list[dict] = []
    for line_index, original in enumerate(lines):
        line = " ".join((original or "").split())
        if not line:
            continue
        matches = []
        for match in _AMOUNT_RE.finditer(line):
            raw = match.group(1)
            value = int(raw.replace(",", ""))
            if value < 100 or value > 500000:
                continue
            if _is_date_or_time_number(line, raw, value):
                continue
            matches.append((match, raw, value))
        if not matches:
            continue

        rightmost = matches[-1][0].start()
        has_money_word = any(word in line for word in _MONEY_WORDS)
        for match, raw, value in matches:
            near = line[max(0, match.start()-2):min(len(line), match.end()+3)]
            recommended = bool("원" in near or has_money_word or "," in raw or match.start() == rightmost)
            candidates.append({
                "amount": value,
                "line": line,
                "line_index": line_index,
                "recommended": recommended,
            })
    return candidates[:40]


def _ocr_lines(image: Image.Image) -> list[str]:
    image = ImageOps.exif_transpose(image).convert("RGB")
    max_side = max(image.width, image.height)
    if max_side < 1800:
        scale = min(2.2, 1800 / max(max_side, 1))
        image = image.resize(
            (max(1, int(image.width*scale)), max(1, int(image.height*scale))),
            Image.Resampling.LANCZOS,
        )
    gray = ImageOps.autocontrast(ImageOps.grayscale(image))
    try:
        data = pytesseract.image_to_data(gray, lang="kor+eng", config="--psm 6", output_type=Output.DICT)
    except pytesseract.TesseractError:
        data = pytesseract.image_to_data(gray, lang="eng", config="--psm 6", output_type=Output.DICT)

    grouped: dict[tuple[int, int, int], list[tuple[int, str]]] = defaultdict(list)
    total = len(data.get("text", []))
    for i in range(total):
        token = (data["text"][i] or "").strip()
        if not token:
            continue
        key = (
            int(data.get("block_num", [0]*total)[i]),
            int(data.get("par_num", [0]*total)[i]),
            int(data.get("line_num", [0]*total)[i]),
        )
        grouped[key].append((int(data.get("left", [0]*total)[i]), token))

    lines = []
    for key in sorted(grouped):
        line = " ".join(token for _, token in sorted(grouped[key], key=lambda x:x[0])).strip()
        if line:
            lines.append(line)
    return lines


def extract_toll_ocr(image_bytes: bytes) -> dict:
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except Exception as exc:
        raise ValueError("통행료 증빙 이미지 형식을 확인해주세요.") from exc
    if image.width < 100 or image.height < 60:
        raise ValueError("통행료 증빙 이미지가 너무 작습니다.")
    lines = _ocr_lines(image)
    return {
        "text": "\n".join(lines),
        "lines": lines,
        "candidates": extract_amount_candidates_from_lines(lines),
    }
