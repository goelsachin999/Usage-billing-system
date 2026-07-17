"""Pricing strategy interface.

Every billing model (flat, tiered, subscription+overage, and anything added
later) implements this same interface. The invoice assembler never knows
which concrete strategy it is talking to -- it only knows
``PricingStrategy.price(quantity, params)``. This is what lets a new billing
type be added as a new strategy class + a registry entry, with zero changes
to invoice or storage code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Mapping, NamedTuple


class PricingResult(NamedTuple):
    """The charge for a given quantity, plus a human-readable explanation
    of how it was derived (useful on invoice line items and in tests)."""

    amount: Decimal
    detail: str


class PricingStrategy(ABC):
    """A pricing model. Stateless: all the numbers it needs (rates, tiers,
    base fees, ...) come in via ``params``, which is resolved from external
    configuration -- never hardcoded in the strategy itself."""

    @abstractmethod
    def price(self, quantity: Decimal, params: Mapping[str, Any]) -> PricingResult:
        """Compute the charge for ``quantity`` units of usage, aggregated
        over the billing period, using the given config ``params``.

        Implementations must not mutate ``params`` and must treat all
        numeric config values as strings/Decimals -- never floats.
        """

    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        """Safely coerce a config value to Decimal. Config is expected to
        carry numbers as strings (or already as Decimal) specifically to
        avoid float round-trips; an int is also accepted for convenience."""
        if isinstance(value, Decimal):
            return value
        if isinstance(value, float):
            raise TypeError(
                "Pricing config values must not be floats (precision risk). "
                f"Got float {value!r}; use a str or Decimal instead."
            )
        return Decimal(str(value))
