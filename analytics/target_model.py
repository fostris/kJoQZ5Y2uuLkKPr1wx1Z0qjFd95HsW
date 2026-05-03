from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Mapping

from concentration import BOND_ASSET_TYPES, calculate_position_market_value

DeviationType = Literal[
    "position_concentration",
    "issuer_concentration",
    "sector_concentration",
    "duration_below",
    "duration_above",
    "ytm_below_min_buy",
    "asset_allocation",
]
Severity = Literal["critical", "warning", "info"]


@dataclass(frozen=True)
class Targets:
    position_max_pct: float
    issuer_max_pct: float
    sector_max_pct: float
    duration_min_years: float
    duration_max_years: float
    ytm_min_for_buy: float
    target_monthly_cashflow: float


@dataclass(frozen=True)
class TargetDeviation:
    type: DeviationType
    severity: Severity
    name: str
    isin: str | None
    current_value: float
    target_value: float
    delta_abs: float
    delta_pp: float | None
    correction_amount_rub: float | None
    message: str
    metrics: dict


@dataclass(frozen=True)
class CoverageInfo:
    sector_coverage: float
    sector_unknown_count: int
    duration_coverage: float


@dataclass(frozen=True)
class TargetDeviationsResult:
    deviations: list[TargetDeviation]
    coverage: CoverageInfo
    summary: dict[str, int]


_SEVERITY_ORDER: dict[Severity, int] = {
    "critical": 0,
    "warning": 1,
    "info": 2,
}

_TYPE_ORDER: dict[DeviationType, int] = {
    "position_concentration": 0,
    "issuer_concentration": 1,
    "sector_concentration": 2,
    "asset_allocation": 3,
    "duration_below": 4,
    "duration_above": 5,
    "ytm_below_min_buy": 6,
}

_CONCENTRATION_CRITICAL_PP = 8.0
_CONCENTRATION_WARNING_PP = 2.0
_ASSET_ALLOCATION_CRITICAL_PP = 10.0
_ASSET_ALLOCATION_WARNING_PP = 5.0
_EPS = 1e-9


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm_isin(value: Any) -> str:
    return str(value or "").strip().upper()


def _norm_share_target(value: Any) -> float | None:
    number = _to_float(value)
    if number is None:
        return None
    if number > 1.0:
        return number / 100.0
    return number


def _norm_ytm(value: Any) -> float | None:
    number = _to_float(value)
    if number is None:
        return None
    if abs(number) > 1.0:
        return number / 100.0
    return number


def _severity_for_concentration(delta_pp: float) -> Severity:
    if delta_pp >= (_CONCENTRATION_CRITICAL_PP - _EPS):
        return "critical"
    if delta_pp >= (_CONCENTRATION_WARNING_PP - _EPS):
        return "warning"
    return "info"


def _severity_for_asset_allocation(delta_pp_abs: float) -> Severity:
    if delta_pp_abs >= (_ASSET_ALLOCATION_CRITICAL_PP - _EPS):
        return "critical"
    if delta_pp_abs >= (_ASSET_ALLOCATION_WARNING_PP - _EPS):
        return "warning"
    return "info"


def _suggested_correction(target_value: float, current_value: float, portfolio_total_value: float) -> float:
    if portfolio_total_value <= 0:
        return 0.0
    return (target_value - current_value) * portfolio_total_value


def _sort_deviations(deviations: list[TargetDeviation]) -> list[TargetDeviation]:
    return sorted(
        deviations,
        key=lambda item: (
            _SEVERITY_ORDER.get(item.severity, 99),
            _TYPE_ORDER.get(item.type, 99),
            -(abs(item.correction_amount_rub) if item.correction_amount_rub is not None else -1.0),
            -abs(item.delta_pp) if item.delta_pp is not None else 1.0,
            str(item.name).lower(),
        ),
    )


def _build_summary(deviations: list[TargetDeviation]) -> dict[str, int]:
    critical = sum(1 for row in deviations if row.severity == "critical")
    warning = sum(1 for row in deviations if row.severity == "warning")
    info = sum(1 for row in deviations if row.severity == "info")
    return {
        "total": len(deviations),
        "critical": critical,
        "warning": warning,
        "info": info,
    }


def _extract_ytm_lookup(weighted_ytm_result: Any) -> dict[str, float]:
    candidates: list[Mapping[str, Any] | None] = []
    if isinstance(weighted_ytm_result, Mapping):
        candidates.append(weighted_ytm_result)
    if hasattr(weighted_ytm_result, "__dict__") and isinstance(weighted_ytm_result.__dict__, dict):
        candidates.append(weighted_ytm_result.__dict__)

    for candidate in candidates:
        if not candidate:
            continue
        ytm_map = candidate.get("ytm_by_isin")
        if not isinstance(ytm_map, Mapping):
            continue
        out: dict[str, float] = {}
        for isin_raw, ytm_raw in ytm_map.items():
            isin = _norm_isin(isin_raw)
            ytm = _norm_ytm(ytm_raw)
            if isin and ytm is not None:
                out[isin] = ytm
        if out:
            return out
    return {}


def compute_target_deviations(
    positions: list[dict],
    *,
    concentration_data: dict,
    duration_result,
    weighted_ytm_result,
    issuer_by_isin: dict[str, str],
    sector_by_isin: dict[str, str | None],
    asset_type_targets: dict[str, float],
    targets: Targets,
    portfolio_total_value: float,
    as_of_date: date,
) -> TargetDeviationsResult:
    concentration_data = concentration_data or {}
    issuer_by_isin = issuer_by_isin or {}
    sector_by_isin = sector_by_isin or {}

    deviations: list[TargetDeviation] = []

    # 1. Position concentration
    for row in concentration_data.get("positions") or []:
        current_value = _to_float(row.get("position_share"))
        if current_value is None or current_value <= targets.position_max_pct:
            continue

        delta_abs = current_value - targets.position_max_pct
        delta_pp = delta_abs * 100.0
        correction = _suggested_correction(targets.position_max_pct, current_value, portfolio_total_value)
        deviations.append(
            TargetDeviation(
                type="position_concentration",
                severity=_severity_for_concentration(delta_pp),
                name=str(row.get("name") or row.get("isin") or "Позиция"),
                isin=_norm_isin(row.get("isin")) or None,
                current_value=current_value,
                target_value=targets.position_max_pct,
                delta_abs=delta_abs,
                delta_pp=delta_pp,
                correction_amount_rub=correction,
                message=(
                    f"Позиция выше лимита на {delta_pp:.2f} п.п.; "
                    f"ориентир корректировки {correction:+,.0f} ₽"
                ),
                metrics={
                    "as_of_date": as_of_date.isoformat(),
                    "position_share": current_value,
                    "limit": targets.position_max_pct,
                },
            )
        )

    # 2. Issuer concentration
    for row in concentration_data.get("issuers") or []:
        current_value = _to_float(row.get("issuer_share"))
        if current_value is None or current_value <= targets.issuer_max_pct:
            continue

        delta_abs = current_value - targets.issuer_max_pct
        delta_pp = delta_abs * 100.0
        correction = _suggested_correction(targets.issuer_max_pct, current_value, portfolio_total_value)
        deviations.append(
            TargetDeviation(
                type="issuer_concentration",
                severity=_severity_for_concentration(delta_pp),
                name=str(row.get("issuer") or "Эмитент"),
                isin=None,
                current_value=current_value,
                target_value=targets.issuer_max_pct,
                delta_abs=delta_abs,
                delta_pp=delta_pp,
                correction_amount_rub=correction,
                message=(
                    f"Эмитент выше лимита на {delta_pp:.2f} п.п.; "
                    f"ориентир корректировки {correction:+,.0f} ₽"
                ),
                metrics={
                    "as_of_date": as_of_date.isoformat(),
                    "issuer_share": current_value,
                    "limit": targets.issuer_max_pct,
                },
            )
        )

    # 3. Sector concentration + coverage
    sector_values: dict[str, float] = {}
    known_sector_total = 0.0
    sector_unknown_count = 0

    for position in positions:
        market_value = calculate_position_market_value(position)
        if market_value is None or market_value <= 0:
            continue

        isin = _norm_isin(position.get("isin"))
        sector_name_raw = sector_by_isin.get(isin) if isin else None
        sector_name = str(sector_name_raw or "").strip()
        if not sector_name:
            sector_unknown_count += 1
            continue

        known_sector_total += market_value
        sector_values[sector_name] = sector_values.get(sector_name, 0.0) + market_value

    sector_coverage = (known_sector_total / portfolio_total_value) if portfolio_total_value > 0 else 0.0

    for sector_name, sector_value in sector_values.items():
        current_value = (sector_value / portfolio_total_value) if portfolio_total_value > 0 else 0.0
        if current_value <= targets.sector_max_pct:
            continue

        delta_abs = current_value - targets.sector_max_pct
        delta_pp = delta_abs * 100.0
        correction = _suggested_correction(targets.sector_max_pct, current_value, portfolio_total_value)
        deviations.append(
            TargetDeviation(
                type="sector_concentration",
                severity=_severity_for_concentration(delta_pp),
                name=sector_name,
                isin=None,
                current_value=current_value,
                target_value=targets.sector_max_pct,
                delta_abs=delta_abs,
                delta_pp=delta_pp,
                correction_amount_rub=correction,
                message=(
                    f"Сектор выше лимита на {delta_pp:.2f} п.п.; "
                    f"ориентир корректировки {correction:+,.0f} ₽"
                ),
                metrics={
                    "as_of_date": as_of_date.isoformat(),
                    "sector": sector_name,
                    "sector_share": current_value,
                    "limit": targets.sector_max_pct,
                    "sector_coverage": sector_coverage,
                },
            )
        )

    # 4. Duration deviation
    duration_value = _to_float(getattr(duration_result, "duration_years", None))
    duration_coverage = _to_float(getattr(duration_result, "coverage", 0.0)) or 0.0
    if duration_value is not None and duration_coverage >= 0.5:
        if duration_value < targets.duration_min_years:
            delta_abs = duration_value - targets.duration_min_years
            severity: Severity = "warning" if abs(delta_abs) <= 0.5 else "critical"
            deviations.append(
                TargetDeviation(
                    type="duration_below",
                    severity=severity,
                    name="Дюрация портфеля",
                    isin=None,
                    current_value=duration_value,
                    target_value=targets.duration_min_years,
                    delta_abs=delta_abs,
                    delta_pp=None,
                    correction_amount_rub=None,
                    message=f"Дюрация ниже минимума на {abs(delta_abs):.2f} года",
                    metrics={
                        "as_of_date": as_of_date.isoformat(),
                        "duration": duration_value,
                        "duration_coverage": duration_coverage,
                    },
                )
            )
        elif duration_value > targets.duration_max_years:
            delta_abs = duration_value - targets.duration_max_years
            severity = "warning" if abs(delta_abs) <= 0.5 else "critical"
            deviations.append(
                TargetDeviation(
                    type="duration_above",
                    severity=severity,
                    name="Дюрация портфеля",
                    isin=None,
                    current_value=duration_value,
                    target_value=targets.duration_max_years,
                    delta_abs=delta_abs,
                    delta_pp=None,
                    correction_amount_rub=None,
                    message=f"Дюрация выше максимума на {abs(delta_abs):.2f} года",
                    metrics={
                        "as_of_date": as_of_date.isoformat(),
                        "duration": duration_value,
                        "duration_coverage": duration_coverage,
                    },
                )
            )

    # 5. YTM below min for buy (informational)
    ytm_by_isin = _extract_ytm_lookup(weighted_ytm_result)
    for position in positions:
        asset_type = str(position.get("asset_type") or "").strip()
        if asset_type not in BOND_ASSET_TYPES:
            continue

        isin = _norm_isin(position.get("isin"))
        ytm_value = _norm_ytm(position.get("ytm"))
        if ytm_value is None:
            ytm_value = _norm_ytm(position.get("ytm_pct"))
        if ytm_value is None and isin:
            ytm_value = ytm_by_isin.get(isin)
        if ytm_value is None or ytm_value >= targets.ytm_min_for_buy:
            continue

        delta_abs = ytm_value - targets.ytm_min_for_buy
        deviations.append(
            TargetDeviation(
                type="ytm_below_min_buy",
                severity="info",
                name=str(position.get("name") or isin or "Облигация"),
                isin=isin or None,
                current_value=ytm_value,
                target_value=targets.ytm_min_for_buy,
                delta_abs=delta_abs,
                delta_pp=delta_abs * 100.0,
                correction_amount_rub=None,
                message=(
                    f"Текущая YTM {ytm_value * 100:.2f}% ниже фильтра покупки "
                    f"{targets.ytm_min_for_buy * 100:.2f}%"
                ),
                metrics={
                    "as_of_date": as_of_date.isoformat(),
                    "ytm": ytm_value,
                    "ytm_min_for_buy": targets.ytm_min_for_buy,
                },
            )
        )

    # 6. Asset allocation deviation
    asset_shares: dict[str, float] = {}
    for row in concentration_data.get("asset_types") or []:
        asset_type = str(row.get("asset_type") or "").strip()
        share = _to_float(row.get("asset_type_share"))
        if asset_type and share is not None:
            asset_shares[asset_type] = share

    for asset_type, raw_target in (asset_type_targets or {}).items():
        target_value = _norm_share_target(raw_target)
        if target_value is None:
            continue

        current_value = asset_shares.get(str(asset_type), 0.0)
        delta_abs = current_value - target_value
        if abs(delta_abs) < 1e-12:
            continue

        delta_pp = delta_abs * 100.0
        correction = _suggested_correction(target_value, current_value, portfolio_total_value)
        deviations.append(
            TargetDeviation(
                type="asset_allocation",
                severity=_severity_for_asset_allocation(abs(delta_pp)),
                name=str(asset_type),
                isin=None,
                current_value=current_value,
                target_value=target_value,
                delta_abs=delta_abs,
                delta_pp=delta_pp,
                correction_amount_rub=correction,
                message=(
                    f"Доля типа актива отклоняется на {delta_pp:+.2f} п.п.; "
                    f"ориентир корректировки {correction:+,.0f} ₽"
                ),
                metrics={
                    "as_of_date": as_of_date.isoformat(),
                    "asset_type": asset_type,
                    "asset_type_share": current_value,
                    "target_share": target_value,
                },
            )
        )

    sorted_deviations = _sort_deviations(deviations)
    coverage = CoverageInfo(
        sector_coverage=float(sector_coverage),
        sector_unknown_count=int(sector_unknown_count),
        duration_coverage=float(duration_coverage),
    )

    return TargetDeviationsResult(
        deviations=sorted_deviations,
        coverage=coverage,
        summary=_build_summary(sorted_deviations),
    )
