from types import SimpleNamespace

from app.services.pdf_service import _movement_place_labels


def _result(**overrides):
    values = {
        "origin_province": "충청남도",
        "origin_sigungu": "천안시 서북구",
        "province": "충청남도",
        "sigungu": "홍성군",
        "origin_support_office": "천안교육지원청",
        "destination_support_office": "홍성교육지원청",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_same_province_uses_local_unit_names():
    assert _movement_place_labels(_result()) == ("천안", "홍성")


def test_naepo_destination_is_labeled_naepo():
    result = _result(destination_support_office="내포")
    assert _movement_place_labels(result) == ("천안", "내포")


def test_naepo_origin_is_labeled_naepo():
    result = _result(
        origin_sigungu="홍성군",
        sigungu="천안시 서북구",
        origin_support_office="내포",
        destination_support_office="천안교육지원청",
    )
    assert _movement_place_labels(result) == ("내포", "천안")
