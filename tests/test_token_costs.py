from datetime import UTC, datetime
import pytest
from farol.token_costs import estimate, rate_cards


def test_six_reviews_an_hour_and_separate_output_cost():
    cost = estimate(3000, 500, 10, 50, 10)
    assert cost["per_review_usd"] == pytest.approx(.055)
    assert cost["per_hour_usd"] == pytest.approx(.33)
    assert cost["local_token_fee_usd"] == 0


def test_duration_is_included_in_completion_based_cadence():
    assert estimate(3000, 500, 10, 50, 10, 120)["reviews_per_hour_per_context"] == 5
    assert estimate(3000, 500, 10, 50, 10, 120, 10)["per_hour_usd"] == pytest.approx(2.75)


@pytest.mark.parametrize('bad', [float('nan'), -1, float('inf'), True])
def test_bad_inputs_rejected(bad):
    with pytest.raises(ValueError):
        estimate(bad, 500, 10, 50, 10)


def test_published_argon_price_change_is_explicit():
    before = rate_cards(datetime(2026, 11, 30, tzinfo=UTC))["rates"][-1]
    after = rate_cards(datetime(2026, 12, 1, tzinfo=UTC))["rates"][-1]
    assert (before['input'], before['output']) == (2, 10)
    assert (after['input'], after['output']) == (4, 20)
