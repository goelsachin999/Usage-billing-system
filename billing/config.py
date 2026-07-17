"""Config-driven mapping from service_type -> pricing model + parameters.

This is the only place a new service or a rate change touches. It can be
loaded from a JSON file (see ``load_config_from_file``) or built as a plain
dict in code (see ``load_config_from_dict``) -- either way, the calculation
engine (``billing.pricing``) and invoice assembler (``billing.invoice``)
never change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping


@dataclass(frozen=True)
class ServiceConfig:
    service_type: str
    billing_type: str
    unit: str
    params: Mapping[str, Any]


def load_config_from_dict(raw: Mapping[str, Any]) -> Dict[str, ServiceConfig]:
    """``raw`` shape::

        {
          "storage": {
            "billing_type": "flat_per_unit",
            "unit": "GB-hour",
            "params": {"rate": "0.02"}
          },
          ...
        }
    """
    config: Dict[str, ServiceConfig] = {}
    for service_type, entry in raw.items():
        config[service_type] = ServiceConfig(
            service_type=service_type,
            billing_type=entry["billing_type"],
            unit=entry["unit"],
            params=entry.get("params", {}),
        )
    return config


def load_config_from_file(path: str | Path) -> Dict[str, ServiceConfig]:
    """Load pricing config from a JSON file on disk. Numbers must be encoded
    as JSON strings (e.g. ``"0.02"``) so they parse straight into Decimal
    without a float round-trip -- see PricingStrategy._to_decimal.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return load_config_from_dict(raw)


# Sample configuration covering all three required billing models. Mirrors
# data/pricing_config.json -- kept here too so the demo/tests have no
# filesystem dependency.
SAMPLE_CONFIG: Dict[str, ServiceConfig] = load_config_from_dict(
    {
        "storage": {
            "billing_type": "flat_per_unit",
            "unit": "GB-hour",
            "params": {"rate": "0.02"},
        },
        "compute": {
            "billing_type": "tiered",
            "unit": "compute-hour",
            "params": {
                "tiers": [
                    {"upto": "100", "rate": "0.10"},
                    {"upto": "1000", "rate": "0.08"},
                    {"upto": None, "rate": "0.05"},
                ]
            },
        },
        "api": {
            "billing_type": "fixed_subscription_overage",
            "unit": "call",
            "params": {
                "base_fee": "50.00",
                "included_units": "1000000",
                "overage_rate": "0.001",
            },
        },
    }
)
