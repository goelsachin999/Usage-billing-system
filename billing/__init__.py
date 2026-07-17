"""Usage-based billing system.

Public entry points:
    - billing.models: domain data types (UsageEvent, LineItem, Invoice)
    - billing.store: usage persistence interface + in-memory implementation
    - billing.pricing: pricing strategy interface, built-in strategies, registry
    - billing.config: config-driven service -> pricing mapping
    - billing.invoice: invoice generation
"""
