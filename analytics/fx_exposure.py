"""Расчёт валютной экспозиции портфеля."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

import concentration

DEFAULT_CURRENCY = "RUB"
DEFAULT_EXPOSURE_TYPE = "rub"
ALLOWED_CURRENCIES = {"RUB", "USD", "CNY", "EUR", "GOLD"}
ALLOWED_EXPOSURE_TYPES = {"rub", "fx_substitute", "fx_direct", "gold", "commodity_proxy"}
DIRECT_FX_EXPOSURE_TYPES = {"fx_substitute", "fx_direct", "gold"}


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_isin(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_currency(value: Any) -> str:
    normalized = str(value or DEFAULT_CURRENCY).strip().upper()
    return normalized if normalized in ALLOWED_CURRENCIES else DEFAULT_CURRENCY


def _normalize_exposure_type(value: Any) -> str:
    normalized = str(value or DEFAULT_EXPOSURE_TYPE).strip().lower()
    return normalized if normalized in ALLOWED_EXPOSURE_TYPES else DEFAULT_EXPOSURE_TYPE


def compute_fx_exposure(
    positions: list[dict],
    fx_overrides: Mapping[str, dict],
) -> dict:
    """Рассчитать валютную экспозицию по портфелю."""
    by_currency: dict[str, float] = defaultdict(float)
    by_exposure_type: dict[str, float] = defaultdict(float)
    rows: list[dict] = []
    total_value = 0.0

    for raw_row in positions or []:
        row = dict(raw_row)
        isin = _normalize_isin(row.get("isin"))
        override = fx_overrides.get(isin, {}) if isin else {}

        market_value = _to_float(row.get("value"))
        if market_value is None:
            market_value = concentration.calculate_position_market_value(row)
        if market_value is None or market_value <= 0:
            continue

        currency = _normalize_currency(override.get("currency"))
        exposure_type = _normalize_exposure_type(override.get("exposure_type"))
        name = str(row.get("name") or isin or "")

        total_value += market_value
        by_currency[currency] += market_value
        by_exposure_type[exposure_type] += market_value
        rows.append(
            {
                "isin": isin,
                "name": name,
                "value": market_value,
                "currency": currency,
                "exposure_type": exposure_type,
            }
        )

    commodity_proxy_value = by_exposure_type.get("commodity_proxy", 0.0)
    total_without_proxy = max(total_value - commodity_proxy_value, 0.0)
    fx_value = sum(by_exposure_type.get(kind, 0.0) for kind in DIRECT_FX_EXPOSURE_TYPES)

    if total_without_proxy > 0:
        fx_share = fx_value / total_without_proxy
        rub_share = max(total_without_proxy - fx_value, 0.0) / total_without_proxy
    else:
        fx_share = 0.0
        rub_share = 0.0

    return {
        "total_value": total_value,
        "by_currency": dict(by_currency),
        "by_exposure_type": dict(by_exposure_type),
        "fx_share": fx_share,
        "rub_share": rub_share,
        "rows": rows,
    }
