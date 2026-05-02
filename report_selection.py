"""Чистая логика выбора активного отчёта в UI."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping


def _parse_period_end(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def resolve_default_report_id(reports: list[Mapping[str, Any]]) -> int | None:
    """Вернуть id самого свежего отчёта (max(period_end), при равенстве max(id))."""
    best_id: int | None = None
    best_date: date | None = None
    for row in reports or []:
        report_id_raw = row.get("id")
        period_end = _parse_period_end(row.get("period_end"))
        if report_id_raw in (None, "") or period_end is None:
            continue
        report_id = int(report_id_raw)
        if best_date is None or period_end > best_date or (period_end == best_date and report_id > int(best_id or -1)):
            best_date = period_end
            best_id = report_id
    return best_id


def should_switch_to_new_report(
    new_period_end: str,
    existing_max_period_end: str | None,
) -> bool:
    """Нужно ли автопереключение на только что импортированный отчёт."""
    new_date = _parse_period_end(new_period_end)
    if new_date is None:
        return False
    if existing_max_period_end is None:
        return True
    existing_date = _parse_period_end(existing_max_period_end)
    if existing_date is None:
        return True
    return new_date >= existing_date
