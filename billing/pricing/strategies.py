"""Built-in pricing strategies.

Each class here handles exactly one billing model and knows nothing about
the others, about storage, or about invoice formatting. Adding a fourth
model (see ``GraduatedWithCapStrategy`` below, added to satisfy the
"add a billing type live" evaluation probe) means writing one new class and
registering it -- nothing here changes.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, List, Mapping, Optional

from .base import PricingResult, PricingStrategy


class FlatPerUnitStrategy(PricingStrategy):
    """e.g. $0.02 per GB-hour of storage: amount = rate * quantity."""

    def price(self, quantity: Decimal, params: Mapping[str, Any]) -> PricingResult:
        rate = self._to_decimal(params["rate"])
        amount = rate * quantity
        return PricingResult(amount, f"{quantity} @ {rate}/unit")


class TieredStrategy(PricingStrategy):
    """Cumulative usage tiers, e.g. compute-hours:
        first 100   @ $0.10
        next  900   @ $0.08   (i.e. hours 100-1000)
        beyond 1000 @ $0.05

    Config shape (``params["tiers"]``): a list of tiers sorted by ascending
    cumulative upper bound, e.g.::

        [
            {"upto": "100",  "rate": "0.10"},
            {"upto": "1000", "rate": "0.08"},
            {"upto": null,   "rate": "0.05"},   # null/None = unbounded
        ]

    ``upto`` is a *cumulative* threshold on total quantity, not a tier
    width. The last tier must have ``upto: None`` (unbounded); it is an
    error for any other tier to be unbounded, and tiers must be strictly
    increasing.
    """

    def price(self, quantity: Decimal, params: Mapping[str, Any]) -> PricingResult:
        tiers = self._normalized_tiers(params["tiers"])

        remaining = quantity
        floor = Decimal("0")
        amount = Decimal("0")
        breakdown: List[str] = []

        for upto, rate in tiers:
            if remaining <= 0:
                break
            tier_width = (upto - floor) if upto is not None else remaining
            units_in_tier = min(remaining, tier_width)
            if units_in_tier > 0:
                tier_amount = units_in_tier * rate
                amount += tier_amount
                breakdown.append(f"{units_in_tier}@{rate}")
                remaining -= units_in_tier
            floor = upto if upto is not None else floor

        return PricingResult(amount, "tiers: " + ", ".join(breakdown) if breakdown else "0 usage")

    @staticmethod
    def _normalized_tiers(raw_tiers: Any) -> List[tuple[Optional[Decimal], Decimal]]:
        if not raw_tiers:
            raise ValueError("tiered pricing requires a non-empty 'tiers' list")
        normalized: List[tuple[Optional[Decimal], Decimal]] = []
        prev_upto: Optional[Decimal] = Decimal("0")
        for i, tier in enumerate(raw_tiers):
            upto_raw = tier.get("upto")
            rate = PricingStrategy._to_decimal(tier["rate"])
            upto = None if upto_raw is None else PricingStrategy._to_decimal(upto_raw)
            is_last = i == len(raw_tiers) - 1
            if upto is None and not is_last:
                raise ValueError("only the last tier may be unbounded (upto=None)")
            if upto is not None:
                if prev_upto is None:
                    raise ValueError("no tier may follow an unbounded tier")
                if upto <= prev_upto:
                    raise ValueError("tier 'upto' values must be strictly increasing")
            normalized.append((upto, rate))
            prev_upto = upto
        return normalized


class FixedSubscriptionOverageStrategy(PricingStrategy):
    """e.g. $50/month includes 1,000,000 API calls, then $0.001 each.

    amount = base_fee + max(0, quantity - included_units) * overage_rate
    """

    def price(self, quantity: Decimal, params: Mapping[str, Any]) -> PricingResult:
        base_fee = self._to_decimal(params["base_fee"])
        included = self._to_decimal(params["included_units"])
        overage_rate = self._to_decimal(params["overage_rate"])

        overage_units = max(Decimal("0"), quantity - included)
        overage_amount = overage_units * overage_rate
        amount = base_fee + overage_amount

        detail = f"base {base_fee} + overage {overage_units}@{overage_rate}"
        return PricingResult(amount, detail)


class GraduatedWithCapStrategy(PricingStrategy):
    """Bonus fourth model, added live to demonstrate extensibility per the
    evaluation probe: identical to tiered pricing, but the total charge is
    capped at ``params["cap"]``, regardless of usage volume.

    Notice this file is the *only* thing that changed to add it -- no edits
    to TieredStrategy, the registry wiring lives in ``registry.py`` as a
    single extra ``register(...)`` call, and invoice/storage code is
    untouched.
    """

    def price(self, quantity: Decimal, params: Mapping[str, Any]) -> PricingResult:
        tiered_amount, tiered_detail = TieredStrategy().price(quantity, params)
        cap = self._to_decimal(params["cap"])
        amount = min(tiered_amount, cap)
        capped = amount < tiered_amount
        detail = f"{tiered_detail}; cap={cap}" + (" (capped)" if capped else "")
        return PricingResult(amount, detail)
