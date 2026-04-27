"""Расчёт метрик концентрации рисков портфеля облигаций."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

MAX_POSITION_SHARE = 0.10
MAX_ISSUER_SHARE = 0.10
MAX_CORPORATE_BONDS_SHARE = 0.70
MAX_ISSUER_HHI = 0.18
MAX_POSITION_HHI = 0.18

BOND_ASSET_TYPES = ("bond_ofz_pd", "bond_ofz_in", "bond_corp")
CORPORATE_BOND_TYPE = "bond_corp"
UNKNOWN_ISSUER = "Unknown"


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def calculate_position_market_value(position: Mapping[str, Any]) -> float | None:
    """Рыночная стоимость позиции (использует готовое value_end, fallback на price*qty)."""
    value_end = _to_float(position.get("value_end"))
    nkd_end = _to_float(position.get("nkd_end")) or 0.0

    if value_end is not None:
        return value_end + nkd_end

    qty = _to_float(position.get("qty"))
    price_end = _to_float(position.get("price_end"))
    if qty is None or price_end is None:
        return None

    asset_type = str(position.get("asset_type") or "")
    if asset_type in BOND_ASSET_TYPES:
        nominal = _to_float(position.get("nominal")) or 1000.0
        return qty * nominal * (price_end / 100.0) + nkd_end

    return qty * price_end


def compute_hhi(shares: list[float | None]) -> float | None:
    """Herfindahl-Hirschman Index: сумма квадратов долей (0..1)."""
    valid = [s for s in shares if s is not None and s >= 0]
    if not valid:
        return None
    return sum(s * s for s in valid)


def calculate_position_shares(positions: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], float]:
    """Доли позиций относительно общей стоимости портфеля."""
    rows: list[dict[str, Any]] = []
    total = 0.0

    for pos in positions:
        market_value = calculate_position_market_value(pos)
        row = dict(pos)
        row["market_value"] = market_value
        rows.append(row)

        if market_value is not None and market_value > 0:
            total += market_value

    if total > 0:
        for row in rows:
            mv = row.get("market_value")
            row["position_share"] = (mv / total) if isinstance(mv, (int, float)) else None
    else:
        for row in rows:
            row["position_share"] = None

    return rows, total


def group_bond_positions_by_issuer(
    positions_with_share: list[Mapping[str, Any]],
    total_portfolio_value: float,
    issuer_by_isin: Mapping[str, str | None] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Группировка облигаций по эмитенту и расчёт долей эмитентов."""
    issuer_by_isin = issuer_by_isin or {}

    by_issuer_value: dict[str, float] = defaultdict(float)
    by_issuer_isins: dict[str, set[str]] = defaultdict(set)
    fallback_count = 0

    for row in positions_with_share:
        asset_type = row.get("asset_type")
        if asset_type not in BOND_ASSET_TYPES:
            continue

        market_value = _to_float(row.get("market_value"))
        if market_value is None or market_value <= 0:
            continue

        isin = str(row.get("isin") or "")

        issuer = issuer_by_isin.get(isin)
        if not issuer:
            # Временный fallback: если эмитент недоступен в данных/API, группируем по имени выпуска.
            issuer = str(row.get("name") or row.get("isin") or UNKNOWN_ISSUER)
            fallback_count += 1

        by_issuer_value[issuer] += market_value
        if isin:
            by_issuer_isins[issuer].add(isin)

    results: list[dict[str, Any]] = []
    for issuer, market_value in by_issuer_value.items():
        share = (market_value / total_portfolio_value) if total_portfolio_value > 0 else None
        issues_count = len(by_issuer_isins.get(issuer, set()))
        results.append(
            {
                "issuer": issuer,
                "market_value": market_value,
                "issuer_share": share,
                "issues_count": issues_count,
                "limit_breach": bool(share is not None and share > MAX_ISSUER_SHARE),
            }
        )

    results.sort(key=lambda x: x["market_value"], reverse=True)
    return results, fallback_count


def build_concentration_warnings(
    position_rows: list[Mapping[str, Any]],
    issuer_rows: list[Mapping[str, Any]],
    corporate_bonds_share: float | None,
    position_hhi: float | None,
    issuer_hhi: float | None,
) -> list[str]:
    """Текстовые предупреждения при превышении лимитов."""
    warnings: list[str] = []

    for row in position_rows:
        share = _to_float(row.get("position_share"))
        if share is not None and share > MAX_POSITION_SHARE:
            warnings.append(
                f"Позиция '{row.get('name', 'Unknown')}' занимает {share * 100:.1f}% портфеля (> {MAX_POSITION_SHARE * 100:.0f}%)."
            )

    for row in issuer_rows:
        share = _to_float(row.get("issuer_share"))
        if share is not None and share > MAX_ISSUER_SHARE:
            warnings.append(
                f"Эмитент '{row.get('issuer', UNKNOWN_ISSUER)}' занимает {share * 100:.1f}% портфеля (> {MAX_ISSUER_SHARE * 100:.0f}%)."
            )

    if corporate_bonds_share is not None and corporate_bonds_share > MAX_CORPORATE_BONDS_SHARE:
        warnings.append(
            f"Доля корпоративных облигаций {corporate_bonds_share * 100:.1f}% (> {MAX_CORPORATE_BONDS_SHARE * 100:.0f}%)."
        )

    if issuer_hhi is not None and issuer_hhi > MAX_ISSUER_HHI:
        warnings.append(f"HHI по эмитентам {issuer_hhi:.3f} (> {MAX_ISSUER_HHI:.2f}).")

    if position_hhi is not None and position_hhi > MAX_POSITION_HHI:
        warnings.append(f"HHI по позициям {position_hhi:.3f} (> {MAX_POSITION_HHI:.2f}).")

    return warnings


def calculate_concentration_metrics(
    positions: list[Mapping[str, Any]],
    issuer_by_isin: Mapping[str, str | None] | None = None,
) -> dict[str, Any]:
    """Комплексный расчёт концентрации: доли, HHI, предупреждения."""
    position_rows, total_portfolio_value = calculate_position_shares(positions)

    issuer_rows, issuer_fallback_count = group_bond_positions_by_issuer(
        positions_with_share=position_rows,
        total_portfolio_value=total_portfolio_value,
        issuer_by_isin=issuer_by_isin,
    )

    largest_position = None
    for row in position_rows:
        share = _to_float(row.get("position_share"))
        if share is None:
            continue
        if largest_position is None or share > largest_position["position_share"]:
            largest_position = row

    largest_issuer = issuer_rows[0] if issuer_rows else None

    corp_value = 0.0
    for row in position_rows:
        if row.get("asset_type") != CORPORATE_BOND_TYPE:
            continue
        mv = _to_float(row.get("market_value"))
        if mv is not None and mv > 0:
            corp_value += mv

    corporate_bonds_share = (corp_value / total_portfolio_value) if total_portfolio_value > 0 else None

    position_hhi = compute_hhi([_to_float(r.get("position_share")) for r in position_rows])
    issuer_hhi = compute_hhi([_to_float(r.get("issuer_share")) for r in issuer_rows])

    warnings = build_concentration_warnings(
        position_rows=position_rows,
        issuer_rows=issuer_rows,
        corporate_bonds_share=corporate_bonds_share,
        position_hhi=position_hhi,
        issuer_hhi=issuer_hhi,
    )

    return {
        "positions": position_rows,
        "issuers": issuer_rows,
        "total_portfolio_value": total_portfolio_value,
        "largest_position_share": _to_float(largest_position.get("position_share")) if largest_position else None,
        "largest_position_name": largest_position.get("name") if largest_position else None,
        "largest_issuer_share": _to_float(largest_issuer.get("issuer_share")) if largest_issuer else None,
        "largest_issuer_name": largest_issuer.get("issuer") if largest_issuer else None,
        "corporate_bonds_share": corporate_bonds_share,
        "position_hhi": position_hhi,
        "issuer_hhi": issuer_hhi,
        "warnings": warnings,
        "issuer_fallback_count": issuer_fallback_count,
    }
