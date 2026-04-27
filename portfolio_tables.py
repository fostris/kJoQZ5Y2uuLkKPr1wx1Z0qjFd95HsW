"""Подготовка DataFrame для таблиц портфеля."""

from __future__ import annotations

from typing import Mapping, Iterable

import pandas as pd

from portfolio_metrics import add_pnl_columns, calculate_total_position_value


def prepare_positions_dataset(
    pos_df: pd.DataFrame,
    type_filter: Iterable[str],
    bond_asset_types: tuple[str, ...],
    ytm_by_isin: Mapping[str, float | None],
    issuer_by_isin: Mapping[str, str | None],
    issuer_share_map: Mapping[str, float | None],
    position_share_map: Mapping[str, float | None],
    cost_map: Mapping[str, Mapping],
    sort_col: str,
) -> pd.DataFrame:
    """Фильтрация, обогащение и сортировка позиций для UI."""
    filtered = pos_df[pos_df["asset_type"].isin(list(type_filter))].copy()

    filtered["ytm"] = filtered["isin"].map(ytm_by_isin)
    filtered.loc[~filtered["asset_type"].isin(bond_asset_types), "ytm"] = None

    filtered["issuer"] = filtered["isin"].map(issuer_by_isin)
    bond_mask = filtered["asset_type"].isin(bond_asset_types)
    missing_issuer_mask = bond_mask & filtered["issuer"].isna()
    filtered.loc[missing_issuer_mask, "issuer"] = filtered.loc[missing_issuer_mask, "name"]
    filtered.loc[~bond_mask, "issuer"] = None

    filtered["issuer_share"] = filtered["issuer"].map(issuer_share_map)
    filtered.loc[~bond_mask, "issuer_share"] = None

    key_series = filtered["isin"].where(filtered["isin"].notna() & (filtered["isin"] != ""), filtered["name"])
    filtered["position_share"] = key_series.map(position_share_map)

    filtered = add_pnl_columns(filtered, cost_map)

    sort_map = {
        "По стоимости": ("value_end", False),
        "По изменению": ("change_value", False),
        "По P&L": ("pnl", False),
        "По YTM": ("ytm", False),
        "По имени": ("name", True),
    }

    col, asc = sort_map[sort_col]
    if col == "pnl":
        filtered["_sort"] = filtered["pnl"].fillna(0)
        filtered = filtered.sort_values("_sort", ascending=asc).drop(columns=["_sort"])
    elif col == "ytm":
        filtered["_sort"] = filtered["ytm"].fillna(float("-inf"))
        filtered = filtered.sort_values("_sort", ascending=asc).drop(columns=["_sort"])
    else:
        filtered = filtered.sort_values(col, ascending=asc)

    return filtered


def prepare_positions_display_table(
    filtered: pd.DataFrame,
    type_labels: Mapping[str, str],
    format_ytm_fn,
) -> pd.DataFrame:
    """Подготовка итоговой таблицы позиций для st.dataframe."""
    display_df = filtered[[
        "name", "asset_type", "issuer", "qty", "avg_price", "price_end", "ytm",
        "position_share", "issuer_share", "value_end", "nkd_end", "change_value", "pnl", "pnl_pct"
    ]].copy()

    display_df["Тип"] = display_df["asset_type"].map(type_labels)
    display_df["Полная стоимость"] = display_df.apply(
        lambda row: calculate_total_position_value(row["value_end"], row["nkd_end"]),
        axis=1,
    )

    display_df = display_df.rename(columns={
        "name": "Инструмент",
        "issuer": "Эмитент",
        "qty": "Кол-во",
        "avg_price": "Ср. цена",
        "price_end": "Цена",
        "ytm": "YTM",
        "position_share": "Доля портфеля %",
        "issuer_share": "Доля эмитента %",
        "value_end": "Стоимость",
        "nkd_end": "НКД",
        "change_value": "Δ за день",
        "pnl": "P&L ₽",
        "pnl_pct": "P&L %",
    })

    display_df["YTM"] = display_df["YTM"].map(format_ytm_fn)
    display_df["Доля портфеля %"] = display_df["Доля портфеля %"].apply(lambda v: v * 100 if v is not None else None)
    display_df["Доля эмитента %"] = display_df["Доля эмитента %"].apply(lambda v: v * 100 if v is not None else None)
    display_df["Эмитент"] = display_df["Эмитент"].fillna("—")
    return display_df
