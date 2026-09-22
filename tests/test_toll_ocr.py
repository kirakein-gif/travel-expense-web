from app.services.toll_ocr_service import analyze_receipt_lines


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
