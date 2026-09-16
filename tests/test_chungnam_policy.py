from app.services.chungnam_policy import (
    destination_distance_code,
    normalize_sigungu,
    resolve_special_destination,
    support_office_code,
)


def test_naepo_alias_resolves_to_fixed_code():
    special = resolve_special_destination("내포")
    assert special is not None
    assert special.code == "NAEPO"
    assert "선화로 22" in special.canonical_address


def test_cheonan_gu_maps_to_cheonan_support_office():
    assert normalize_sigungu("천안시 동남구") == "천안시"
    assert support_office_code("천안시 동남구") == "CHEONAN"


def test_nonsan_and_gyeryong_share_support_office():
    assert support_office_code("논산시") == "NONSAN_GYERYONG"
    assert support_office_code("계룡시") == "NONSAN_GYERYONG"


def test_special_destination_overrides_sigungu_destination_code():
    special = resolve_special_destination("충청남도교육청")
    assert destination_distance_code("홍성군", special) == "NAEPO"
