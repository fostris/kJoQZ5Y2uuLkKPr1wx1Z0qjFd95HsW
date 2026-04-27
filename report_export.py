"""HTML export helpers for portfolio summary reports."""

from __future__ import annotations

from html import escape
from typing import Any, Mapping, Sequence


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_currency(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "нет данных"
    return f"{number:,.2f} ₽"


def _fmt_pct(value: Any, scale_100: bool = False) -> str:
    number = _to_float(value)
    if number is None:
        return "нет данных"
    number = number * 100.0 if scale_100 else number
    return f"{number:.2f}%"


def _build_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    if not rows:
        return "<p>Нет данных.</p>"

    head_html = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return (
        "<table border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse;width:100%;'>"
        f"<thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table>"
    )


def build_portfolio_summary_html(
    report_date: str,
    portfolio_value: Any,
    bond_value: Any,
    weighted_ytm: Any,
    ytm_coverage_pct: Any,
    largest_positions: Sequence[Mapping[str, Any]],
    largest_issuers: Sequence[Mapping[str, Any]],
    warnings: Sequence[Mapping[str, Any] | str],
    coupon_cashflow_12m: Mapping[str, Any],
    maturity_ladder: Mapping[str, Any],
) -> str:
    """Build short HTML report with explicit missing-data notes."""
    missing_notes: list[str] = []

    if _to_float(weighted_ytm) is None:
        missing_notes.append("Средневзвешенная YTM недоступна.")
    if _to_float(ytm_coverage_pct) is None:
        missing_notes.append("Покрытие YTM недоступно.")
    if not largest_positions:
        missing_notes.append("Нет данных для блока крупнейших позиций.")
    if not largest_issuers:
        missing_notes.append("Нет данных для блока крупнейших эмитентов.")

    position_rows = [
        (
            str(row.get("name") or "—"),
            str(row.get("isin") or "—"),
            _fmt_pct(row.get("position_share"), scale_100=True),
            _fmt_currency(row.get("market_value")),
        )
        for row in largest_positions[:5]
    ]

    issuer_rows = [
        (
            str(row.get("issuer") or "—"),
            _fmt_pct(row.get("issuer_share"), scale_100=True),
            _fmt_currency(row.get("market_value")),
        )
        for row in largest_issuers[:5]
    ]

    warning_lines: list[str] = []
    for item in warnings:
        if isinstance(item, Mapping):
            severity = str(item.get("severity") or "info")
            text = str(item.get("text") or "")
            if text:
                warning_lines.append(f"[{severity}] {text}")
        else:
            text = str(item or "")
            if text:
                warning_lines.append(text)

    cashflow_months = coupon_cashflow_12m.get("months") if isinstance(coupon_cashflow_12m, Mapping) else []
    cashflow_rows = [
        (
            str(row.get("month") or "—"),
            _fmt_currency(row.get("income")),
            str(int(_to_float(row.get("payments_count")) or 0)),
        )
        for row in (cashflow_months or [])
    ]
    cashflow_total = _fmt_currency(coupon_cashflow_12m.get("total_income") if isinstance(coupon_cashflow_12m, Mapping) else None)

    ladder_years = maturity_ladder.get("years") if isinstance(maturity_ladder, Mapping) else []
    ladder_rows = [
        (
            str(int(_to_float(row.get("year")) or 0)),
            _fmt_currency(row.get("maturity_return")),
            _fmt_currency(row.get("amortization_return")),
            _fmt_currency(row.get("total_return")),
        )
        for row in (ladder_years or [])
    ]

    missing_html = (
        "<ul>" + "".join(f"<li>{escape(note)}</li>" for note in missing_notes) + "</ul>"
        if missing_notes
        else "<p>Критичных пробелов данных не обнаружено.</p>"
    )

    warnings_html = (
        "<ul>" + "".join(f"<li>{escape(line)}</li>" for line in warning_lines) + "</ul>"
        if warning_lines
        else "<p>Предупреждения отсутствуют.</p>"
    )

    return f"""
<!doctype html>
<html lang='ru'>
<head>
  <meta charset='utf-8'>
  <title>Краткий отчёт портфеля</title>
</head>
<body style='font-family: Arial, sans-serif; margin: 24px;'>
  <h1>Краткий отчёт портфеля</h1>
  <p><strong>Дата отчёта:</strong> {escape(str(report_date or 'нет данных'))}</p>

  <h2>Ключевые метрики</h2>
  <ul>
    <li>Стоимость портфеля: {_fmt_currency(portfolio_value)}</li>
    <li>Стоимость облигационной части: {_fmt_currency(bond_value)}</li>
    <li>Средневзвешенная YTM: {_fmt_pct(weighted_ytm)}</li>
    <li>Покрытие YTM: {_fmt_pct(ytm_coverage_pct, scale_100=True)}</li>
  </ul>

  <h2>Крупнейшие позиции</h2>
  {_build_table(["Инструмент", "ISIN", "Доля", "Полная стоимость"], position_rows)}

  <h2>Крупнейшие эмитенты</h2>
  {_build_table(["Эмитент", "Доля", "Полная стоимость"], issuer_rows)}

  <h2>Предупреждения</h2>
  {warnings_html}

  <h2>Купонный поток на 12 месяцев</h2>
  <p><strong>Итого за 12 месяцев:</strong> {cashflow_total}</p>
  {_build_table(["Месяц", "Доход", "Выплат"], cashflow_rows)}

  <h2>Лестница погашений</h2>
  {_build_table(["Год", "Погашения", "Амортизации", "Итого"], ladder_rows)}

  <h2>Отсутствующие данные</h2>
  {missing_html}
</body>
</html>
""".strip()
