"""Подготовка DataFrame для таблиц портфеля."""

from __future__ import annotations

from datetime import date
from typing import Mapping, Iterable

import pandas as pd

from analytics.bonds import (
    calculate_days_to_maturity,
    calculate_price_to_nominal_pct_and_status,
    calculate_years_to_maturity,
)
from portfolio_metrics import add_pnl_columns, calculate_total_position_value

POSITIONS_TABLE_VIEW_MODES = (
    "Все колонки",
    "Обзор",
    "Доходность",
    "Риск",
    "Календарь",
    "P&L",
    "Качество данных",
)

POSITIONS_TABLE_COLUMNS_BY_MODE = {
    "Все колонки": [
        "Инструмент",
        "Тип",
        "Эмитент",
        "Кол-во",
        "Ср. цена",
        "Цена",
        "YTM",
        "Дней до погашения",
        "Лет до погашения",
        "Цена к номиналу %",
        "Статус к номиналу",
        "Доля портфеля %",
        "Доля эмитента %",
        "Полная стоимость",
        "Δ за день",
        "P&L ₽",
        "P&L %",
    ],
    "Обзор": [
        "Инструмент",
        "Тип",
        "Эмитент",
        "Доля портфеля %",
        "Доля эмитента %",
        "Полная стоимость",
        "Δ за день",
    ],
    "Доходность": [
        "Инструмент",
        "Тип",
        "YTM",
        "Ср. цена",
        "Цена",
        "P&L ₽",
        "P&L %",
        "Полная стоимость",
    ],
    "Риск": [
        "Инструмент",
        "Тип",
        "Эмитент",
        "Доля портфеля %",
        "Доля эмитента %",
        "YTM",
        "Лет до погашения",
        "Цена к номиналу %",
        "Статус к номиналу",
        "Полная стоимость",
    ],
    "Календарь": [
        "Инструмент",
        "Тип",
        "Дней до погашения",
        "Лет до погашения",
        "YTM",
        "Полная стоимость",
    ],
    "P&L": [
        "Инструмент",
        "Тип",
        "Ср. цена",
        "Цена",
        "Δ за день",
        "P&L ₽",
        "P&L %",
        "Полная стоимость",
    ],
    "Качество данных": [
        "Инструмент",
        "Тип",
        "Эмитент",
        "YTM",
        "Ср. цена",
        "Цена",
        "Дней до погашения",
        "Лет до погашения",
        "Цена к номиналу %",
        "Статус к номиналу",
        "Полная стоимость",
    ],
}


def get_positions_table_columns(view_mode: str, available_columns: Iterable[str]) -> list[str]:
    """Подобрать колонки для выбранного режима, безопасно пропуская отсутствующие."""
    available = list(available_columns)
    mode = view_mode if view_mode in POSITIONS_TABLE_COLUMNS_BY_MODE else "Все колонки"
    preferred = POSITIONS_TABLE_COLUMNS_BY_MODE[mode]
    columns = [column for column in preferred if column in available]
    return columns if columns else available


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
    maturity_by_isin: Mapping[str, str | None] | None = None,
    as_of_date: date | None = None,
) -> pd.DataFrame:
    """Фильтрация, обогащение и сортировка позиций для UI."""
    maturity_by_isin = maturity_by_isin or {}
    as_of_date = as_of_date or date.today()

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

    filtered["days_to_maturity"] = filtered["isin"].map(
        lambda isin: calculate_days_to_maturity(maturity_by_isin.get(isin), as_of_date)
        if isinstance(isin, str) and isin else None
    )
    filtered["years_to_maturity"] = filtered["isin"].map(
        lambda isin: calculate_years_to_maturity(maturity_by_isin.get(isin), as_of_date)
        if isinstance(isin, str) and isin else None
    )
    filtered.loc[~bond_mask, ["days_to_maturity", "years_to_maturity"]] = None

    premium_discount_data = filtered.apply(
        lambda row: calculate_price_to_nominal_pct_and_status(
            asset_type=row.get("asset_type"),
            price_end=row.get("price_end"),
            nominal=row.get("nominal"),
            bond_asset_types=bond_asset_types,
        ),
        axis=1,
        result_type="expand",
    )
    filtered["price_to_nominal_pct"] = premium_discount_data[0]
    filtered["premium_discount_status"] = premium_discount_data[1]

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
        "days_to_maturity", "years_to_maturity",
        "price_to_nominal_pct", "premium_discount_status",
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
        "days_to_maturity": "Дней до погашения",
        "years_to_maturity": "Лет до погашения",
        "price_to_nominal_pct": "Цена к номиналу %",
        "premium_discount_status": "Статус к номиналу",
        "position_share": "Доля портфеля %",
        "issuer_share": "Доля эмитента %",
        "value_end": "Стоимость",
        "nkd_end": "НКД",
        "change_value": "Δ за день",
        "pnl": "P&L ₽",
        "pnl_pct": "P&L %",
    })

    display_df["YTM"] = display_df["YTM"].map(format_ytm_fn)
    display_df["Дней до погашения"] = display_df["Дней до погашения"].apply(
        lambda v: int(v) if pd.notna(v) else "нет данных"
    )
    display_df["Лет до погашения"] = display_df["Лет до погашения"].apply(
        lambda v: f"{v:.2f}" if pd.notna(v) else "нет данных"
    )
    display_df["Цена к номиналу %"] = display_df["Цена к номиналу %"].apply(
        lambda v: f"{v:.2f}" if pd.notna(v) else "нет данных"
    )
    display_df["Статус к номиналу"] = display_df["Статус к номиналу"].fillna("нет данных")
    display_df["Доля портфеля %"] = display_df["Доля портфеля %"].apply(lambda v: v * 100 if v is not None else None)
    display_df["Доля эмитента %"] = display_df["Доля эмитента %"].apply(lambda v: v * 100 if v is not None else None)
    display_df["Эмитент"] = display_df["Эмитент"].fillna("—")
    return display_df
