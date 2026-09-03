from app.utils.money import (
    is_likely_truncated_round_inr,
    repair_truncated_inr_amount,
    round_inr,
)


def test_round_inr_snaps_float_noise():
    assert round_inr(9999.999999999) == 10000
    assert round_inr(9999.995) == 10000
    assert round_inr(9999.4) == 9999
    assert round_inr(10000) == 10000


def test_truncated_inr_detection():
    assert is_likely_truncated_round_inr(9999) is True
    assert is_likely_truncated_round_inr(19999) is True
    assert is_likely_truncated_round_inr(4999) is False
    assert is_likely_truncated_round_inr(10000) is False


def test_repair_truncated_inr_amount():
    assert repair_truncated_inr_amount(9999) == 10000
    assert repair_truncated_inr_amount(10000) == 10000
    assert repair_truncated_inr_amount(4999) == 4999
