"""Rule-based сценарии принятия решений (без авто-сделок)."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping

import concentration
from analytics.bonds import calculate_years_to_maturity
from analytics.ratings import RATING_BUCKET_UNRATED, classify_rating_bucket

DEFAULT_WARNING_SHARE_THRESHOLD = 0.10

EXCLUSION_REASON_LABELS = {
    "not_bond": "не облигация",
    "no_market_value": "нет рыночной стоимости",
    "position_share_limit": "доля позиции выше лимита",
    "issuer_share_limit": "доля эмитента выше лимита",
    "missing_ytm": "нет YTM (исключено фильтром)",
    "ytm_below_min": "YTM ниже минимального порога",
    "missing_maturity": "нет даты погашения (исключено фильтром)",
    "maturity_too_long": "срок до погашения выше максимального",
}

REDUCE_FACTOR_LABELS = {
    "position_share": "большая доля позиции",
    "issuer_share": "большая доля эмитента",
    "missing_ytm": "нет YTM",
    "missing_maturity": "нет даты погашения",
    "low_ytm_vs_term": "низкая YTM относительно срока",
    "missing_rating": "нет рейтинга",
    "long_maturity": "длинный срок до погашения",
    "data_quality": "проблемы качества данных",
}
DEFAULT_REDUCE_FACTOR_WEIGHTS = {
    "position_share": 25.0,
    "issuer_share": 20.0,
    "missing_ytm": 12.0,
    "missing_maturity": 12.0,
    "low_ytm_vs_term": 10.0,
    "missing_rating": 8.0,
    "long_maturity": 8.0,
    "data_quality": 5.0,
}
DEFAULT_REDUCE_FACTOR_ENABLED = {name: True for name in REDUCE_FACTOR_LABELS}
DEFAULT_POSITION_SHARE_REFERENCE = 0.10
DEFAULT_ISSUER_SHARE_REFERENCE = 0.10
DEFAULT_LONG_MATURITY_YEARS = 7.0
DEFAULT_LOW_YTM_BASE = 6.0
DEFAULT_LOW_YTM_YEAR_SLOPE = 0.5


def get_exclusion_reason_label(reason_code: str) -> str:
    return EXCLUSION_REASON_LABELS.get(reason_code, reason_code)


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _append_reason(counter: dict[str, int], reason_code: str) -> None:
    counter[reason_code] = counter.get(reason_code, 0) + 1


def _normalized_share_risk(share: float | None, reference: float) -> float:
    if share is None or share <= 0 or reference <= 0:
        return 0.0
    return min(share / reference, 1.0)


def _risk_severity(score: float) -> str:
    if score >= 70:
        return "critical"
    if score >= 45:
        return "high"
    if score >= 25:
        return "warning"
    return "info"


def _build_candidate_explanation(
    ytm: float | None,
    min_ytm: float,
    position_share: float | None,
    max_position_share: float,
    issuer_share: float | None,
    max_issuer_share: float,
    years_to_maturity: float | None,
    max_years_to_maturity: float,
    target_gap_pct: float,
    warnings: list[str],
) -> str:
    parts: list[str] = []
    if ytm is None:
        parts.append("YTM нет (допущено настройками)")
    else:
        parts.append(f"YTM {ytm:.2f}% (мин. порог {min_ytm:.2f}%)")

    if position_share is None:
        parts.append("доля позиции недоступна")
    else:
        parts.append(
            f"доля позиции {position_share * 100:.2f}% "
            f"(лимит {max_position_share * 100:.2f}%)"
        )

    if issuer_share is None:
        parts.append("доля эмитента недоступна")
    else:
        parts.append(
            f"доля эмитента {issuer_share * 100:.2f}% "
            f"(лимит {max_issuer_share * 100:.2f}%)"
        )

    if years_to_maturity is None:
        parts.append("дата погашения не найдена")
    else:
        parts.append(
            f"срок до погашения {years_to_maturity:.2f} г. "
            f"(макс. {max_years_to_maturity:.2f} г.)"
        )

    parts.append(f"отклонение класса актива от цели: {target_gap_pct:+.2f} п.п.")
    if warnings:
        parts.append("предупреждения: " + "; ".join(warnings))
    else:
        parts.append("предупреждений нет")
    return " | ".join(parts)


def build_buy_candidates(
    positions: Iterable[Mapping[str, Any]],
    *,
    free_cash: float,
    issuer_by_isin: Mapping[str, str | None],
    ytm_by_isin: Mapping[str, float | None],
    maturity_by_isin: Mapping[str, str | None],
    position_share_map: Mapping[str, float | None],
    issuer_share_map: Mapping[str, float | None],
    current_type_pct: Mapping[str, float],
    target_type_pct: Mapping[str, float],
    total_portfolio_value: float,
    max_issuer_share: float,
    max_position_share: float,
    min_ytm: float,
    max_years_to_maturity: float,
    exclude_without_ytm: bool,
    exclude_without_maturity: bool,
    bond_asset_types: tuple[str, ...],
    warning_share_threshold: float = DEFAULT_WARNING_SHARE_THRESHOLD,
    data_quality_issue_isins: set[str] | None = None,
    as_of_date: date | None = None,
    max_candidates: int = 10,
) -> dict[str, Any]:
    """Сформировать список облигаций-кандидатов «можно рассмотреть к покупке»."""
    positions = list(positions)
    as_of_date = as_of_date or date.today()
    issue_isins = {str(isin).upper() for isin in (data_quality_issue_isins or set()) if isin}
    excluded_reasons: dict[str, int] = {}
    candidates: list[dict[str, Any]] = []
    total_bond_positions = 0

    for row in positions:
        asset_type = str(row.get("asset_type") or "")
        if asset_type not in bond_asset_types:
            _append_reason(excluded_reasons, "not_bond")
            continue
        total_bond_positions += 1

        market_value = concentration.calculate_position_market_value(row)
        if market_value is None or market_value <= 0:
            _append_reason(excluded_reasons, "no_market_value")
            continue

        isin = str(row.get("isin") or "").strip().upper()
        name = str(row.get("name") or isin or concentration.UNKNOWN_ISSUER)
        issuer = concentration.normalize_bond_issuer(
            issuer_by_isin.get(isin) or name,
            asset_type,
        )
        ytm = _to_float(ytm_by_isin.get(isin)) if isin else None
        years_to_maturity = (
            calculate_years_to_maturity(maturity_by_isin.get(isin), as_of_date) if isin else None
        )

        position_key = isin or name
        position_share = _to_float(position_share_map.get(position_key))
        issuer_share = _to_float(issuer_share_map.get(issuer))

        if position_share is not None and position_share > max_position_share:
            _append_reason(excluded_reasons, "position_share_limit")
            continue
        if issuer_share is not None and issuer_share > max_issuer_share:
            _append_reason(excluded_reasons, "issuer_share_limit")
            continue
        if ytm is None and exclude_without_ytm:
            _append_reason(excluded_reasons, "missing_ytm")
            continue
        if ytm is not None and ytm < min_ytm:
            _append_reason(excluded_reasons, "ytm_below_min")
            continue
        if years_to_maturity is None and exclude_without_maturity:
            _append_reason(excluded_reasons, "missing_maturity")
            continue
        if years_to_maturity is not None and years_to_maturity > max_years_to_maturity:
            _append_reason(excluded_reasons, "maturity_too_long")
            continue

        warning_items: list[str] = []
        if ytm is None:
            warning_items.append("нет YTM")
        if years_to_maturity is None:
            warning_items.append("нет даты погашения")
        if position_share is not None and position_share > warning_share_threshold:
            warning_items.append("высокая доля позиции")
        if issuer_share is not None and issuer_share > warning_share_threshold:
            warning_items.append("высокая доля эмитента")
        if isin and isin in issue_isins:
            warning_items.append("проблемы качества данных")

        current_type = _to_float(current_type_pct.get(asset_type)) or 0.0
        target_type = _to_float(target_type_pct.get(asset_type)) or 0.0
        target_gap_pct = target_type - current_type

        candidates.append(
            {
                "name": name,
                "isin": isin,
                "asset_type": asset_type,
                "issuer": issuer,
                "market_value": market_value,
                "ytm": ytm,
                "years_to_maturity": years_to_maturity,
                "position_share": position_share,
                "issuer_share": issuer_share,
                "target_gap_pct": target_gap_pct,
                "warning_count": len(warning_items),
                "warnings": warning_items,
                "explanation": _build_candidate_explanation(
                    ytm=ytm,
                    min_ytm=min_ytm,
                    position_share=position_share,
                    max_position_share=max_position_share,
                    issuer_share=issuer_share,
                    max_issuer_share=max_issuer_share,
                    years_to_maturity=years_to_maturity,
                    max_years_to_maturity=max_years_to_maturity,
                    target_gap_pct=target_gap_pct,
                    warnings=warning_items,
                ),
            }
        )

    candidates.sort(
        key=lambda row: (
            -(row["ytm"] if row["ytm"] is not None else -1_000_000_000.0),
            row["position_share"] if row["position_share"] is not None else 1_000_000_000.0,
            -(row["target_gap_pct"] if row["target_gap_pct"] is not None else -1_000_000_000.0),
            row["warning_count"],
            str(row["name"]).lower(),
        )
    )

    top_candidates = candidates[:max_candidates]
    suggested_amount = (free_cash / len(top_candidates)) if top_candidates and free_cash > 0 else 0.0
    new_total_value = total_portfolio_value + max(free_cash, 0.0)

    for row in top_candidates:
        row["suggested_amount"] = suggested_amount
        if new_total_value > 0:
            row["projected_position_share"] = (row["market_value"] + suggested_amount) / new_total_value
            issuer_share = row.get("issuer_share")
            if issuer_share is not None and total_portfolio_value > 0:
                issuer_value = issuer_share * total_portfolio_value
                row["projected_issuer_share"] = (issuer_value + suggested_amount) / new_total_value
            else:
                row["projected_issuer_share"] = None
        else:
            row["projected_position_share"] = None
            row["projected_issuer_share"] = None

    excluded_summary = [
        {
            "reason_code": code,
            "reason": get_exclusion_reason_label(code),
            "count": count,
        }
        for code, count in sorted(excluded_reasons.items(), key=lambda item: item[1], reverse=True)
        if count > 0
    ]
    return {
        "candidates": top_candidates,
        "excluded_summary": excluded_summary,
        "total_positions_seen": len(positions),
        "total_bond_positions": total_bond_positions,
    }


def build_reduce_candidates(
    positions: Iterable[Mapping[str, Any]],
    *,
    issuer_by_isin: Mapping[str, str | None],
    ytm_by_isin: Mapping[str, float | None],
    maturity_by_isin: Mapping[str, str | None],
    rating_by_isin: Mapping[str, str | None],
    position_share_map: Mapping[str, float | None],
    issuer_share_map: Mapping[str, float | None],
    data_quality_issue_isins: set[str] | None,
    bond_asset_types: tuple[str, ...],
    factor_enabled: Mapping[str, bool] | None = None,
    factor_weights: Mapping[str, float] | None = None,
    position_share_reference: float = DEFAULT_POSITION_SHARE_REFERENCE,
    issuer_share_reference: float = DEFAULT_ISSUER_SHARE_REFERENCE,
    long_maturity_years: float = DEFAULT_LONG_MATURITY_YEARS,
    low_ytm_base: float = DEFAULT_LOW_YTM_BASE,
    low_ytm_year_slope: float = DEFAULT_LOW_YTM_YEAR_SLOPE,
    as_of_date: date | None = None,
    max_candidates: int = 15,
) -> dict[str, Any]:
    """Сформировать список позиций-кандидатов на сокращение по прозрачному risk_score."""
    positions = list(positions)
    as_of = as_of_date or date.today()
    issue_isins = {str(isin).upper() for isin in (data_quality_issue_isins or set()) if isin}
    enabled = dict(DEFAULT_REDUCE_FACTOR_ENABLED)
    enabled.update({k: bool(v) for k, v in (factor_enabled or {}).items()})
    weights = dict(DEFAULT_REDUCE_FACTOR_WEIGHTS)
    for key, value in (factor_weights or {}).items():
        num = _to_float(value)
        if num is not None and num >= 0:
            weights[key] = num

    total_portfolio_value = 0.0
    market_value_map: dict[str, float] = {}
    for row in positions:
        market_value = concentration.calculate_position_market_value(row)
        if market_value is None or market_value <= 0:
            continue
        key = str(row.get("isin") or row.get("name") or "")
        if key:
            market_value_map[key] = market_value
        total_portfolio_value += market_value

    candidates: list[dict[str, Any]] = []
    for row in positions:
        market_value = concentration.calculate_position_market_value(row)
        if market_value is None or market_value <= 0:
            continue

        asset_type = str(row.get("asset_type") or "")
        is_bond = asset_type in bond_asset_types
        isin = str(row.get("isin") or "").strip().upper()
        name = str(row.get("name") or isin or concentration.UNKNOWN_ISSUER)
        issuer = (
            concentration.normalize_bond_issuer(issuer_by_isin.get(isin) or name, asset_type)
            if is_bond
            else str(row.get("name") or name)
        )
        ytm = _to_float(ytm_by_isin.get(isin)) if is_bond and isin else None
        years_to_maturity = (
            calculate_years_to_maturity(maturity_by_isin.get(isin), as_of)
            if is_bond and isin
            else None
        )
        rating = str(rating_by_isin.get(isin) or "") if is_bond and isin else ""
        has_rating = bool(rating) and classify_rating_bucket(rating) != RATING_BUCKET_UNRATED

        position_key = isin or name
        position_share = _to_float(position_share_map.get(position_key))
        if position_share is None and total_portfolio_value > 0:
            position_share = market_value / total_portfolio_value
        issuer_share = _to_float(issuer_share_map.get(issuer)) if issuer else None

        factor_items: list[dict[str, Any]] = []

        def add_factor(code: str, raw_value: float, details: str) -> None:
            if not enabled.get(code, True):
                return
            if raw_value <= 0:
                return
            weight = float(weights.get(code, 0.0))
            points = raw_value * weight
            if points <= 0:
                return
            factor_items.append(
                {
                    "code": code,
                    "label": REDUCE_FACTOR_LABELS.get(code, code),
                    "raw_value": raw_value,
                    "weight": weight,
                    "points": points,
                    "details": details,
                }
            )

        pos_raw = _normalized_share_risk(position_share, position_share_reference)
        add_factor(
            "position_share",
            pos_raw,
            (
                f"доля позиции {position_share * 100:.2f}% "
                f"при ориентире {position_share_reference * 100:.2f}%"
            ) if position_share is not None else "доля позиции недоступна",
        )
        iss_raw = _normalized_share_risk(issuer_share, issuer_share_reference)
        add_factor(
            "issuer_share",
            iss_raw,
            (
                f"доля эмитента {issuer_share * 100:.2f}% "
                f"при ориентире {issuer_share_reference * 100:.2f}%"
            ) if issuer_share is not None else "доля эмитента недоступна",
        )

        if is_bond:
            add_factor("missing_ytm", 1.0 if ytm is None else 0.0, "нет YTM")
            add_factor(
                "missing_maturity",
                1.0 if years_to_maturity is None else 0.0,
                "нет даты погашения",
            )

            if ytm is not None and years_to_maturity is not None:
                required_ytm = low_ytm_base + max(years_to_maturity - 1.0, 0.0) * low_ytm_year_slope
                low_ytm_raw = max(required_ytm - ytm, 0.0) / required_ytm if required_ytm > 0 else 0.0
                add_factor(
                    "low_ytm_vs_term",
                    low_ytm_raw,
                    f"YTM {ytm:.2f}% ниже условного порога {required_ytm:.2f}% для срока {years_to_maturity:.2f} г.",
                )
            if years_to_maturity is not None and long_maturity_years > 0:
                long_raw = min(max(years_to_maturity - long_maturity_years, 0.0) / long_maturity_years, 1.0)
                add_factor(
                    "long_maturity",
                    long_raw,
                    f"срок до погашения {years_to_maturity:.2f} г. (ориентир {long_maturity_years:.2f} г.)",
                )

            add_factor(
                "missing_rating",
                1.0 if not has_rating else 0.0,
                "нет рейтинга по ISIN" if isin else "нет ISIN для проверки рейтинга",
            )

        if isin and isin in issue_isins:
            add_factor("data_quality", 1.0, "есть проблемы качества данных")

        if not factor_items:
            continue

        factor_items.sort(key=lambda item: float(item["points"]), reverse=True)
        risk_score = sum(float(item["points"]) for item in factor_items)
        reasons = [f"{item['label']}: {item['details']}" for item in factor_items]

        candidates.append(
            {
                "name": name,
                "isin": isin or "—",
                "asset_type": asset_type,
                "issuer": issuer or "—",
                "market_value": market_value,
                "position_share": position_share,
                "issuer_share": issuer_share,
                "ytm": ytm,
                "years_to_maturity": years_to_maturity,
                "rating": rating or "",
                "risk_score": risk_score,
                "severity": _risk_severity(risk_score),
                "factor_count": len(factor_items),
                "factors": factor_items,
                "reason": "; ".join(reasons),
                "suggested_action": "можно рассмотреть частичное снижение позиции",
            }
        )

    candidates.sort(
        key=lambda row: (
            -float(row.get("risk_score") or 0.0),
            -(_to_float(row.get("position_share")) or 0.0),
            -(_to_float(row.get("issuer_share")) or 0.0),
            -(_to_float(row.get("market_value")) or 0.0),
            str(row.get("name") or "").lower(),
        )
    )

    return {
        "candidates": candidates[:max_candidates],
        "enabled_factors": enabled,
        "weights": weights,
    }
