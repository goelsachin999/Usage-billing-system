"""Registry mapping a config-driven ``billing_type`` string to the
``PricingStrategy`` that implements it.

This is the seam that makes pricing extensible: adding a new billing model
is exactly one ``registry.register("new_type", NewStrategy())`` call plus a
new strategy class -- never a modified if/switch statement in the
calculation engine.
"""

from __future__ import annotations

from typing import Dict

from .base import PricingStrategy
from .strategies import (
    FixedSubscriptionOverageStrategy,
    FlatPerUnitStrategy,
    GraduatedWithCapStrategy,
    TieredStrategy,
)


class PricingRegistry:
    def __init__(self) -> None:
        self._strategies: Dict[str, PricingStrategy] = {}

    def register(self, billing_type: str, strategy: PricingStrategy) -> None:
        self._strategies[billing_type] = strategy

    def get(self, billing_type: str) -> PricingStrategy:
        try:
            return self._strategies[billing_type]
        except KeyError:
            raise KeyError(
                f"No pricing strategy registered for billing_type={billing_type!r}. "
                f"Known types: {sorted(self._strategies)}"
            ) from None

    def known_types(self) -> list[str]:
        return sorted(self._strategies)


def default_registry() -> PricingRegistry:
    """The three billing models required by the spec, pre-registered.

    ``GraduatedWithCapStrategy`` is deliberately left unregistered here --
    it is registered live in the demo to show a fourth billing type being
    added without touching this function or any existing entry.
    """
    registry = PricingRegistry()
    registry.register("flat_per_unit", FlatPerUnitStrategy())
    registry.register("tiered", TieredStrategy())
    registry.register("fixed_subscription_overage", FixedSubscriptionOverageStrategy())
    return registry
