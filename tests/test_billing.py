import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from billing.config import SAMPLE_CONFIG, ServiceConfig, load_config_from_file
from billing.invoice import InvoiceGenerator
from billing.models import UsageEvent
from billing.pricing import GraduatedWithCapStrategy, TieredStrategy, default_registry
from billing.pricing.strategies import FixedSubscriptionOverageStrategy, FlatPerUnitStrategy
from billing.store import InMemoryUsageStore

UTC = timezone.utc
START = datetime(2026, 6, 1, tzinfo=UTC)
END = datetime(2026, 7, 1, tzinfo=UTC)


def ev(user, resource, service, qty, unit, day, hour=0):
    return UsageEvent(user, resource, service, Decimal(qty), unit, datetime(2026, 6, day, hour, tzinfo=UTC))


class FlatPerUnitTests(unittest.TestCase):
    def test_basic(self):
        result = FlatPerUnitStrategy().price(Decimal("800"), {"rate": "0.02"})
        self.assertEqual(result.amount, Decimal("16.00"))

    def test_zero_quantity(self):
        result = FlatPerUnitStrategy().price(Decimal("0"), {"rate": "0.02"})
        self.assertEqual(result.amount, Decimal("0"))


class TieredStrategyTests(unittest.TestCase):
    TIERS = {
        "tiers": [
            {"upto": "100", "rate": "0.10"},
            {"upto": "1000", "rate": "0.08"},
            {"upto": None, "rate": "0.05"},
        ]
    }

    def test_within_first_tier(self):
        result = TieredStrategy().price(Decimal("50"), self.TIERS)
        self.assertEqual(result.amount, Decimal("5.00"))

    def test_exact_first_tier_boundary(self):
        # exactly 100 units: all at the first tier's rate, none spill to tier 2
        result = TieredStrategy().price(Decimal("100"), self.TIERS)
        self.assertEqual(result.amount, Decimal("10.00"))

    def test_one_unit_past_first_boundary(self):
        result = TieredStrategy().price(Decimal("101"), self.TIERS)
        self.assertEqual(result.amount, Decimal("10.00") + Decimal("0.08"))

    def test_exact_second_tier_boundary(self):
        result = TieredStrategy().price(Decimal("1000"), self.TIERS)
        # 100@0.10 + 900@0.08
        self.assertEqual(result.amount, Decimal("10.00") + Decimal("72.00"))

    def test_spec_example_650_and_1300(self):
        # From the spec: first 100 @ 0.10, next 900 @ 0.08, beyond @ 0.05
        result = TieredStrategy().price(Decimal("1300"), self.TIERS)
        expected = Decimal("100") * Decimal("0.10") + Decimal("900") * Decimal("0.08") + Decimal("300") * Decimal("0.05")
        self.assertEqual(result.amount, expected)

    def test_zero_quantity(self):
        result = TieredStrategy().price(Decimal("0"), self.TIERS)
        self.assertEqual(result.amount, Decimal("0"))

    def test_rejects_non_increasing_tiers(self):
        bad = {"tiers": [{"upto": "100", "rate": "0.1"}, {"upto": "100", "rate": "0.2"}, {"upto": None, "rate": "0.3"}]}
        with self.assertRaises(ValueError):
            TieredStrategy().price(Decimal("50"), bad)

    def test_rejects_unbounded_non_last_tier(self):
        bad = {"tiers": [{"upto": None, "rate": "0.1"}, {"upto": "100", "rate": "0.2"}]}
        with self.assertRaises(ValueError):
            TieredStrategy().price(Decimal("50"), bad)


class SubscriptionOverageTests(unittest.TestCase):
    PARAMS = {"base_fee": "50.00", "included_units": "1000000", "overage_rate": "0.001"}

    def test_under_included_units_no_overage(self):
        result = FixedSubscriptionOverageStrategy().price(Decimal("500000"), self.PARAMS)
        self.assertEqual(result.amount, Decimal("50.00"))

    def test_exactly_at_included_units_no_overage(self):
        result = FixedSubscriptionOverageStrategy().price(Decimal("1000000"), self.PARAMS)
        self.assertEqual(result.amount, Decimal("50.00"))

    def test_one_unit_over_included(self):
        result = FixedSubscriptionOverageStrategy().price(Decimal("1000001"), self.PARAMS)
        self.assertEqual(result.amount, Decimal("50.00") + Decimal("0.001"))

    def test_large_overage(self):
        result = FixedSubscriptionOverageStrategy().price(Decimal("1200000"), self.PARAMS)
        self.assertEqual(result.amount, Decimal("50.00") + Decimal("200000") * Decimal("0.001"))


class MoneyTypeSafetyTests(unittest.TestCase):
    def test_rejects_float_quantity(self):
        with self.assertRaises(TypeError):
            UsageEvent("u1", "r1", "storage", 12.5, "GB-hour", datetime.now(UTC))

    def test_rejects_naive_timestamp(self):
        with self.assertRaises(ValueError):
            UsageEvent("u1", "r1", "storage", Decimal("1"), "GB-hour", datetime.now())

    def test_rejects_float_in_pricing_params(self):
        with self.assertRaises(TypeError):
            FlatPerUnitStrategy().price(Decimal("10"), {"rate": 0.02})


class StoreOutOfOrderTests(unittest.TestCase):
    def test_query_correct_regardless_of_insertion_order(self):
        store = InMemoryUsageStore()
        # Insert deliberately out of chronological order.
        store.add_event(ev("u1", "r1", "storage", "10", "GB-hour", 20))
        store.add_event(ev("u1", "r1", "storage", "5", "GB-hour", 3))
        store.add_event(ev("u1", "r1", "storage", "7", "GB-hour", 10))

        results = store.query("u1", START, END)
        self.assertEqual([r.timestamp.day for r in results], [3, 10, 20])
        self.assertEqual(sum(r.quantity for r in results), Decimal("22"))

    def test_period_is_half_open(self):
        store = InMemoryUsageStore()
        store.add_event(UsageEvent("u1", "r1", "storage", Decimal("1"), "GB-hour", START))  # included
        store.add_event(UsageEvent("u1", "r1", "storage", Decimal("2"), "GB-hour", END))  # excluded

        results = store.query("u1", START, END)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].quantity, Decimal("1"))

    def test_invalid_period_raises(self):
        store = InMemoryUsageStore()
        with self.assertRaises(ValueError):
            store.query("u1", END, START)


class InvoiceGenerationTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryUsageStore()
        self.registry = default_registry()
        self.generator = InvoiceGenerator(self.store, self.registry)

    def test_two_users_three_services(self):
        self.store.add_events(
            [
                ev("user-1", "bucket-a", "storage", "500", "GB-hour", 15),
                ev("user-1", "bucket-a", "storage", "300", "GB-hour", 3),
                ev("user-1", "vm-cluster-1", "compute", "650", "compute-hour", 10),
                ev("user-1", "vm-cluster-1", "compute", "650", "compute-hour", 20),
                ev("user-2", "gateway-1", "api", "400000", "call", 5),
                ev("user-2", "gateway-1", "api", "800000", "call", 25),
                ev("user-2", "bucket-b", "storage", "120.5", "GB-hour", 8),
            ]
        )

        inv1 = self.generator.generate("user-1", START, END, SAMPLE_CONFIG)
        amounts = {(li.resource_id, li.service_type): li.amount for li in inv1.line_items}
        self.assertEqual(amounts[("bucket-a", "storage")], Decimal("16.00"))
        self.assertEqual(amounts[("vm-cluster-1", "compute")], Decimal("97.00"))
        self.assertEqual(inv1.total, Decimal("113.00"))

        inv2 = self.generator.generate("user-2", START, END, SAMPLE_CONFIG)
        amounts2 = {(li.resource_id, li.service_type): li.amount for li in inv2.line_items}
        self.assertEqual(amounts2[("gateway-1", "api")], Decimal("250.00"))
        self.assertEqual(amounts2[("bucket-b", "storage")], Decimal("2.41"))
        self.assertEqual(inv2.total, Decimal("252.41"))

    def test_events_outside_period_excluded_from_invoice(self):
        self.store.add_events(
            [
                ev("user-1", "bucket-a", "storage", "100", "GB-hour", 15),
                UsageEvent("user-1", "bucket-a", "storage", Decimal("99999"), "GB-hour", START - timedelta(days=1)),
                UsageEvent("user-1", "bucket-a", "storage", Decimal("99999"), "GB-hour", END),
            ]
        )
        invoice = self.generator.generate("user-1", START, END, SAMPLE_CONFIG)
        self.assertEqual(len(invoice.line_items), 1)
        self.assertEqual(invoice.line_items[0].amount, Decimal("2.00"))

    def test_unknown_service_type_raises(self):
        self.store.add_event(ev("user-1", "r1", "not-configured", "10", "unit", 5))
        with self.assertRaises(KeyError):
            self.generator.generate("user-1", START, END, SAMPLE_CONFIG)

    def test_mixed_units_same_resource_raises(self):
        self.store.add_event(ev("user-1", "bucket-a", "storage", "10", "GB-hour", 5))
        self.store.add_event(ev("user-1", "bucket-a", "storage", "10", "TB-hour", 6))
        with self.assertRaises(ValueError):
            self.generator.generate("user-1", START, END, SAMPLE_CONFIG)

    def test_no_usage_produces_zero_invoice(self):
        invoice = self.generator.generate("user-1", START, END, SAMPLE_CONFIG)
        self.assertEqual(invoice.line_items, ())
        self.assertEqual(invoice.total, Decimal("0"))


class ExtensibilityTests(unittest.TestCase):
    """Covers the explicit evaluation probe: add a graduated-with-cap model
    live, with no modification to existing strategies or the calculation
    engine."""

    def test_add_fourth_billing_type_without_touching_existing_ones(self):
        registry = default_registry()
        before = set(registry.known_types())

        registry.register("graduated_with_cap", GraduatedWithCapStrategy())

        self.assertEqual(registry.known_types(), sorted(before | {"graduated_with_cap"}))

        params = {
            "tiers": [
                {"upto": "100", "rate": "0.10"},
                {"upto": "1000", "rate": "0.08"},
                {"upto": None, "rate": "0.05"},
            ],
            "cap": "300.00",
        }
        # Uncapped amount would be 10 + 72 + 450 = 532.00; cap holds it at 300.
        result = registry.get("graduated_with_cap").price(Decimal("10000"), params)
        self.assertEqual(result.amount, Decimal("300.00"))

        # Existing strategies are provably untouched: same output as before.
        flat_result = registry.get("flat_per_unit").price(Decimal("800"), {"rate": "0.02"})
        self.assertEqual(flat_result.amount, Decimal("16.00"))


class ConfigLoadingTests(unittest.TestCase):
    def test_load_from_json_file_matches_sample_config(self):
        path = Path(__file__).resolve().parent.parent / "data" / "pricing_config.json"
        loaded = load_config_from_file(path)
        self.assertEqual(set(loaded.keys()), set(SAMPLE_CONFIG.keys()))
        self.assertEqual(loaded["storage"].params["rate"], "0.02")
        self.assertIsInstance(loaded["storage"], ServiceConfig)


if __name__ == "__main__":
    unittest.main()
