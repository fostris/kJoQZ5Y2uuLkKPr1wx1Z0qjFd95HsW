"""Чистые расчёты для вкладки ребалансировки."""

from __future__ import annotations

from typing import Mapping

import pandas as pd


DEFAULT_TARGETS = {
    "bond_ofz_pd": 10.0,
    "bond_ofz_in": 10.0,
    "bond_corp": 40.0,
    "etf": 10.0,
    "stock": 30.0,
}


def build_current_allocation(pos_df: pd.DataFrame, type_labels: Mapping[str, str]) -> tuple[pd.DataFrame, float]:
    """Текущее распределение по типам активов."""
    if pos_df.empty:
        out = pd.DataFrame(columns=["asset_type", "value", "nkd", "count", "total", "current_pct", "label"])
        return out, 0.0

    type_agg = pos_df.groupby("asset_type").agg(
        value=("value_end", "sum"),
        nkd=("nkd_end", "sum"),
        count=("name", "count"),
    ).reset_index()
    type_agg["total"] = type_agg["value"] + type_agg["nkd"]
    total_portfolio = float(type_agg["total"].sum())
    type_agg["current_pct"] = (type_agg["total"] / total_portfolio * 100).round(2) if total_portfolio > 0 else 0.0
    type_agg["label"] = type_agg["asset_type"].map(type_labels)
    return type_agg, total_portfolio


def build_rebalance_comparison(
    type_agg: pd.DataFrame,
    new_targets: Mapping[str, float],
    type_labels: Mapping[str, str],
    total_portfolio: float,
) -> pd.DataFrame:
    """Таблица сравнения текущее vs целевое."""
    comparison = []
    for atype, label in type_labels.items():
        row = type_agg[type_agg["asset_type"] == atype]
        current_val = float(row["total"].values[0]) if len(row) > 0 else 0.0
        current_pct = float(row["current_pct"].values[0]) if len(row) > 0 else 0.0
        target_pct = float(new_targets.get(atype, 0.0))
        target_val = total_portfolio * target_pct / 100
        diff_val = current_val - target_val
        diff_pct = current_pct - target_pct

        comparison.append({
            "Тип": label,
            "asset_type": atype,
            "Текущая ₽": current_val,
            "Текущая %": current_pct,
            "Целевая %": target_pct,
            "Целевая ₽": target_val,
            "Отклонение ₽": diff_val,
            "Отклонение %": diff_pct,
        })

    return pd.DataFrame(comparison)


def split_rebalance_gaps(comp_df: pd.DataFrame, tolerance_rub: float = 100.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Разделение на перевес/недовес с допуском в рублях."""
    overweight = comp_df[comp_df["Отклонение ₽"] > tolerance_rub].sort_values("Отклонение ₽", ascending=False)
    underweight = comp_df[comp_df["Отклонение ₽"] < -tolerance_rub].sort_values("Отклонение ₽")
    return overweight, underweight
