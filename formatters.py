"""Форматирование чисел для UI."""

from __future__ import annotations

import math


def _is_nan(value) -> bool:
    try:
        return math.isnan(value)
    except (TypeError, ValueError):
        return False


def format_rub(value: float | int | None, dash: str = "—") -> str:
    """Формат суммы в рублях с пробелом-разделителем и запятой."""
    if value is None or _is_nan(value):
        return dash
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def format_percent(value: float | None, decimals: int = 1, dash: str = "—") -> str:
    """Формат доли/процента; для None возвращает dash."""
    if value is None or _is_nan(value):
        return dash
    return f"{value:.{decimals}f}%"


def format_nullable(value: float | None, pattern: str = "{:.2f}", dash: str = "—") -> str:
    """Формат nullable-чисел по pattern."""
    if value is None or _is_nan(value):
        return dash
    return pattern.format(value)
