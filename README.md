# Usage-Based Billing System

A small, dependency-free billing engine for cloud-style resource usage:
ingest usage events, price them under pluggable billing models, generate
per-user invoices. Built for the "Usage-Based Billing System" interview
screening exercise — standard library only, no external billing libraries.

## Quick start

```bash
python3 demo.py                       # runs the end-to-end demo
python3 -m unittest discover -s tests -v   # runs the test suite (27 tests)
```

Requires Python 3.10+ (uses `X | Y` union type hints and `datetime.timezone`).
No third-party packages — nothing to `pip install`.

## Layout

```
billing/
  models.py        UsageEvent, LineItem, ServiceSubtotal, Invoice (immutable dataclasses)
  store.py          UsageStore interface + InMemoryUsageStore
  config.py         ServiceConfig + loaders (dict / JSON file) — the config-driven layer
  invoice.py        InvoiceGenerator: aggregates usage, prices it, assembles an Invoice
  pricing/
    base.py          PricingStrategy interface + PricingResult
    strategies.py     FlatPerUnitStrategy, TieredStrategy,
                       FixedSubscriptionOverageStrategy, GraduatedWithCapStrategy
    registry.py        PricingRegistry: billing_type string -> strategy instance
data/
  pricing_config.json  Sample external pricing config (loadable via billing.config.load_config_from_file)
tests/
  test_billing.py   27 unit tests: strategy math, boundaries, ordering, invoicing, extensibility
demo.py             Driver: two users, three services, one invoice each, plus the
                    "add a 4th billing type live" extensibility probe
```

## How each requirement is met

**Usage tracking.** `UsageEvent` (frozen dataclass) carries user_id,
resource_id, service_type, quantity, unit, timestamp, plus a generated
`event_id`. `InMemoryUsageStore` scopes events per (user, resource) pair
implicitly via `resource_id`/`service_type` fields.

**Three pricing models, a fourth needs no changes to existing code.**
Each model is its own `PricingStrategy` subclass in `pricing/strategies.py`.
`InvoiceGenerator` never branches on billing type — it always does
`registry.get(service_config.billing_type).price(quantity, params)`. Adding
a model means: one new class, one `registry.register(...)` call. See
`GraduatedWithCapStrategy` and `demo.py::run_extensibility_probe`, which
registers it *at runtime* and prices a resource with it, without editing
`FlatPerUnitStrategy`, `TieredStrategy`, `FixedSubscriptionOverageStrategy`,
`registry.default_registry()`, `invoice.py`, or `store.py`.

**Invoice generation.** `InvoiceGenerator.generate(user_id, start, end,
config)` queries the store for `[start, end)`, aggregates quantity per
`(resource_id, service_type)` — tiers and subscription overage are
period-cumulative, so aggregation must happen *before* pricing, never
event-by-event — prices each group, and rolls line items up into
per-service subtotals and a grand total.

**Money — no floats.** `UsageEvent.quantity` and every pricing parameter
must be `Decimal` (or a string that becomes one); constructing an event
with a `float` quantity, or a strategy call with a `float` in `params`,
raises `TypeError` immediately. Final invoice amounts are quantized to
2 decimal places with `ROUND_HALF_UP`.

**Config-driven pricing.** `billing/config.py` + `data/pricing_config.json`
hold the service -> billing_type -> params mapping. A rate change or a new
*service* (reusing an existing billing type) is a JSON edit — no code
change. A genuinely new *billing type* is one strategy class + one registry
line (see above); the calculation engine itself never changes.

**Out-of-order ingestion.** `InMemoryUsageStore.query` always filters by
timestamp and re-sorts before returning, regardless of insertion order
(covered by `StoreOutOfOrderTests`).

**Persistence behind an interface.** `UsageStore` is an ABC;
`InMemoryUsageStore` is the only implementation, but `InvoiceGenerator`
depends only on the interface, so a database-backed store can be swapped in
without touching pricing or invoicing.

**Period boundaries.** Billing periods are half-open `[start, end)` — an
event exactly at `end` belongs to the next period, not this one
(`test_period_is_half_open`).

## Design choices worth flagging

- **Aggregate-then-price, not price-then-sum.** Tiered and
  subscription+overage pricing depend on *total* usage in the period, so
  events are summed per resource before a strategy ever sees them. Pricing
  a `$0.10`-per-hour first tier per individual event would double-grant the
  first-100-hours discount across every event in a period.
- **Mixed units on one resource are rejected**, not silently summed —
  summing `GB-hour` and `TB-hour` without conversion is a data integrity
  bug, not a pricing decision.
- **Strategies are stateless and pure** (`quantity`, `params`) -> `PricingResult`.
  This is what makes the registry a plain dict-like lookup and keeps every
  strategy trivially unit-testable in isolation from storage or invoicing.

## Known simplifications (explicitly out of scope per the spec)

- No real persistence layer (in-memory only, behind an interface).
- No currency conversion / multi-currency support (single fixed unit, per spec).
- No authentication, API layer, or invoice PDF rendering — `Invoice.render()`
  is a plain-text representation for demos/debugging.
