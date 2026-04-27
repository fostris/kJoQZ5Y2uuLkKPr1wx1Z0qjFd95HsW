"""Агрегаты рейтингов облигаций по ручному справочнику."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

import concentration

RATING_BUCKET_AAA = "AAA"
RATING_BUCKET_AA = "AA"
RATING_BUCKET_A = "A"
RATING_BUCKET_BBB_OR_LOWER = "BBB и ниже"
RATING_BUCKET_UNRATED = "Без рейтинга"
RATING_BUCKETS = (
    RATING_BUCKET_AAA,
    RATING_BUCKET_AA,
    RATING_BUCKET_A,
    RATING_BUCKET_BBB_OR_LOWER,
    RATING_BUCKET_UNRATED,
)
UNRATED_MARKERS = {"NR", "N/R", "UNRATED", "NO RATING", "NOTRATED", "NA", "N/A"}


def normalize_rating_text(value: Any) -> str:
    """Нормализовать строку рейтинга для классификации."""
    return str(value or "").strip().upper().replace(" ", "")


def classify_rating_bucket(rating: Any) -> str:
    """Сопоставить конкретный рейтинг с корзиной для отчёта."""
    normalized = normalize_rating_text(rating)
    if not normalized:
        return RATING_BUCKET_UNRATED

    if normalized in UNRATED_MARKERS:
        return RATING_BUCKET_UNRATED

    if normalized.startswith("RU"):
        normalized = normalized[2:]

    if normalized.startswith("AAA"):
        return RATING_BUCKET_AAA
    if normalized.startswith("AA"):
        return RATING_BUCKET_AA
    if normalized.startswith("A"):
        return RATING_BUCKET_A
    return RATING_BUCKET_BBB_OR_LOWER


def build_rating_distribution(
    positions: Iterable[Mapping[str, Any]],
    rating_by_isin: Mapping[str, Any] | None,
    bond_asset_types: tuple[str, ...],
) -> dict[str, Any]:
    """Рассчитать доли облигационной части по корзинам кредитных рейтингов."""
    rating_by_isin = rating_by_isin or {}
    by_bucket_value = {bucket: 0.0 for bucket in RATING_BUCKETS}
    by_bucket_count = {bucket: 0 for bucket in RATING_BUCKETS}
    total_bond_value = 0.0

    for row in positions:
        if row.get("asset_type") not in bond_asset_types:
            continue
        market_value = concentration.calculate_position_market_value(row)
        if market_value is None or market_value <= 0:
            continue

        isin = str(row.get("isin") or "").strip().upper()
        rating = rating_by_isin.get(isin) if isin else None
        bucket = classify_rating_bucket(rating)
        by_bucket_value[bucket] += market_value
        by_bucket_count[bucket] += 1
        total_bond_value += market_value

    rows: list[dict[str, Any]] = []
    for bucket in RATING_BUCKETS:
        bucket_value = by_bucket_value[bucket]
        rows.append(
            {
                "bucket": bucket,
                "market_value": bucket_value,
                "share": (bucket_value / total_bond_value) if total_bond_value > 0 else None,
                "bonds_count": by_bucket_count[bucket],
            }
        )

    share_map = {row["bucket"]: row["share"] for row in rows}
    return {
        "rows": rows,
        "total_bond_value": total_bond_value,
        "share_map": share_map,
        "unrated_share": share_map.get(RATING_BUCKET_UNRATED),
    }

