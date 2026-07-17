"""Invoice assembly.

Deliberately the only layer that knows about *all* of usage storage,
pricing, and formatting -- and even it only orchestrates them, it doesn't
implement any of their logic. Ingestion (``billing.store``), pricing
(``billing.pricing``), and assembly (here) stay independently testable and
independently replaceable.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Mapping, Tuple

from .config import ServiceConfig
from .models import Invoice, LineItem, ServiceSubtotal, UsageEvent
from .pricing.registry import PricingRegistry
from .store import UsageStore

CENT = Decimal("0.01")


def _round_money(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


class InvoiceGenerator:
    def __init__(self, store: UsageStore, registry: PricingRegistry) -> None:
        self._store = store
        self._registry = registry

    def generate(
        self,
        user_id: str,
        start: datetime,
        end: datetime,
        config: Mapping[str, ServiceConfig],
    ) -> Invoice:
        events = self._store.query(user_id, start, end)
        grouped = self._group_by_resource(events)

        line_items: list[LineItem] = []
        for (resource_id, service_type), (quantity, unit) in sorted(grouped.items()):
            service_config = self._resolve_service_config(service_type, config)
            strategy = self._registry.get(service_config.billing_type)
            result = strategy.price(quantity, service_config.params)
            line_items.append(
                LineItem(
                    resource_id=resource_id,
                    service_type=service_type,
                    quantity=quantity,
                    unit=unit,
                    amount=_round_money(result.amount),
                    detail=result.detail,
                )
            )

        subtotals_by_service: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for li in line_items:
            subtotals_by_service[li.service_type] += li.amount
        service_subtotals = tuple(
            ServiceSubtotal(service_type=s, amount=amt)
            for s, amt in sorted(subtotals_by_service.items())
        )

        total = sum((st.amount for st in service_subtotals), Decimal("0"))

        return Invoice(
            user_id=user_id,
            period_start=start,
            period_end=end,
            line_items=tuple(line_items),
            service_subtotals=service_subtotals,
            total=total,
        )

    @staticmethod
    def _group_by_resource(
        events: list[UsageEvent],
    ) -> Dict[Tuple[str, str], Tuple[Decimal, str]]:
        """Sum quantity per (resource_id, service_type). Tiered and
        subscription+overage pricing are inherently period-cumulative, so
        usage must be aggregated *before* pricing runs, never priced event
        by event and summed afterwards -- that would double-count tier
        thresholds and the subscription base fee.
        """
        totals: Dict[Tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
        units: Dict[Tuple[str, str], str] = {}
        for event in events:
            key = (event.resource_id, event.service_type)
            totals[key] += event.quantity
            existing_unit = units.get(key)
            if existing_unit is not None and existing_unit != event.unit:
                raise ValueError(
                    f"Resource {event.resource_id!r} (service {event.service_type!r}) has "
                    f"mixed units in one billing period: {existing_unit!r} vs {event.unit!r}"
                )
            units[key] = event.unit
        return {key: (qty, units[key]) for key, qty in totals.items()}

    @staticmethod
    def _resolve_service_config(
        service_type: str, config: Mapping[str, ServiceConfig]
    ) -> ServiceConfig:
        try:
            return config[service_type]
        except KeyError:
            raise KeyError(
                f"No pricing configuration for service_type={service_type!r}. "
                f"Configured services: {sorted(config)}"
            ) from None
