"""Расчёты денежных потоков купонов."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any, Iterable, Mapping


def _row_get(row, key: str, default=None):
    if row is None:
        return default
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return default


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_date(value: Any) -> date | None:
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


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + (month_index // 12)
    month = (month_index % 12) + 1
    return date(year, month, 1)


def build_coupon_cashflow_by_month(
    coupons: Iterable[Mapping[str, Any]],
    positions: Iterable[Mapping[str, Any]],
    months: int = 12,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    """Построить ожидаемый поток купонов по месяцам на заданное окно."""
    if months <= 0:
        return {
            "months": [],
            "total_income": 0.0,
            "total_payments": 0,
            "start_date": None,
            "end_date": None,
        }

    as_of = as_of_date or date.today()
    window_start = _month_start(as_of)
    window_end = _add_months(window_start, months)

    qty_by_isin: dict[str, float] = {}
    for position in positions:
        isin = str(_row_get(position, "isin", "") or "")
        if not isin:
            continue
        qty = _to_float(_row_get(position, "qty"))
        if qty is None or qty <= 0:
            continue
        qty_by_isin[isin] = qty

    month_income: dict[date, float] = defaultdict(float)
    month_count: dict[date, int] = defaultdict(int)
    month_bonds: dict[date, set[str]] = defaultdict(set)

    for coupon in coupons:
        coupon_date = _to_date(_row_get(coupon, "coupon_date"))
        if coupon_date is None:
            continue
        if coupon_date < as_of or coupon_date >= window_end:
            continue

        month = _month_start(coupon_date)
        isin = str(_row_get(coupon, "isin", "") or "")
        name = str(_row_get(coupon, "name", "") or isin or "—")

        qty = qty_by_isin.get(isin)
        if qty is None:
            qty = _to_float(_row_get(coupon, "qty"))

        coupon_amount = _to_float(_row_get(coupon, "coupon_amount"))
        expected_income = _to_float(_row_get(coupon, "expected_income"))

        if coupon_amount is not None and qty is not None:
            income = coupon_amount * qty
        elif expected_income is not None:
            income = expected_income
        else:
            continue

        month_income[month] += income
        month_count[month] += 1
        month_bonds[month].add(name)

    rows: list[dict[str, Any]] = []
    for i in range(months):
        month = _add_months(window_start, i)
        bonds = sorted(month_bonds.get(month, set()))
        rows.append(
            {
                "month": month.strftime("%Y-%m"),
                "income": float(month_income.get(month, 0.0)),
                "payments_count": int(month_count.get(month, 0)),
                "bonds": bonds,
                "bonds_text": ", ".join(bonds) if bonds else "нет данных",
            }
        )

    return {
        "months": rows,
        "total_income": float(sum(row["income"] for row in rows)),
        "total_payments": int(sum(row["payments_count"] for row in rows)),
        "start_date": window_start,
        "end_date": window_end,
    }

