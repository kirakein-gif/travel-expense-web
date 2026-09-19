from app.browser.opinet_browser import normalize_opinet_sigungu


def test_provincial_city_district_collapses_to_parent_city():
    assert normalize_opinet_sigungu("경기도", "화성시 만세구") == "화성시"
    assert normalize_opinet_sigungu("경기도", "수원시 영통구") == "수원시"
    assert normalize_opinet_sigungu("충청북도", "청주시 상당구") == "청주시"


def test_metropolitan_district_is_preserved():
    assert normalize_opinet_sigungu("서울특별시", "강남구") == "강남구"


def test_sejong_is_single_opinet_region():
    assert normalize_opinet_sigungu("세종특별자치시", "조치원읍") == "세종"
