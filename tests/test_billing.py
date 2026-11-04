from datetime import date
from decimal import Decimal

import pytest

from videomind.billing import Budget, deepseek_rate
from videomind.errors import BudgetError, ProviderError
from videomind.pipeline import preview


def test_budget_reservation_precedes_requests_and_is_retained():
    budget = Budget(Decimal("1"))
    with pytest.raises(BudgetError):
        budget.reserve(Decimal("0.4"))
    assert budget.reserved_usd == 0
    budget.authorized = True
    budget.reserve(Decimal("0.4"))
    with pytest.raises(BudgetError):
        budget.reserve(Decimal("0.7"))
    assert budget.reserved_usd == Decimal("0.4")


@pytest.mark.parametrize("day", [date(2026, 11, 3), date(2026, 11, 12)])
def test_expired_or_future_pricing_blocks_paid_execution(day):
    with pytest.raises(BudgetError):
        deepseek_rate("deepseek-flash", today=day)


def test_unknown_model_is_not_assumed_compatible():
    with pytest.raises(ProviderError):
        deepseek_rate("unknown-model")
    assert not deepseek_rate("deepseek-v4-pro").vision


def test_preview_limits_full_run_without_reading_keys(deepseek_settings):
    plan = preview(deepseek_settings, cloud=True)
    assert plan["requests_at_most"] == 4
    assert Decimal(plan["reserved_upper_usd"]) > 1
    assert plan["paid_requests_sent"] == 0
