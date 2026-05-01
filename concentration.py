"""Расчёт метрик концентрации рисков портфеля облигаций."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

MAX_POSITION_SHARE = 0.10
MAX_ISSUER_SHARE = 0.10
MAX_SECTOR_SHARE = 0.30
MAX_ISSUER_GROUP_SHARE = 0.30
MAX_CORPORATE_BONDS_SHARE = 0.70
MAX_ISSUER_HHI = 0.18
MAX_POSITION_HHI = 0.18
CONCENTRATION_SEVERITY_THRESHOLDS = (
    (0.20, "critical"),
    (0.15, "high"),
    (0.10, "warning"),
    (0.05, "info"),
)
SEVERITY_PRIORITY = {"info": 0, "warning": 1, "high": 2, "critical": 3}

BOND_ASSET_TYPES = ("bond_ofz_pd", "bond_ofz_in", "bond_corp")
OFZ_ASSET_TYPES = ("bond_ofz_pd", "bond_ofz_in")
CORPORATE_BOND_TYPE = "bond_corp"
MINFIN_ISSUER = "Минфин РФ"
UNKNOWN_ISSUER = "Unknown"
UNKNOWN_SECTOR = "Не указан"


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_text_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text


def _build_issuer_reference_lookup(
    issuer_reference_by_name: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Mapping[str, Any]]:
    if not issuer_reference_by_name:
        return {}

    lookup: dict[str, Mapping[str, Any]] = {}
    for issuer_name, row in issuer_reference_by_name.items():
        key = _normalize_text_key(issuer_name)
        if not key:
            continue
        lookup[key] = row
    return lookup


def _resolve_issuer_reference(
    issuer_name: str,
    reference_lookup: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if not issuer_name:
        return None
    return reference_lookup.get(_normalize_text_key(issuer_name))


def normalize_bond_issuer(issuer_name: str | None, asset_type: str | None) -> str:
    """Нормализовать имя эмитента для кредитного риска (ОФЗ + линкеры = Минфин РФ)."""
    normalized_asset_type = str(asset_type or "").strip()
    if normalized_asset_type in OFZ_ASSET_TYPES:
        return MINFIN_ISSUER
    issuer = str(issuer_name or "").strip()
    return issuer or UNKNOWN_ISSUER


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
    issuer_reference_by_name: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Группировка облигаций по эмитенту и расчёт долей эмитентов."""
    issuer_by_isin = issuer_by_isin or {}
    reference_lookup = _build_issuer_reference_lookup(issuer_reference_by_name)

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
        issuer = normalize_bond_issuer(issuer, str(asset_type or ""))

        by_issuer_value[issuer] += market_value
        if isin:
            by_issuer_isins[issuer].add(isin)

    results: list[dict[str, Any]] = []
    for issuer, market_value in by_issuer_value.items():
        ref = _resolve_issuer_reference(issuer, reference_lookup) or {}
        issuer_group = str(ref.get("issuer_group") or "").strip() or issuer
        sector = str(ref.get("sector") or "").strip() or UNKNOWN_SECTOR
        issuer_type = str(ref.get("issuer_type") or "").strip()
        comment = str(ref.get("comment") or "").strip()

        share = (market_value / total_portfolio_value) if total_portfolio_value > 0 else None
        issues_count = len(by_issuer_isins.get(issuer, set()))
        results.append(
            {
                "issuer": issuer,
                "issuer_group": issuer_group,
                "sector": sector,
                "issuer_type": issuer_type,
                "comment": comment,
                "market_value": market_value,
                "issuer_share": share,
                "issues_count": issues_count,
                "limit_breach": bool(share is not None and share > MAX_ISSUER_SHARE),
            }
        )

    results.sort(key=lambda x: x["market_value"], reverse=True)
    return results, fallback_count


def group_positions_by_asset_type(
    positions_with_share: list[Mapping[str, Any]],
    total_portfolio_value: float,
) -> list[dict[str, Any]]:
    """Распределение портфеля по типам активов."""
    by_type_value: dict[str, float] = defaultdict(float)
    by_type_count: dict[str, int] = defaultdict(int)

    for row in positions_with_share:
        market_value = _to_float(row.get("market_value"))
        if market_value is None or market_value <= 0:
            continue
        asset_type = str(row.get("asset_type") or "").strip() or "unknown"
        by_type_value[asset_type] += market_value
        by_type_count[asset_type] += 1

    results: list[dict[str, Any]] = []
    for asset_type, market_value in by_type_value.items():
        share = (market_value / total_portfolio_value) if total_portfolio_value > 0 else None
        results.append(
            {
                "asset_type": asset_type,
                "market_value": market_value,
                "asset_type_share": share,
                "positions_count": by_type_count.get(asset_type, 0),
            }
        )

    results.sort(key=lambda x: x["market_value"], reverse=True)
    return results


def aggregate_issuer_dimension(
    issuer_rows: list[Mapping[str, Any]],
    total_portfolio_value: float,
    field_name: str,
    fallback_label: str,
) -> list[dict[str, Any]]:
    """Собрать концентрацию по атрибуту эмитента (сектор/группа)."""
    by_dimension_value: dict[str, float] = defaultdict(float)
    by_dimension_issuers: dict[str, set[str]] = defaultdict(set)

    for row in issuer_rows:
        market_value = _to_float(row.get("market_value"))
        if market_value is None or market_value <= 0:
            continue

        issuer = str(row.get("issuer") or UNKNOWN_ISSUER)
        dimension_value = str(row.get(field_name) or "").strip() or fallback_label
        by_dimension_value[dimension_value] += market_value
        by_dimension_issuers[dimension_value].add(issuer)

    results: list[dict[str, Any]] = []
    for dimension_value, market_value in by_dimension_value.items():
        share = (market_value / total_portfolio_value) if total_portfolio_value > 0 else None
        results.append(
            {
                field_name: dimension_value,
                "market_value": market_value,
                "dimension_share": share,
                "issuers_count": len(by_dimension_issuers.get(dimension_value, set())),
                "issuers": sorted(by_dimension_issuers.get(dimension_value, set())),
            }
        )

    results.sort(key=lambda x: x["market_value"], reverse=True)
    return results


def build_concentration_warnings(
    warning_items: list[Mapping[str, Any]],
) -> list[str]:
    """Совместимый плоский список текстов предупреждений."""
    return [str(item.get("text")) for item in warning_items if item.get("text")]


def _classify_share_severity(share: float | None) -> str | None:
    if share is None:
        return None
    for threshold, severity in CONCENTRATION_SEVERITY_THRESHOLDS:
        if share >= threshold:
            return severity
    return None


def build_concentration_warning_items(
    position_rows: list[Mapping[str, Any]],
    issuer_rows: list[Mapping[str, Any]],
    corporate_bonds_share: float | None,
    position_hhi: float | None,
    issuer_hhi: float | None,
    sector_rows: list[Mapping[str, Any]] | None = None,
    issuer_group_rows: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Структурированные предупреждения концентрации с severity."""
    warnings: list[dict[str, Any]] = []

    for row in position_rows:
        share = _to_float(row.get("position_share"))
        severity = _classify_share_severity(share)
        if share is not None and severity is not None:
            warnings.append(
                {
                    "kind": "position_share",
                    "severity": severity,
                    "share": share,
                    "text": (
                        f"Позиция '{row.get('name', 'Unknown')}' занимает "
                        f"{share * 100:.1f}% портфеля."
                    ),
                }
            )

    for row in issuer_rows:
        share = _to_float(row.get("issuer_share"))
        severity = _classify_share_severity(share)
        if share is not None and severity is not None:
            warnings.append(
                {
                    "kind": "issuer_share",
                    "severity": severity,
                    "share": share,
                    "text": (
                        f"Эмитент '{row.get('issuer', UNKNOWN_ISSUER)}' занимает "
                        f"{share * 100:.1f}% портфеля."
                    ),
                }
            )

    for row in (sector_rows or []):
        share = _to_float(row.get("dimension_share"))
        if share is None or share <= MAX_SECTOR_SHARE:
            continue
        warnings.append(
            {
                "kind": "sector_share",
                "severity": "warning",
                "share": share,
                "text": (
                    f"Сектор '{row.get('sector', UNKNOWN_SECTOR)}' занимает "
                    f"{share * 100:.1f}% портфеля (> {MAX_SECTOR_SHARE * 100:.0f}%)."
                ),
            }
        )

    for row in (issuer_group_rows or []):
        share = _to_float(row.get("dimension_share"))
        if share is None or share <= MAX_ISSUER_GROUP_SHARE:
            continue
        warnings.append(
            {
                "kind": "issuer_group_share",
                "severity": "warning",
                "share": share,
                "text": (
                    f"Группа эмитентов '{row.get('issuer_group', UNKNOWN_ISSUER)}' занимает "
                    f"{share * 100:.1f}% портфеля (> {MAX_ISSUER_GROUP_SHARE * 100:.0f}%)."
                ),
            }
        )

    if corporate_bonds_share is not None and corporate_bonds_share > MAX_CORPORATE_BONDS_SHARE:
        warnings.append(
            {
                "kind": "corporate_bonds_share",
                "severity": "warning",
                "share": corporate_bonds_share,
                "text": (
                    f"Доля корпоративных облигаций {corporate_bonds_share * 100:.1f}% "
                    f"(> {MAX_CORPORATE_BONDS_SHARE * 100:.0f}%)."
                ),
            }
        )

    if issuer_hhi is not None and issuer_hhi > MAX_ISSUER_HHI:
        warnings.append(
            {
                "kind": "issuer_hhi",
                "severity": "warning",
                "hhi": issuer_hhi,
                "text": f"HHI по эмитентам {issuer_hhi:.3f} (> {MAX_ISSUER_HHI:.2f}).",
            }
        )

    if position_hhi is not None and position_hhi > MAX_POSITION_HHI:
        warnings.append(
            {
                "kind": "position_hhi",
                "severity": "warning",
                "hhi": position_hhi,
                "text": f"HHI по позициям {position_hhi:.3f} (> {MAX_POSITION_HHI:.2f}).",
            }
        )

    warnings.sort(
        key=lambda item: (
            SEVERITY_PRIORITY.get(str(item.get("severity", "info")), 0),
            _to_float(item.get("share")) or 0.0,
        ),
        reverse=True,
    )

    return warnings


def calculate_concentration_metrics(
    positions: list[Mapping[str, Any]],
    issuer_by_isin: Mapping[str, str | None] | None = None,
    issuer_reference_by_name: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Комплексный расчёт концентрации: доли, HHI, предупреждения."""
    position_rows, total_portfolio_value = calculate_position_shares(positions)

    issuer_rows, issuer_fallback_count = group_bond_positions_by_issuer(
        positions_with_share=position_rows,
        total_portfolio_value=total_portfolio_value,
        issuer_by_isin=issuer_by_isin,
        issuer_reference_by_name=issuer_reference_by_name,
    )
    sector_rows = aggregate_issuer_dimension(
        issuer_rows=issuer_rows,
        total_portfolio_value=total_portfolio_value,
        field_name="sector",
        fallback_label=UNKNOWN_SECTOR,
    )
    issuer_group_rows = aggregate_issuer_dimension(
        issuer_rows=issuer_rows,
        total_portfolio_value=total_portfolio_value,
        field_name="issuer_group",
        fallback_label=UNKNOWN_ISSUER,
    )
    asset_type_rows = group_positions_by_asset_type(
        positions_with_share=position_rows,
        total_portfolio_value=total_portfolio_value,
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

    warning_items = build_concentration_warning_items(
        position_rows=position_rows,
        issuer_rows=issuer_rows,
        sector_rows=sector_rows,
        issuer_group_rows=issuer_group_rows,
        corporate_bonds_share=corporate_bonds_share,
        position_hhi=position_hhi,
        issuer_hhi=issuer_hhi,
    )
    warnings = build_concentration_warnings(warning_items)

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
        "warning_items": warning_items,
        "issuer_fallback_count": issuer_fallback_count,
        "sectors": sector_rows,
        "issuer_groups": issuer_group_rows,
        "asset_types": asset_type_rows,
    }
