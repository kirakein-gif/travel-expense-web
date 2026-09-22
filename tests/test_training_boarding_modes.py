from datetime import date

from app.services.travel_policy import calculate_allowances, transport_distance


BASE = dict(
    start_date=date(2026, 9, 1),
    end_date=date(2026, 9, 3),
    trip_type="training",
    public_vehicle=False,
    provided_meals_count=0,
    training_stay_mode="nonresidential",
    training_round_trips=3,
    training_meal_claim_count=0,
    training_meal_claim_amount=0,
    origin_sigungu="천안시",
    destination_sigungu="아산시",
)


def test_training_transport_is_one_round_trip_for_boarding_and_nonboarding():
    for stay_mode in ("nonresidential", "residential", "custom"):
        distance, count = transport_distance(
            one_way_km=20,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
            trip_type="training",
            round_trip=True,
            normal_stay_mode="nonresidential",
            training_stay_mode=stay_mode,
            training_round_trips=3,
        )
        assert distance == 40.0
        assert count == 1.0


def test_training_boarding_uses_institution_meal_claim_amount():
    result = calculate_allowances(
        training_boarding=True,
        **{**BASE, "training_meal_claim_amount": 42000},
    )
    assert result["daily_allowance"] == 50000
    assert result["meal_allowance"] == 42000
    assert "중간 1일 일비 없음" in result["daily_note"]
    assert "식비 청구액 42,000원" in result["meal_note"]


def test_training_nonboarding_lunch_count_reduces_one_third_per_lunch():
    result = calculate_allowances(
        training_boarding=False,
        **{**BASE, "training_meal_claim_count": 2},
    )
    assert result["daily_allowance"] == 62500
    assert result["meal_allowance"] == 58333
    assert "중간 1일 50%" in result["daily_note"]
    assert "중식 제공 2회 × 1/3" in result["meal_note"]


def test_training_nonboarding_no_lunch_gets_full_meal_allowance():
    result = calculate_allowances(training_boarding=False, **BASE)
    assert result["meal_allowance"] == 75000
    assert "중식 제공 없음" in result["meal_note"]
