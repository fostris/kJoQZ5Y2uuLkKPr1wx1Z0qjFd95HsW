"""Оценка качества данных по облигациям."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Iterable, Mapping

from analytics.bonds import calculate_days_to_maturity, calculate_years_to_maturity
from concentration import BOND_ASSET_TYPES, calculate_position_market_value

SEVERITY_ORDER = {"info": 0, "warning": 1, "high": 2, "critical": 3}

FIELD_LABELS = {
    "ytm": "YTM",
    "issuer": "Эмитент",
    "maturity": "Дата погашения",
    "coupons": "Купонный календарь",
    "amortization": "Амортизации",
    "cost_basis": "Cost basis",
    "nkd": "НКД",
    "price": "Цена",
}
ATTENTION_SEVERITY_ORDER = {"info": 0, "warning": 1, "high": 2, "critical": 3}


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


def _severity_by_share(share: float | None) -> str:
    if share is None or share < 0.05:
        return "info"
    if share < 0.15:
        return "warning"
    if share < 0.30:
        return "high"
    return "critical"


def build_bond_data_quality_report(
    positions: Iterable[Mapping[str, Any]],
    ytm_map: Mapping[str, float | None],
    issuer_map: Mapping[str, str | None],
    maturities: Iterable[Mapping[str, Any]],
    coupons: Iterable[Mapping[str, Any]],
    cost_basis: Mapping[str, Mapping[str, Any]],
    amortizations: Iterable[Mapping[str, Any]] | None = None,
    bond_asset_types: tuple[str, ...] = BOND_ASSET_TYPES,
) -> dict[str, Any]:
    """Отчёт по полноте данных облигаций: score, проблемы, список бумаг."""
    maturity_by_isin: dict[str, Mapping[str, Any]] = {}
    requires_amortization: set[str] = set()
    for row in maturities:
        isin = str(_row_get(row, "isin", "") or "")
        if not isin:
            continue
        maturity_by_isin[isin] = dict(row)
        if bool(_row_get(row, "has_amortization", False)):
            requires_amortization.add(isin)

    coupon_isins = {
        str(_row_get(row, "isin", "") or "")
        for row in coupons
        if str(_row_get(row, "isin", "") or "")
    }
    amortization_isins = {
        str(_row_get(row, "isin", "") or "")
        for row in (amortizations or [])
        if str(_row_get(row, "isin", "") or "")
    }

    bond_rows: list[dict[str, Any]] = []
    problem_values: dict[str, float] = defaultdict(float)
    problem_counts: dict[str, int] = defaultdict(int)
    total_bond_value = 0.0
    total_required = 0
    total_present = 0

    for position in positions:
        if _row_get(position, "asset_type") not in bond_asset_types:
            continue

        market_value = calculate_position_market_value(position)
        if market_value is None or market_value <= 0:
            continue

        isin = str(_row_get(position, "isin", "") or "")
        name = str(_row_get(position, "name", "") or "—")
        total_bond_value += market_value

        required_fields = ["ytm", "issuer", "maturity", "coupons", "cost_basis", "nkd", "price"]
        if isin in requires_amortization:
            required_fields.append("amortization")

        missing_fields: list[str] = []

        # YTM
        if _to_float(ytm_map.get(isin)) is None:
            missing_fields.append("ytm")
        # Эмитент
        if not issuer_map.get(isin):
            missing_fields.append("issuer")
        # Дата погашения
        maturity_date = _row_get(maturity_by_isin.get(isin), "maturity_date")
        if not maturity_date:
            missing_fields.append("maturity")
        # Купоны
        if isin not in coupon_isins:
            missing_fields.append("coupons")
        # Амортизации (если применимо)
        if isin in requires_amortization and isin not in amortization_isins:
            missing_fields.append("amortization")
        # Cost basis
        cb = cost_basis.get(isin)
        if not cb or _to_float(_row_get(cb, "avg_price")) is None:
            missing_fields.append("cost_basis")
        # НКД
        if _to_float(_row_get(position, "nkd_end")) is None:
            missing_fields.append("nkd")
        # Цена
        if _to_float(_row_get(position, "price_end")) is None:
            missing_fields.append("price")

        required_count = len(required_fields)
        present_count = required_count - len(missing_fields)
        total_required += required_count
        total_present += present_count

        for code in missing_fields:
            problem_values[code] += market_value
            problem_counts[code] += 1

        bond_rows.append(
            {
                "name": name,
                "isin": isin or "—",
                "market_value": market_value,
                "missing_fields": missing_fields,
                "missing_fields_text": ", ".join(FIELD_LABELS[f] for f in missing_fields) if missing_fields else "нет данных",
                "missing_count": len(missing_fields),
                "required_count": required_count,
                "present_count": present_count,
                "completeness_pct": (present_count / required_count * 100) if required_count else 0.0,
            }
        )

    if total_bond_value > 0:
        for row in bond_rows:
            row["position_share"] = row["market_value"] / total_bond_value
    else:
        for row in bond_rows:
            row["position_share"] = None

    bond_rows_with_issues = [row for row in bond_rows if row["missing_count"] > 0]
    bond_rows_with_issues.sort(key=lambda row: row["market_value"], reverse=True)

    problems: list[dict[str, Any]] = []
    for code, value in problem_values.items():
        share = (value / total_bond_value) if total_bond_value > 0 else None
        problems.append(
            {
                "code": code,
                "title": FIELD_LABELS.get(code, code),
                "missing_count": problem_counts.get(code, 0),
                "missing_value": float(value),
                "missing_share": share,
                "severity": _severity_by_share(share),
            }
        )
    problems.sort(key=lambda item: SEVERITY_ORDER[item["severity"]], reverse=True)

    overall_score_pct = (total_present / total_required * 100) if total_required > 0 else None
    if problems:
        overall_severity = problems[0]["severity"]
    else:
        overall_severity = "info"

    return {
        "overall_score_pct": overall_score_pct,
        "overall_severity": overall_severity,
        "total_bond_value": total_bond_value,
        "bond_count": len(bond_rows),
        "bonds_with_issues_count": len(bond_rows_with_issues),
        "missing_fields_total": int(sum(row["missing_count"] for row in bond_rows)),
        "checked_fields": [FIELD_LABELS[k] for k in FIELD_LABELS],
        "problems": problems,
        "bonds": bond_rows_with_issues,
    }


def build_attention_list(
    positions: Iterable[Mapping[str, Any]],
    position_share_map: Mapping[str, float | None],
    issuer_share_map: Mapping[str, float | None],
    issuer_map: Mapping[str, str | None],
    ytm_map: Mapping[str, float | None],
    maturity_by_isin: Mapping[str, Any],
    coupons: Iterable[Mapping[str, Any]],
    cost_basis: Mapping[str, Mapping[str, Any]],
    as_of_date: date | None = None,
    near_maturity_days_threshold: int = 90,
    loss_pct_threshold: float = -10.0,
    long_maturity_years_threshold: float = 7.0,
    concentration_threshold: float = 0.10,
    bond_asset_types: tuple[str, ...] = BOND_ASSET_TYPES,
) -> list[dict[str, Any]]:
    """Список бумаг, требующих внимания, с причинами и действиями."""
    as_of = as_of_date or date.today()
    coupon_isins = {
        str(_row_get(row, "isin", "") or "")
        for row in coupons
        if str(_row_get(row, "isin", "") or "")
    }

    rows: list[dict[str, Any]] = []
    total_portfolio_value = 0.0

    # Чтобы позиционные доли можно было посчитать fallback'ом.
    market_value_map: dict[str, float] = {}
    for position in positions:
        market_value = calculate_position_market_value(position)
        if market_value is None or market_value <= 0:
            continue
        key = str(_row_get(position, "isin", "") or _row_get(position, "name", "") or "")
        if key:
            market_value_map[key] = market_value
        total_portfolio_value += market_value

    for position in positions:
        name = str(_row_get(position, "name", "") or "—")
        isin = str(_row_get(position, "isin", "") or "")
        asset_type = str(_row_get(position, "asset_type", "") or "")
        market_value = calculate_position_market_value(position)
        if market_value is None or market_value <= 0:
            continue

        position_key = isin or name
        position_share = position_share_map.get(position_key)
        if position_share is None and total_portfolio_value > 0:
            position_share = market_value / total_portfolio_value

        issuer = issuer_map.get(isin) or name
        issuer_share = issuer_share_map.get(issuer) if issuer else None

        reasons: list[str] = []
        actions: list[str] = []
        severity = "info"

        def add_reason(reason: str, action: str, reason_severity: str):
            nonlocal severity
            reasons.append(reason)
            actions.append(action)
            if ATTENTION_SEVERITY_ORDER[reason_severity] > ATTENTION_SEVERITY_ORDER[severity]:
                severity = reason_severity

        if position_share is not None and position_share > concentration_threshold:
            sev = "high" if position_share >= 0.15 else "warning"
            add_reason(
                f"Доля позиции {position_share * 100:.1f}% > {concentration_threshold * 100:.0f}%",
                "оценить концентрацию",
                sev,
            )

        if issuer_share is not None and issuer_share > concentration_threshold:
            sev = "high" if issuer_share >= 0.15 else "warning"
            add_reason(
                f"Доля эмитента {issuer_share * 100:.1f}% > {concentration_threshold * 100:.0f}%",
                "оценить концентрацию",
                sev,
            )

        days_to_maturity = None
        years_to_maturity = None

        if asset_type in bond_asset_types:
            if _to_float(ytm_map.get(isin)) is None:
                add_reason("Нет YTM", "проверить доходность", "warning")

            maturity_raw = maturity_by_isin.get(isin)
            years_to_maturity = calculate_years_to_maturity(maturity_raw, as_of)
            days_to_maturity = calculate_days_to_maturity(maturity_raw, as_of)
            if maturity_raw in (None, ""):
                add_reason("Нет даты погашения", "проверить данные", "high")
            else:
                if days_to_maturity is not None and days_to_maturity <= near_maturity_days_threshold:
                    add_reason(
                        f"Погашение ближе {near_maturity_days_threshold} дней",
                        "запланировать реинвестирование",
                        "warning",
                    )
                if years_to_maturity is not None and years_to_maturity >= long_maturity_years_threshold:
                    add_reason(
                        f"Срок до погашения > {long_maturity_years_threshold:.1f} лет",
                        "проверить доходность",
                        "info",
                    )

            if isin not in coupon_isins:
                add_reason("Нет купонного календаря", "проверить данные", "warning")

        pnl_pct = None
        cb = cost_basis.get(isin)
        avg_price = _to_float(_row_get(cb, "avg_price"))
        qty = _to_float(_row_get(position, "qty"))
        if avg_price is not None and qty is not None and qty > 0:
            cost_value = avg_price * qty
            if cost_value > 0:
                pnl_pct = (market_value - cost_value) / cost_value * 100
                if pnl_pct <= loss_pct_threshold:
                    add_reason(
                        f"Убыток {pnl_pct:.1f}% <= {loss_pct_threshold:.1f}%",
                        "проверить причину убытка",
                        "warning",
                    )

        if not reasons:
            continue

        unique_actions = []
        for action in actions:
            if action not in unique_actions:
                unique_actions.append(action)

        rows.append(
            {
                "name": name,
                "isin": isin or "—",
                "asset_type": asset_type,
                "market_value": float(market_value),
                "position_share": position_share,
                "issuer": issuer or "—",
                "issuer_share": issuer_share,
                "days_to_maturity": days_to_maturity,
                "years_to_maturity": years_to_maturity,
                "pnl_pct": pnl_pct,
                "severity": severity,
                "reason": "; ".join(reasons),
                "reasons": reasons,
                "suggested_action": ", ".join(unique_actions),
            }
        )

    rows.sort(
        key=lambda row: (
            ATTENTION_SEVERITY_ORDER.get(str(row.get("severity")), 0),
            _to_float(row.get("position_share")) or 0.0,
            _to_float(row.get("market_value")) or 0.0,
        ),
        reverse=True,
    )
    return rows
