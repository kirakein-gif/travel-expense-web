from datetime import date

from app.services.travel_policy import calculate_allowances, transport_distance


BASE = dict(
    start_date=date(2026, 9, 1),
    end_date=date(2026, 9, 3),
    trip_type="training",
    public_vehicle=False,
    provided_meals_count=0,
    training_stay_mode="residential",
    training_round_trips=None,
    training_meal_claim_count=0,
    origin_sigungu="천안시",
    destination_sigungu="아산시",
)


def test_training_boarding_has_no_middle_day_daily_allowance():
    result = calculate_allowances(training_boarding=True, **BASE)
    assert result["daily_allowance"] == 50000
    assert "합숙" in result["daily_note"]
    assert "중간 1일 일비 없음" in result["daily_note"]


def test_training_nonboarding_gets_half_middle_day_even_when_self_lodging():
    result = calculate_allowances(training_boarding=False, **BASE)
    assert result["daily_allowance"] == 62500
    assert "비합숙" in result["daily_note"]
    assert "중간 1일 50%" in result["daily_note"]


def test_training_nonboarding_transport_is_independent_from_daily_rule():
    daily_commute = transport_distance(
        one_way_km=20,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        trip_type="training",
        round_trip=True,
        normal_stay_mode="nonresidential",
        training_stay_mode="nonresidential",
        training_round_trips=None,
    )
    self_lodging = transport_distance(
        one_way_km=20,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        trip_type="training",
        round_trip=True,
        normal_stay_mode="nonresidential",
        training_stay_mode="residential",
        training_round_trips=None,
    )
    assert daily_commute == (120.0, 3.0)
    assert self_lodging == (40.0, 1.0)
