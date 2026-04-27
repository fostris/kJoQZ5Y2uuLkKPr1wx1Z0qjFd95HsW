"""Оценка качества данных по облигациям."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

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

