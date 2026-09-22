from app.services.toll_ocr_service import extract_amount_candidates_from_lines


def test_extracts_multiple_toll_rows():
    lines = [
        "2026.09.18 천안 풍세 1,700원",
        "2026.09.18 풍세 남천안 2,400원",
        "2026.09.20 남천안 풍세 2,400원",
    ]
    result = extract_amount_candidates_from_lines(lines)
    recommended = [row["amount"] for row in result if row["recommended"]]
    assert 1700 in recommended
    assert recommended.count(2400) == 2


def test_excludes_date_year_but_keeps_toll_amount():
    result = extract_amount_candidates_from_lines(["2026-09-22 17:30 천안IC 3,200원"])
    amounts = [row["amount"] for row in result]
    assert 2026 not in amounts
    assert 3200 in amounts
