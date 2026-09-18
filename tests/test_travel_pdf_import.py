from app.services import travel_pdf_import as parser


def test_approval_pdf_accepts_split_date_markers(monkeypatch):
    chunks = [
        {"x": 20.0, "y": 578.0, "text": "지방교육행정"},
        {"x": 20.0, "y": 564.0, "text": "사무관"},
        {"x": 120.0, "y": 564.0, "text": "장영자"},
        {"x": 170.0, "y": 578.0, "text": "교육행정통합을 위한"},
        {"x": 170.0, "y": 564.0, "text": "업무 협의"},
        {"x": 319.1, "y": 580.4, "text": "2026.08.27"},
        {"x": 369.6, "y": 580.4, "text": "부터"},
        {"x": 293.0, "y": 565.5, "text": "("},
        {"x": 308.3, "y": 565.5, "text": "06:30~18:00"},
        {"x": 377.1, "y": 565.5, "text": ")"},
        {"x": 319.1, "y": 548.6, "text": "2026.08.27"},
        {"x": 369.6, "y": 548.6, "text": "까지"},
        {"x": 392.5, "y": 577.5, "text": "전남광주통합특별시교육청"},
        {"x": 397.5, "y": 563.5, "text": "전남청사(무안)"},
        {"x": 495.7, "y": 563.5, "text": "장영자"},
    ]
    monkeypatch.setattr(parser, "_page_chunks", lambda page: chunks)

    rows = parser._records_from_page(object(), 1, "approval")

    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "장영자"
    assert row["position"] == "지방교육행정사무관"
    assert row["start_date"] == "2026-08-27"
    assert row["end_date"] == "2026-08-27"
    assert row["time"] == "06:30~18:00"
    assert row["destination"] == "전남광주통합특별시교육청전남청사(무안)"


def test_period_marker_keeps_combined_text():
    chunks = [
        {"x": 320.0, "y": 580.0, "text": "2026.08.27부터"},
        {"x": 320.0, "y": 548.0, "text": "2026.08.27까지"},
    ]
    period_range = (285.0, 390.0)

    starts = parser._period_date_markers(
        chunks, period_range, "부터", parser._DATE_START_RE
    )
    ends = parser._period_date_markers(
        chunks, period_range, "까지", parser._DATE_END_RE
    )

    assert len(starts) == 1
    assert len(ends) == 1
    assert starts[0]["text"] == "2026.08.27부터"
    assert ends[0]["text"] == "2026.08.27까지"
