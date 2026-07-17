"""Domain data types.

Design notes
------------
- All monetary and quantity values use ``decimal.Decimal``, never ``float``.
  Binary floating point cannot represent values like 0.1 exactly, which is
  unacceptable for anything that ends up on an invoice.
- ``UsageEvent`` is intentionally a plain, immutable record. It carries no
  billing logic -- pricing is resolved later, by service_type, via the
  pricing registry (see ``billing.pricing``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4


@dataclass(frozen=True)
class UsageEvent:
    """A single usage record scoped to a (user, resource) pair.

    Frozen/immutable: once ingested, a usage event is a fact and is never
    mutated. Correcting usage means recording a new (possibly negative)
    event, not editing history.
    """

    user_id: str
    resource_id: str
    service_type: str
    quantity: Decimal
    unit: str
    timestamp: datetime
    event_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not isinstance(self.quantity, Decimal):
            raise TypeError(
                f"UsageEvent.quantity must be a Decimal, got {type(self.quantity).__name__}. "
                "Construct it as Decimal('123.45'), never from a float literal."
            )
        if self.timestamp.tzinfo is None:
            raise ValueError(
                "UsageEvent.timestamp must be timezone-aware to avoid ambiguous "
                "billing-period boundaries."
            )
        if not self.user_id or not self.resource_id or not self.service_type:
            raise ValueError("user_id, resource_id, and service_type are required")


@dataclass(frozen=True)
class LineItem:
    """One priced row on an invoice: usage of a single resource, aggregated
    over the billing period, run through its service's pricing strategy."""

    resource_id: str
    service_type: str
    quantity: Decimal
    unit: str
    amount: Decimal
    detail: str = ""


@dataclass(frozen=True)
class ServiceSubtotal:
    service_type: str
    amount: Decimal


@dataclass(frozen=True)
class Invoice:
    """A generated invoice for one user over one billing period."""

    user_id: str
    period_start: datetime
    period_end: datetime
    line_items: tuple[LineItem, ...]
    service_subtotals: tuple[ServiceSubtotal, ...]
    total: Decimal

    def render(self) -> str:
        """Human-readable text rendering, useful for demos/debugging."""
        lines = [
            f"Invoice for {self.user_id}",
            f"Period: [{self.period_start.isoformat()}, {self.period_end.isoformat()})",
            "-" * 60,
        ]
        for li in self.line_items:
            lines.append(
                f"  {li.resource_id:<20} {li.service_type:<10} "
                f"{li.quantity} {li.unit:<12} -> {li.amount}"
                + (f"  ({li.detail})" if li.detail else "")
            )
        lines.append("-" * 60)
        for st in self.service_subtotals:
            lines.append(f"  Subtotal [{st.service_type}]: {st.amount}")
        lines.append("-" * 60)
        lines.append(f"TOTAL: {self.total}")
        return "\n".join(lines)
