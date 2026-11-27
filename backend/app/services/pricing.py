"""Versioned LLM pricing calculator for transparent cost estimation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from app.models.entities import LLMModel
from app.providers.registry import provider_registry

PRICING_CATALOG_VERSION = "2026.11-official-v1"
_ONE_MILLION = Decimal("1000000")

# Prefix fallback table ONLY for official dated snapshots of known models
_PREFIX_PRICING_FALLBACK: list[tuple[str, str, Decimal, Decimal]] = [
    ("openai", "gpt-5-mini", Decimal("0.25"), Decimal("2.00")),
    ("openai", "gpt-5", Decimal("1.25"), Decimal("10.00")),
    ("openai", "gpt-4o-mini", Decimal("0.15"), Decimal("0.60")),
    ("openai", "gpt-4o", Decimal("2.50"), Decimal("10.00")),
    ("openai", "o3-mini", Decimal("1.10"), Decimal("4.40")),
    ("openai", "o1-mini", Decimal("1.10"), Decimal("4.40")),
    ("openai", "o1", Decimal("15.00"), Decimal("60.00")),
    ("openai", "gpt-4.1-mini", Decimal("0.40"), Decimal("1.60")),
    ("openai", "gpt-4.1", Decimal("2.00"), Decimal("8.00")),
    ("gemini", "gemini-3.8-flash", Decimal("0.35"), Decimal("2.80")),
    ("gemini", "gemini-3.1-flash-lite", Decimal("0.10"), Decimal("0.40")),
    ("gemini", "gemini-3-flash", Decimal("0.30"), Decimal("2.50")),
    ("gemini", "gemini-2.5-flash", Decimal("0.30"), Decimal("2.50")),
    ("gemini", "gemini-2.5-pro", Decimal("1.25"), Decimal("10.00")),
    ("gemini", "gemini-2.0-flash", Decimal("0.10"), Decimal("0.40")),
    ("gemini", "gemini-1.5-flash", Decimal("0.075"), Decimal("0.30")),
    ("gemini", "gemini-1.5-pro", Decimal("1.25"), Decimal("5.00")),
    ("anthropic", "claude-fable-5", Decimal("5.00"), Decimal("25.00")),
    ("anthropic", "claude-opus-5", Decimal("15.00"), Decimal("75.00")),
    ("anthropic", "claude-sonnet-5", Decimal("3.00"), Decimal("15.00")),
    ("anthropic", "claude-haiku-5", Decimal("0.80"), Decimal("4.00")),
    ("anthropic", "claude-sonnet-4", Decimal("3.00"), Decimal("15.00")),
    ("anthropic", "claude-opus-4", Decimal("15.00"), Decimal("75.00")),
    ("anthropic", "claude-3-7-sonnet", Decimal("3.00"), Decimal("15.00")),
    ("anthropic", "claude-3-5-sonnet", Decimal("3.00"), Decimal("15.00")),
    ("anthropic", "claude-3-5-haiku", Decimal("0.80"), Decimal("4.00")),
]


@dataclass(frozen=True)
class CostCalculation:
    estimated_cost_usd: Optional[Decimal]
    input_unit_price_per_1m: Optional[Decimal]
    output_unit_price_per_1m: Optional[Decimal]
    pricing_version: str
    pricing_available: bool
    is_estimated: bool = True


def calculate_estimated_cost(
    *,
    provider_key: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    db_model: Optional[LLMModel] = None,
) -> CostCalculation:
    """Calculate estimated USD cost using versioned per-model pricing.

    Never assumes uniform pricing across unknown models: if pricing is unavailable for a
    custom model, `estimated_cost_usd` is `None` and `pricing_available` is `False`.
    """
    in_rate: Optional[Decimal] = None
    out_rate: Optional[Decimal] = None
    version = PRICING_CATALOG_VERSION

    if db_model and db_model.input_price_per_1m is not None and db_model.output_price_per_1m is not None:
        in_rate = Decimal(str(db_model.input_price_per_1m))
        out_rate = Decimal(str(db_model.output_price_per_1m))
        version = db_model.pricing_version or PRICING_CATALOG_VERSION
    else:
        spec = provider_registry.get_model_spec(provider_key, model_id)
        if spec and spec.input_price_per_1m is not None and spec.output_price_per_1m is not None:
            in_rate = spec.input_price_per_1m
            out_rate = spec.output_price_per_1m
            version = spec.pricing_version
        else:
            normalized = model_id.lower().removeprefix("models/")
            for p_key, prefix, p_in, p_out in _PREFIX_PRICING_FALLBACK:
                if p_key == provider_key.lower() and normalized.startswith(prefix):
                    in_rate = p_in
                    out_rate = p_out
                    break

    if in_rate is None or out_rate is None:
        return CostCalculation(
            estimated_cost_usd=None,
            input_unit_price_per_1m=None,
            output_unit_price_per_1m=None,
            pricing_version=version,
            pricing_available=False,
            is_estimated=True,
        )

    in_cost = (Decimal(max(0, input_tokens)) * in_rate) / _ONE_MILLION
    out_cost = (Decimal(max(0, output_tokens)) * out_rate) / _ONE_MILLION
    total = (in_cost + out_cost).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)

    return CostCalculation(
        estimated_cost_usd=total,
        input_unit_price_per_1m=in_rate,
        output_unit_price_per_1m=out_rate,
        pricing_version=version,
        pricing_available=True,
        is_estimated=True,
    )
