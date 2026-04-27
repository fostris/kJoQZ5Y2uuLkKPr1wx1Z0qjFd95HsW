"""Расчёты облигационных метрик портфеля."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from concentration import BOND_ASSET_TYPES, calculate_position_market_value


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(converted):
        return None
    return converted


def _parse_date(value: str | date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        return None

    raw = value.strip()
    if not raw:
        return None

    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    return None


def calculate_days_to_maturity(
    maturity_date: str | date | datetime | None,
    as_of_date: date | datetime | None,
) -> int | None:
    """Количество дней до погашения (не меньше нуля)."""
    maturity = _parse_date(maturity_date)
    as_of = _parse_date(as_of_date)
    if maturity is None or as_of is None:
        return None
    return max((maturity - as_of).days, 0)


def calculate_years_to_maturity(
    maturity_date: str | date | datetime | None,
    as_of_date: date | datetime | None,
) -> float | None:
    """Срок до погашения в годах."""
    days_to_maturity = calculate_days_to_maturity(maturity_date, as_of_date)
    if days_to_maturity is None:
        return None
    return days_to_maturity / 365.25


def calculate_weighted_ytm(
    positions: Iterable[Mapping[str, Any]],
    ytm_by_isin: Mapping[str, float | None],
    bond_asset_types: tuple[str, ...] = BOND_ASSET_TYPES,
) -> dict[str, Any]:
    """Рассчитать средневзвешенную YTM и покрытие YTM по стоимости облигаций."""
    total_portfolio_value = 0.0
    total_bond_value = 0.0
    covered_bond_value = 0.0
    weighted_sum = 0.0
    missing_positions: list[dict[str, Any]] = []
    missing_count = 0

    for position in positions:
        market_value = calculate_position_market_value(position)
        if market_value is None or market_value <= 0:
            continue

        total_portfolio_value += market_value

        if position.get("asset_type") not in bond_asset_types:
            continue

        total_bond_value += market_value

        isin = str(position.get("isin") or "")
        ytm = _to_float(ytm_by_isin.get(isin)) if isin else None
        if ytm is None:
            missing_count += 1
            missing_positions.append(
                {
                    "name": str(position.get("name") or "—"),
                    "isin": isin or "—",
                    "market_value": market_value,
                }
            )
            continue

        covered_bond_value += market_value
        weighted_sum += market_value * ytm

    coverage_pct = (covered_bond_value / total_bond_value) if total_bond_value > 0 else None
    weighted_ytm = (weighted_sum / covered_bond_value) if covered_bond_value > 0 else None

    if total_portfolio_value > 0:
        for row in missing_positions:
            row["portfolio_share"] = row["market_value"] / total_portfolio_value
    else:
        for row in missing_positions:
            row["portfolio_share"] = None

    missing_positions.sort(key=lambda row: row["market_value"], reverse=True)

    return {
        "weighted_ytm": weighted_ytm,
        "covered_value": covered_bond_value,
        "total_bond_value": total_bond_value,
        "coverage_pct": coverage_pct,
        "missing_count": missing_count,
        "missing_positions": missing_positions,
        # Backward-compatible aliases.
        "coverage": coverage_pct,
        "covered_bond_value": covered_bond_value,
    }


def calculate_weighted_years_to_maturity(
    positions: Iterable[Mapping[str, Any]],
    maturity_by_isin: Mapping[str, str | date | datetime | None],
    as_of_date: date | datetime | None,
    bond_asset_types: tuple[str, ...] = BOND_ASSET_TYPES,
) -> dict[str, float | int | None]:
    """Средневзвешенный срок до погашения облигаций по рыночной стоимости."""
    total_bond_value = 0.0
    covered_value = 0.0
    weighted_sum = 0.0
    missing_count = 0

    for position in positions:
        if position.get("asset_type") not in bond_asset_types:
            continue

        market_value = calculate_position_market_value(position)
        if market_value is None or market_value <= 0:
            continue

        total_bond_value += market_value

        isin = str(position.get("isin") or "")
        maturity_date = maturity_by_isin.get(isin) if isin else None
        years_to_maturity = calculate_years_to_maturity(maturity_date, as_of_date)
        if years_to_maturity is None:
            missing_count += 1
            continue

        covered_value += market_value
        weighted_sum += market_value * years_to_maturity

    coverage_pct = (covered_value / total_bond_value) if total_bond_value > 0 else None
    weighted_years_to_maturity = (weighted_sum / covered_value) if covered_value > 0 else None

    return {
        "weighted_years_to_maturity": weighted_years_to_maturity,
        "covered_value": covered_value,
        "total_bond_value": total_bond_value,
        "coverage_pct": coverage_pct,
        "missing_count": missing_count,
    }
