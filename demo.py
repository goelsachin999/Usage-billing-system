"""Driver / demo script.

Run with: python demo.py

Demonstrates:
  1. Two users, three services (storage/flat, compute/tiered, api/subscription+overage).
  2. Usage events ingested out of order, some outside the billing period (must be excluded).
  3. Invoice generation for each user.
  4. The extensibility probe: registering a 4th billing type
     ("graduated_with_cap") live, with no changes to existing pricing
     strategies, the registry defaults, invoice.py, or store.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from billing.config import SAMPLE_CONFIG, ServiceConfig, load_config_from_dict
from billing.invoice import InvoiceGenerator
from billing.models import UsageEvent
from billing.pricing import GraduatedWithCapStrategy, default_registry
from billing.store import InMemoryUsageStore

PERIOD_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
PERIOD_END = datetime(2026, 7, 1, tzinfo=timezone.utc)


def dt(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 6, day, hour, tzinfo=timezone.utc)


def build_demo_events() -> list[UsageEvent]:
    events = [
        # --- user-1: storage (flat) + compute (tiered) ---
        # Deliberately out of order: the 15th arrives before the 3rd.
        UsageEvent("user-1", "bucket-a", "storage", Decimal("500"), "GB-hour", dt(15)),
        UsageEvent("user-1", "bucket-a", "storage", Decimal("300"), "GB-hour", dt(3)),
        UsageEvent("user-1", "vm-cluster-1", "compute", Decimal("650"), "compute-hour", dt(10)),
        UsageEvent("user-1", "vm-cluster-1", "compute", Decimal("650"), "compute-hour", dt(20)),
        # Out-of-period event: must NOT appear on the June invoice.
        UsageEvent("user-1", "bucket-a", "storage", Decimal("9999"), "GB-hour", dt(2) - timedelta(days=40)),
        UsageEvent("user-1", "bucket-a", "storage", Decimal("9999"), "GB-hour", PERIOD_END),

        # --- user-2: api (subscription + overage) + storage (flat) ---
        UsageEvent("user-2", "gateway-1", "api", Decimal("400000"), "call", dt(5)),
        UsageEvent("user-2", "gateway-1", "api", Decimal("800000"), "call", dt(25)),
        UsageEvent("user-2", "bucket-b", "storage", Decimal("120.5"), "GB-hour", dt(8)),
    ]
    return events


def run_core_demo() -> None:
    store = InMemoryUsageStore()
    store.add_events(build_demo_events())

    registry = default_registry()
    generator = InvoiceGenerator(store, registry)

    for user_id in ("user-1", "user-2"):
        invoice = generator.generate(user_id, PERIOD_START, PERIOD_END, SAMPLE_CONFIG)
        print(invoice.render())
        print()


def run_extensibility_probe() -> None:
    """"Add a graduated-with-cap model live" -- registered here, at demo
    time, without editing registry.py, invoice.py, store.py, or any
    existing strategy class."""
    print("=== Extensibility probe: adding graduated_with_cap live ===")

    store = InMemoryUsageStore()
    store.add_event(
        UsageEvent("user-3", "vm-cluster-9", "compute-capped", Decimal("10000"), "compute-hour", dt(12))
    )

    registry = default_registry()
    registry.register("graduated_with_cap", GraduatedWithCapStrategy())  # <-- the entire change

    config = dict(SAMPLE_CONFIG)
    config["compute-capped"] = ServiceConfig(
        service_type="compute-capped",
        billing_type="graduated_with_cap",
        unit="compute-hour",
        params={
            "tiers": [
                {"upto": "100", "rate": "0.10"},
                {"upto": "1000", "rate": "0.08"},
                {"upto": None, "rate": "0.05"},
            ],
            "cap": "300.00",
        },
    )

    generator = InvoiceGenerator(store, registry)
    invoice = generator.generate("user-3", PERIOD_START, PERIOD_END, config)
    print(invoice.render())
    print(f"\nknown billing types after live registration: {registry.known_types()}")


if __name__ == "__main__":
    run_core_demo()
    run_extensibility_probe()
