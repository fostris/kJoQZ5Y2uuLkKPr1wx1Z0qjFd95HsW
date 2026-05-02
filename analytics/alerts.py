"""Unified portfolio alerts: data gaps + portfolio risks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Mapping

import concentration
from analytics.bonds import calculate_days_to_maturity
from portfolio_metrics import compute_position_pnl_for_row

Severity = Literal["critical", "warning", "info"]
AlertCategory = Literal["data", "risk"]


@dataclass(frozen=True)
class AlertThresholds:
    # Position concentration (portfolio share, 0..1)
    position_critical: float = 0.15
    position_warning: float = 0.10
    position_info: float = 0.07
    # Issuer concentration
    issuer_critical: float = 0.20
    issuer_warning: float = 0.15
    issuer_info: float = 0.10
    # Sector concentration
    sector_critical: float = 0.40
    sector_warning: float = 0.30
    sector_info: float = 0.20
    # Position loss (absolute value of negative P&L %, 0..1)
    loss_warning: float = 0.10
    loss_critical: float = 0.20
    # Reinvestment risk
    maturity_critical_days: int = 30
    maturity_warning_days: int = 90


@dataclass(frozen=True)
class Alert:
    category: AlertCategory
    severity: Severity
    rule_code: str
    isin: str | None
    name: str | None
    message: str
    metrics: dict[str, Any]
    sort_key: float


@dataclass(frozen=True)
class AlertsResult:
    data_alerts: list[Alert]
    risk_alerts: list[Alert]
    summary: dict[str, int]


RULE_LABELS = {
    "missing_ytm": "Нет YTM",
    "missing_maturity": "Нет даты погашения",
    "missing_rating": "Нет рейтинга",
    "missing_cost_basis": "Нет cost basis",
    "missing_issuer": "Нет эмитента",
    "concentration_position": "Концентрация позиции",
    "concentration_issuer": "Концентрация эмитента",
    "concentration_sector": "Концентрация сектора",
    "loss_position": "Убыток позиции",
    "maturity_soon": "Скорое погашение",
    "hhi_portfolio": "Высокий HHI портфеля",
}

_SEVERITY_PRIORITY: dict[Severity, int] = {"critical": 2, "warning": 1, "info": 0}


def get_rule_label(rule_code: str) -> str:
    return RULE_LABELS.get(rule_code, rule_code)


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm_isin(value: Any) -> str:
    return str(value or "").strip().upper()


def _position_key(row: Mapping[str, Any]) -> str:
    isin = _norm_isin(row.get("isin"))
    if isin:
        return isin
    return str(row.get("name") or "").strip()


def _severity_by_share(
    share: float | None,
    *,
    critical: float,
    warning: float,
    info: float,
) -> Severity | None:
    if share is None:
        return None
    if share >= critical:
        return "critical"
    if share >= warning:
        return "warning"
    if share >= info:
        return "info"
    return None


def _sort_alerts(items: list[Alert]) -> list[Alert]:
    return sorted(
        items,
        key=lambda a: (
            -_SEVERITY_PRIORITY.get(a.severity, 0),
            -(float(a.sort_key) if a.sort_key is not None else 0.0),
            str(a.name or "").lower(),
        ),
    )


def _extract_maturity_map(data_quality_data: Mapping[str, Any]) -> dict[str, Any]:
    maturity_map_raw = data_quality_data.get("maturity_by_isin") or {}
    if maturity_map_raw:
        return {_norm_isin(k): v for k, v in maturity_map_raw.items() if _norm_isin(k)}

    maturities = data_quality_data.get("maturities") or []
    result: dict[str, Any] = {}
    for row in maturities:
        if not isinstance(row, Mapping):
            continue
        isin = _norm_isin(row.get("isin"))
        if not isin:
            continue
        result[isin] = row.get("maturity_date")
    return result


def _extract_rating_map(data_quality_data: Mapping[str, Any]) -> dict[str, str]:
    rating_by_isin_raw = data_quality_data.get("rating_by_isin") or {}
    out: dict[str, str] = {}
    for isin_raw, value in rating_by_isin_raw.items():
        isin = _norm_isin(isin_raw)
        if not isin:
            continue
        if isinstance(value, Mapping):
            out[isin] = str(value.get("rating") or "").strip()
        else:
            out[isin] = str(value or "").strip()
    return out


def _extract_cost_basis_map(data_quality_data: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    cost_basis_raw = data_quality_data.get("cost_basis") or {}
    out: dict[str, Mapping[str, Any]] = {}
    for isin_raw, value in cost_basis_raw.items():
        isin = _norm_isin(isin_raw)
        if not isin or not isinstance(value, Mapping):
            continue
        out[isin] = value
    return out


def _extract_issuer_map(data_quality_data: Mapping[str, Any]) -> dict[str, str]:
    issuer_raw = data_quality_data.get("issuer_by_isin") or data_quality_data.get("issuer_map") or {}
    out: dict[str, str] = {}
    for isin_raw, value in issuer_raw.items():
        isin = _norm_isin(isin_raw)
        if not isin:
            continue
        out[isin] = str(value or "").strip()
    return out


def build_alerts(
    positions: list[dict],
    *,
    concentration_data: dict,
    data_quality_data: dict,
    as_of_date: date,
    thresholds: AlertThresholds = AlertThresholds(),
) -> AlertsResult:
    """Build split alerts: data gaps and portfolio risks."""
    if not positions or not concentration_data or not data_quality_data:
        return AlertsResult(
            data_alerts=[],
            risk_alerts=[],
            summary={
                "data_total": 0,
                "risk_total": 0,
                "critical": 0,
                "warning": 0,
                "info": 0,
                "data_critical": 0,
                "data_warning": 0,
                "data_info": 0,
                "risk_critical": 0,
                "risk_warning": 0,
                "risk_info": 0,
            },
        )

    position_rows = concentration_data.get("positions") or []
    position_share_map: dict[str, float] = {}
    for row in position_rows:
        if not isinstance(row, Mapping):
            continue
        key = _position_key(row)
        if not key:
            continue
        share = _to_float(row.get("position_share"))
        if share is not None:
            position_share_map[key] = share

    total_portfolio_value = _to_float(concentration_data.get("total_portfolio_value")) or 0.0
    if total_portfolio_value <= 0:
        for row in positions:
            market_value = concentration.calculate_position_market_value(row)
            if market_value is not None and market_value > 0:
                total_portfolio_value += market_value

    ytm_by_isin = {
        _norm_isin(k): _to_float(v)
        for k, v in (data_quality_data.get("ytm_by_isin") or data_quality_data.get("ytm_map") or {}).items()
        if _norm_isin(k)
    }
    maturity_by_isin = _extract_maturity_map(data_quality_data)
    rating_by_isin = _extract_rating_map(data_quality_data)
    cost_basis_map = _extract_cost_basis_map(data_quality_data)
    issuer_by_isin = _extract_issuer_map(data_quality_data)

    ytm_asset_types = set(
        data_quality_data.get("ytm_applicable_asset_types") or concentration.BOND_ASSET_TYPES
    )
    bond_asset_types = set(concentration.BOND_ASSET_TYPES)

    data_alerts: list[Alert] = []
    risk_alerts: list[Alert] = []

    # Per-position rules
    for row in positions:
        key = _position_key(row)
        isin = _norm_isin(row.get("isin")) or None
        name = str(row.get("name") or "").strip() or None
        asset_type = str(row.get("asset_type") or "").strip()
        market_value = concentration.calculate_position_market_value(row)

        position_share = _to_float(position_share_map.get(key))
        if position_share is None and market_value is not None and market_value > 0 and total_portfolio_value > 0:
            position_share = market_value / total_portfolio_value
        sort_key = float(position_share or 0.0)

        # Risk: concentration by position
        sev = _severity_by_share(
            position_share,
            critical=thresholds.position_critical,
            warning=thresholds.position_warning,
            info=thresholds.position_info,
        )
        if sev is not None:
            risk_alerts.append(
                Alert(
                    category="risk",
                    severity=sev,
                    rule_code="concentration_position",
                    isin=isin,
                    name=name,
                    message=f"Доля позиции {position_share * 100:.2f}%",
                    metrics={"position_share": position_share},
                    sort_key=sort_key,
                )
            )

        # Risk: loss position
        pnl_pct = _to_float(row.get("pnl_pct"))
        if pnl_pct is None and isin:
            cb = cost_basis_map.get(isin)
            avg_price = _to_float(cb.get("avg_price")) if cb else None
            qty = _to_float(row.get("qty"))
            if avg_price is not None and qty is not None and qty > 0 and market_value is not None:
                pnl_result = compute_position_pnl_for_row(
                    quantity=qty,
                    market_value=market_value,
                    avg_price=avg_price,
                    asset_type=asset_type,
                    nominal=_to_float(row.get("nominal")),
                    cost_basis_total_qty=_to_float(cb.get("total_qty")) if cb else None,
                    cost_basis_source=str(cb.get("source") or "") if cb else None,
                )
                pnl_pct = _to_float(pnl_result.get("pnl_pct"))
        if pnl_pct is not None and pnl_pct < 0:
            loss_share = abs(pnl_pct) / 100.0
            loss_severity: Severity | None = None
            if loss_share >= thresholds.loss_critical:
                loss_severity = "critical"
            elif loss_share >= thresholds.loss_warning:
                loss_severity = "warning"
            if loss_severity is not None:
                risk_alerts.append(
                    Alert(
                        category="risk",
                        severity=loss_severity,
                        rule_code="loss_position",
                        isin=isin,
                        name=name,
                        message=f"Убыток {pnl_pct:.2f}%",
                        metrics={"pnl_pct": pnl_pct},
                        sort_key=sort_key,
                    )
                )

        # Risk: soon maturity
        if asset_type in bond_asset_types:
            days_to_maturity = calculate_days_to_maturity(maturity_by_isin.get(isin or ""), as_of_date)
            maturity_severity: Severity | None = None
            if days_to_maturity is not None and days_to_maturity <= thresholds.maturity_critical_days:
                maturity_severity = "critical"
            elif days_to_maturity is not None and days_to_maturity <= thresholds.maturity_warning_days:
                maturity_severity = "warning"
            if maturity_severity is not None:
                risk_alerts.append(
                    Alert(
                        category="risk",
                        severity=maturity_severity,
                        rule_code="maturity_soon",
                        isin=isin,
                        name=name,
                        message=f"До погашения {days_to_maturity} дн.",
                        metrics={"days_to_maturity": days_to_maturity},
                        sort_key=sort_key,
                    )
                )

        # Data: missing YTM (only for supported bond asset types)
        if asset_type in ytm_asset_types and ytm_by_isin.get(isin or "") is None:
            data_alerts.append(
                Alert(
                    category="data",
                    severity="critical",
                    rule_code="missing_ytm",
                    isin=isin,
                    name=name,
                    message="Не заполнено поле YTM",
                    metrics={"asset_type": asset_type},
                    sort_key=sort_key,
                )
            )

        # Data: missing maturity (bonds only)
        if asset_type in bond_asset_types and not maturity_by_isin.get(isin or ""):
            data_alerts.append(
                Alert(
                    category="data",
                    severity="critical",
                    rule_code="missing_maturity",
                    isin=isin,
                    name=name,
                    message="Не заполнена дата погашения",
                    metrics={"asset_type": asset_type},
                    sort_key=sort_key,
                )
            )

        # Data: missing rating (bonds only)
        if asset_type in bond_asset_types and not str(rating_by_isin.get(isin or "") or "").strip():
            data_alerts.append(
                Alert(
                    category="data",
                    severity="warning",
                    rule_code="missing_rating",
                    isin=isin,
                    name=name,
                    message="Не заполнен кредитный рейтинг",
                    metrics={"asset_type": asset_type},
                    sort_key=sort_key,
                )
            )

        # Data: missing cost basis (all)
        has_cost_basis = False
        if isin:
            cb = cost_basis_map.get(isin)
            has_cost_basis = bool(cb and _to_float(cb.get("avg_price")) is not None)
        if not has_cost_basis:
            data_alerts.append(
                Alert(
                    category="data",
                    severity="warning",
                    rule_code="missing_cost_basis",
                    isin=isin,
                    name=name,
                    message="Не заполнен cost basis",
                    metrics={"asset_type": asset_type},
                    sort_key=sort_key,
                )
            )

        # Data: missing issuer (all)
        issuer_value = str(
            row.get("issuer")
            or issuer_by_isin.get(isin or "")
            or row.get("name")
            or ""
        ).strip()
        if not issuer_value:
            data_alerts.append(
                Alert(
                    category="data",
                    severity="info",
                    rule_code="missing_issuer",
                    isin=isin,
                    name=name,
                    message="Не заполнен эмитент",
                    metrics={"asset_type": asset_type},
                    sort_key=sort_key,
                )
            )

    # Portfolio/group-level risk rules
    issuer_rows = concentration_data.get("issuers") or []
    for row in issuer_rows:
        if not isinstance(row, Mapping):
            continue
        issuer = str(row.get("issuer") or "").strip()
        share = _to_float(row.get("issuer_share"))
        sev = _severity_by_share(
            share,
            critical=thresholds.issuer_critical,
            warning=thresholds.issuer_warning,
            info=thresholds.issuer_info,
        )
        if sev is None:
            continue
        risk_alerts.append(
            Alert(
                category="risk",
                severity=sev,
                rule_code="concentration_issuer",
                isin=None,
                name=issuer or None,
                message=f"Доля эмитента {share * 100:.2f}%",
                metrics={"issuer_share": share},
                sort_key=float(share or 0.0),
            )
        )

    sector_rows = concentration_data.get("sectors") or []
    for row in sector_rows:
        if not isinstance(row, Mapping):
            continue
        sector = str(row.get("sector") or "").strip()
        share = _to_float(row.get("dimension_share"))
        sev = _severity_by_share(
            share,
            critical=thresholds.sector_critical,
            warning=thresholds.sector_warning,
            info=thresholds.sector_info,
        )
        if sev is None:
            continue
        risk_alerts.append(
            Alert(
                category="risk",
                severity=sev,
                rule_code="concentration_sector",
                isin=None,
                name=sector or None,
                message=f"Доля сектора {share * 100:.2f}%",
                metrics={"sector_share": share},
                sort_key=float(share or 0.0),
            )
        )

    position_hhi = _to_float(concentration_data.get("position_hhi"))
    hhi_target = _to_float(
        concentration_data.get("position_hhi_target")
        or concentration_data.get("hhi_target")
        or concentration_data.get("max_position_hhi")
    )
    if position_hhi is not None and hhi_target is not None and position_hhi > hhi_target:
        risk_alerts.append(
            Alert(
                category="risk",
                severity="warning",
                rule_code="hhi_portfolio",
                isin=None,
                name=None,
                message=f"HHI {position_hhi:.3f} выше целевого {hhi_target:.3f}",
                metrics={"position_hhi": position_hhi, "target_hhi": hhi_target},
                sort_key=float(position_hhi),
            )
        )

    data_alerts = _sort_alerts(data_alerts)
    risk_alerts = _sort_alerts(risk_alerts)

    def _count(items: list[Alert], severity: Severity) -> int:
        return sum(1 for item in items if item.severity == severity)

    summary = {
        "data_total": len(data_alerts),
        "risk_total": len(risk_alerts),
        "critical": _count(data_alerts, "critical") + _count(risk_alerts, "critical"),
        "warning": _count(data_alerts, "warning") + _count(risk_alerts, "warning"),
        "info": _count(data_alerts, "info") + _count(risk_alerts, "info"),
        "data_critical": _count(data_alerts, "critical"),
        "data_warning": _count(data_alerts, "warning"),
        "data_info": _count(data_alerts, "info"),
        "risk_critical": _count(risk_alerts, "critical"),
        "risk_warning": _count(risk_alerts, "warning"),
        "risk_info": _count(risk_alerts, "info"),
    }

    return AlertsResult(
        data_alerts=data_alerts,
        risk_alerts=risk_alerts,
        summary=summary,
    )
