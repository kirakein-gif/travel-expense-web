from PIL import Image, ImageDraw

from app.services.toll_ocr_service import (
    _find_vertical_separators,
    _merge_pass_results,
    analyze_receipt_lines,
)


def test_sample_pattern_left_receipt_confirms_a_b_c():
    result = analyze_receipt_lines(
        [
            "2026년08월25일 17시09분",
            "1종 1,500원 (카드)",
            "KEC 1,300원 (카드)",
            "CNE 200원 (카드)",
            "공급가액 : 1,482원 부가세 : 18원",
        ]
    )
    assert result["amount"] == 1500
    assert result["sources"] == {"A": 1500, "B": 1500, "C": 1500}
    assert result["status"] == "confirmed"
    assert result["vehicle_class"] == 1
    assert result["vehicle_warning"] is False


def test_sample_pattern_right_receipt_confirms_a_b_c():
    result = analyze_receipt_lines(
        [
            "2026년08월25일 17시01분",
            "1종 2,400원 (카드)",
            "CNE 2,400원 (카드)",
            "공급가액 : 2,182원 부가세 : 218원",
        ]
    )
    assert result["amount"] == 2400
    assert result["sources"] == {"A": 2400, "B": 2400, "C": 2400}
    assert result["status"] == "confirmed"


def test_a_only_is_filled_but_requires_review_and_ten_won_check():
    result = analyze_receipt_lines(["공급가액 1,482원", "부가세 18원"])
    assert result["amount"] == 1500
    assert result["status"] == "review"
    assert "A만 인식" in result["note"]
    assert "10원 단위 확인" in result["note"]


def test_a_only_non_ten_won_amount_warns():
    result = analyze_receipt_lines(["공급가액 1,499원", "부가세 18원"])
    assert result["amount"] == 1517
    assert result["status"] == "review"
    assert "10원 단위 아님" in result["note"]


def test_b_and_c_match_can_confirm_without_a():
    result = analyze_receipt_lines(["6 종 3,200원", "CNE 3,200원"])
    assert result["amount"] == 3200
    assert result["status"] == "confirmed"
    assert result["vehicle_class"] == 6


def test_vehicle_classes_two_to_five_show_review_warning_only():
    result = analyze_receipt_lines(
        ["3 종 4,000원", "KEC 3,000원", "CNE 1,000원"]
    )
    assert result["amount"] == 4000
    assert result["status"] == "confirmed"
    assert result["vehicle_class"] == 3
    assert result["vehicle_warning"] is True
    assert "차종 확인" in result["vehicle_note"]


def test_source_a_accepts_dot_as_thousands_separator():
    result = analyze_receipt_lines(
        ["공급가액:1.482원 부가세:18원"]
    )
    assert result["amount"] == 1500
    assert result["sources"]["A"] == 1500
    assert result["status"] == "review"


def test_source_c_recovers_common_won_glyph_ocr_tail():
    result = analyze_receipt_lines(
        ["공급가액 : 1,482원 부가세 : 18원", "KEC 13004 (카드)", "CNE 2004 (카드)"]
    )
    assert result["sources"]["A"] == 1500
    assert result["sources"]["C"] == 1500
    assert result["amount"] == 1500
    assert result["status"] == "confirmed"


def test_source_c_accepts_dot_thousands_separator():
    result = analyze_receipt_lines(
        ["공급가액:2.182원 부가세:218원", "CNE 2.400원 (카드)"]
    )
    assert result["sources"]["A"] == 2400
    assert result["sources"]["C"] == 2400
    assert result["status"] == "confirmed"



def test_amount_pattern_accepts_space_thousands_separator():
    result = analyze_receipt_lines(
        ["1종 2 400원", "공급가액 2 182원", "부가세 218원"]
    )
    assert result["sources"]["A"] == 2400
    assert result["sources"]["B"] == 2400
    assert result["status"] == "confirmed"


def test_multi_pass_same_amount_stays_review_when_only_one_pattern_exists():
    lines = ["공급가액 1,482원", "부가세 18원"]
    result_a = analyze_receipt_lines(lines)
    result_b = analyze_receipt_lines(lines)
    merged = _merge_pass_results(
        [
            ("gray_psm6", lines, result_a),
            ("gray_psm11", lines, result_b),
        ]
    )
    assert merged["amount"] == 1500
    assert merged["status"] == "review"
    assert "복수 OCR 판독값 일치" in merged["note"]


def test_multi_pass_two_semantic_sources_confirm():
    a_lines = ["공급가액 1,482원", "부가세 18원"]
    b_lines = ["1종 1,500원"]
    merged = _merge_pass_results(
        [
            ("gray_psm6", a_lines, analyze_receipt_lines(a_lines)),
            ("gray_psm11", b_lines, analyze_receipt_lines(b_lines)),
        ]
    )
    assert merged["amount"] == 1500
    assert merged["sources"]["A"] == 1500
    assert merged["sources"]["B"] == 1500
    assert merged["status"] == "confirmed"


def test_separator_detection_finds_center_line():
    image = Image.new("RGB", (1000, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 80, 420, 520), outline="black", width=4)
    draw.rectangle((580, 80, 930, 520), outline="black", width=4)
    draw.rectangle((498, 30, 502, 570), fill="black")

    separators = _find_vertical_separators(image)
    assert separators
    assert abs(separators[0] - 500) <= 12


def test_separator_detection_does_not_split_single_receipt_border():
    image = Image.new("RGB", (700, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 70, 630, 830), outline="black", width=4)
    draw.rectangle((130, 180, 570, 230), outline="black", width=3)
    separators = _find_vertical_separators(image)
    assert separators == []



def test_report_print_sparse_lines_confirm_left_receipt():
    result = analyze_receipt_lines(
        [
            "1 종",
            "1,500%",
            "KEC",
            "73002",
            "CNE",
            "2008",
            "공 급 가 액 : 1.482 원 부가세 : 18 원",
        ]
    )
    assert result["sources"]["A"] == 1500
    assert result["sources"]["B"] == 1500
    assert result["amount"] == 1500
    assert result["status"] == "confirmed"


def test_report_print_sparse_lines_confirm_right_receipt():
    result = analyze_receipt_lines(
        [
            "1 종",
            "2,400원",
            "CNE",
            "24002",
            "공 급 가 액 : 2.182 원 부가세 : 218 원",
        ]
    )
    assert result["sources"]["A"] == 2400
    assert result["sources"]["B"] == 2400
    assert result["sources"]["C"] == 2400
    assert result["amount"] == 2400
    assert result["status"] == "confirmed"


def test_report_print_colon_thousands_separator_is_normalized():
    result = analyze_receipt_lines(
        ["1 종", "2:400원", "공 급 가 액 : 2.182 원 부가세 : 218 원"]
    )
    assert result["sources"]["A"] == 2400
    assert result["sources"]["B"] == 2400
    assert result["status"] == "confirmed"
