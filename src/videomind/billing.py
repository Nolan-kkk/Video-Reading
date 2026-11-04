"""Conservative pre-request reservations, not an exact provider invoice."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from videomind.errors import BudgetError, ProviderError
from videomind.providers.base import Usage

PRICE_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing/"
PRICE_CHECKED_ON = date(2026, 11, 4)
PRICE_VALID_THROUGH = date(2026, 11, 11)
# The full model context is reserved for EVERY request, deliberately overestimating
# prompt/image usage rather than treating character counts as exact token counts.
INPUT_TOKEN_CEILING = 1_048_576


@dataclass(frozen=True)
class RateCard:
    input_per_million: Decimal
    output_per_million: Decimal
    vision: bool

    def upper_cost(self, max_output_tokens: int) -> Decimal:
        return (
            self.input_per_million * INPUT_TOKEN_CEILING
            + self.output_per_million * max_output_tokens
        ) / 1_000_000


def utc_today() -> date:
    return datetime.now(UTC).date()


def deepseek_rate(model: str, *, today: date | None = None) -> RateCard:
    current = today or utc_today()
    if not PRICE_CHECKED_ON <= current <= PRICE_VALID_THROUGH:
        raise BudgetError("价格快照已过期或系统日期异常；请核对官方价格并更新费率后再调用。")
    # Peak, cache-miss rates; never assume a discount or prompt-cache hit.
    rates = {
        "deepseek-flash": RateCard(Decimal("0.30"), Decimal("1.20"), True),
        "deepseek-v4-pro": RateCard(Decimal("1.32"), Decimal("3.96"), False),
    }
    if model not in rates:
        raise ProviderError("该 DeepSeek 模型尚未核验能力及价格，禁止付费调用。")
    return rates[model]


@dataclass
class Budget:
    limit_usd: Decimal
    authorized: bool = False
    reserved_usd: Decimal = Decimal("0")
    usage: list[Usage] = field(default_factory=list)

    def check_total(self, cost: Decimal) -> None:
        if not cost.is_finite() or cost < 0 or cost + self.reserved_usd > self.limit_usd:
            raise BudgetError("保守费用预留超过预算；请减少关键帧/请求数或调整用户预算。")

    def reserve(self, cost: Decimal) -> None:
        if not self.authorized:
            raise BudgetError("尚未允许付费请求；先查看 --dry-run，再显式开启云端并确认费用。")
        self.check_total(cost)
        # Keep the reservation even after a timeout: the provider may have billed it.
        self.reserved_usd += cost
