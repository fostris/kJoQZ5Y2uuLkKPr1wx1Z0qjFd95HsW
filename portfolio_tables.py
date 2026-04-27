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
        "Рейтинг",
        "Эмитент",
        "Кол-во",
        "Ср. цена",
        "Цена",
        "YTM",
        "Дней до погашения",
        "Лет до погашения",
        "Цена к номиналу %",
        "Статус к номиналу",
        "flags",
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
        "Рейтинг",
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
        "Рейтинг",
        "Эмитент",
        "Доля портфеля %",
        "Доля эмитента %",
        "YTM",
        "Лет до погашения",
        "Цена к номиналу %",
        "Статус к номиналу",
        "flags",
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
        "Рейтинг",
        "Эмитент",
        "YTM",
        "Ср. цена",
        "Цена",
        "Дней до погашения",
        "Лет до погашения",
        "Цена к номиналу %",
        "Статус к номиналу",
        "flags",
        "Полная стоимость",
    ],
}

POSITIONS_WARNING_FILTER_OPTIONS = (
    "all",
    "with_warnings",
    "without_warnings",
)
POSITIONS_DATA_QUALITY_FILTER_OPTIONS = (
    "all",
    "with_issues",
    "without_issues",
)
BOND_ASSET_TYPES_FOR_FLAGS = ("bond_corp", "bond_ofz_pd", "bond_ofz_in")


def _to_float(value) -> float | None:
    if value in (None, ""):
        return None
    if pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_positions_table_columns(view_mode: str, available_columns: Iterable[str]) -> list[str]:
    """Подобрать колонки для выбранного режима, безопасно пропуская отсутствующие."""
    available = list(available_columns)
    mode = view_mode if view_mode in POSITIONS_TABLE_COLUMNS_BY_MODE else "Все колонки"
    preferred = POSITIONS_TABLE_COLUMNS_BY_MODE[mode]
    columns = [column for column in preferred if column in available]
    return columns if columns else available


def apply_positions_advanced_filters(
    filtered: pd.DataFrame,
    issuer_filter: Iterable[str] | None = None,
    ytm_range: tuple[float, float] | None = None,
    position_share_range: tuple[float, float] | None = None,
    years_to_maturity_range: tuple[float, float] | None = None,
    warning_filter: str = "all",
    data_quality_filter: str = "all",
    premium_filter: str = "all",
    data_quality_isins: set[str] | None = None,
    warning_share_threshold: float = 0.10,
) -> pd.DataFrame:
    """Применить расширенные фильтры позиций (совместно и безопасно)."""
    result = filtered.copy()
    issuers = [issuer for issuer in (issuer_filter or []) if issuer]

    if premium_filter != "all":
        result = result[result["premium_discount_status"] == premium_filter]

    if issuers:
        result = result[result["issuer"].isin(issuers)]

    if ytm_range is not None:
        ytm_min, ytm_max = ytm_range
        result = result[result["ytm"].notna() & result["ytm"].between(ytm_min, ytm_max, inclusive="both")]

    if position_share_range is not None:
        pos_min, pos_max = position_share_range
        result = result[
            result["position_share"].notna()
            & result["position_share"].between(pos_min, pos_max, inclusive="both")
        ]

    if years_to_maturity_range is not None:
        years_min, years_max = years_to_maturity_range
        result = result[
            result["years_to_maturity"].notna()
            & result["years_to_maturity"].between(years_min, years_max, inclusive="both")
        ]

    if warning_filter in POSITIONS_WARNING_FILTER_OPTIONS and warning_filter != "all":
        warning_mask = (
            (result["position_share"].fillna(0) > warning_share_threshold)
            | (result["issuer_share"].fillna(0) > warning_share_threshold)
        )
        if warning_filter == "with_warnings":
            result = result[warning_mask]
        elif warning_filter == "without_warnings":
            result = result[~warning_mask]

    issue_isins = {isin for isin in (data_quality_isins or set()) if isinstance(isin, str) and isin and isin != "—"}
    if data_quality_filter in POSITIONS_DATA_QUALITY_FILTER_OPTIONS and data_quality_filter != "all":
        quality_mask = result["isin"].where(result["isin"].notna(), "").isin(issue_isins)
        if data_quality_filter == "with_issues":
            result = result[quality_mask]
        elif data_quality_filter == "without_issues":
            result = result[~quality_mask]

    return result


def build_position_flags(
    row: Mapping[str, object],
    position_threshold: float = 0.10,
    issuer_threshold: float = 0.10,
    near_maturity_days_threshold: int = 90,
    bond_asset_types: tuple[str, ...] = BOND_ASSET_TYPES_FOR_FLAGS,
) -> list[str]:
    """Сформировать flags позиции для риск/качество-индикаторов."""
    flags: list[str] = []

    position_share = _to_float(row.get("position_share"))
    if position_share is not None and position_share > position_threshold:
        flags.append(">10% позиции")

    issuer_share = _to_float(row.get("issuer_share"))
    if issuer_share is not None and issuer_share > issuer_threshold:
        flags.append(">10% эмитент")

    asset_type = row.get("asset_type")
    is_bond = asset_type in bond_asset_types
    ytm = _to_float(row.get("ytm"))
    if is_bond and ytm is None:
        flags.append("нет YTM")

    days_to_maturity = _to_float(row.get("days_to_maturity"))
    if is_bond and days_to_maturity is None:
        flags.append("нет погашения")
    elif is_bond and days_to_maturity <= near_maturity_days_threshold:
        flags.append("скоро погашение")

    premium_discount_status = str(row.get("premium_discount_status") or "")
    if is_bond and premium_discount_status == "premium":
        flags.append("premium")
    elif is_bond and premium_discount_status == "discount":
        flags.append("discount")

    avg_price = _to_float(row.get("avg_price"))
    if avg_price is None:
        flags.append("нет cost basis")

    return flags


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
    rating_by_isin: Mapping[str, str | None] | None = None,
    maturity_by_isin: Mapping[str, str | None] | None = None,
    as_of_date: date | None = None,
) -> pd.DataFrame:
    """Фильтрация, обогащение и сортировка позиций для UI."""
    maturity_by_isin = maturity_by_isin or {}
    rating_by_isin = rating_by_isin or {}
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

    filtered["rating"] = filtered["isin"].map(rating_by_isin).astype("object")
    filtered.loc[~bond_mask, "rating"] = "—"

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
    filtered["flags"] = filtered.apply(
        lambda row: ", ".join(build_position_flags(row, bond_asset_types=bond_asset_types)),
        axis=1,
    )

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
        "name", "asset_type", "rating", "issuer", "qty", "avg_price", "price_end", "ytm",
        "days_to_maturity", "years_to_maturity",
        "price_to_nominal_pct", "premium_discount_status",
        "position_share", "issuer_share", "flags",
        "value_end", "nkd_end", "change_value", "pnl", "pnl_pct"
    ]].copy()

    display_df["Тип"] = display_df["asset_type"].map(type_labels)
    display_df["Полная стоимость"] = display_df.apply(
        lambda row: calculate_total_position_value(row["value_end"], row["nkd_end"]),
        axis=1,
    )

    display_df = display_df.rename(columns={
        "name": "Инструмент",
        "rating": "Рейтинг",
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
        "flags": "flags",
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
    display_df["Рейтинг"] = display_df["Рейтинг"].apply(
        lambda v: None if v is None or str(v).strip() == "" else v
    ).fillna("без рейтинга")
    display_df["Эмитент"] = display_df["Эмитент"].fillna("—")
    display_df["flags"] = display_df["flags"].fillna("")
    return display_df


def prepare_positions_export_table(
    filtered: pd.DataFrame,
    type_labels: Mapping[str, str],
) -> pd.DataFrame:
    """Подготовить CSV-таблицу позиций для экспорта текущей выборки."""
    export_df = filtered[[
        "name", "isin", "asset_type", "rating", "issuer", "ytm",
        "position_share", "issuer_share", "years_to_maturity",
        "premium_discount_status", "flags", "pnl", "pnl_pct", "value_end", "nkd_end",
    ]].copy()

    export_df["type_label"] = export_df["asset_type"].map(type_labels)
    export_df["total_value"] = export_df.apply(
        lambda row: calculate_total_position_value(row["value_end"], row["nkd_end"]),
        axis=1,
    )
    export_df["position_share_pct"] = export_df["position_share"].apply(
        lambda v: (v * 100.0) if pd.notna(v) else None
    )
    export_df["issuer_share_pct"] = export_df["issuer_share"].apply(
        lambda v: (v * 100.0) if pd.notna(v) else None
    )

    export_df = export_df.rename(
        columns={
            "name": "Инструмент",
            "isin": "ISIN",
            "type_label": "Тип",
            "rating": "Рейтинг",
            "issuer": "Эмитент",
            "ytm": "YTM %",
            "position_share_pct": "Доля позиции %",
            "issuer_share_pct": "Доля эмитента %",
            "years_to_maturity": "Срок до погашения, лет",
            "premium_discount_status": "Статус к номиналу",
            "flags": "flags",
            "pnl": "P&L ₽",
            "pnl_pct": "P&L %",
            "total_value": "Полная стоимость ₽",
        }
    )

    export_df["Рейтинг"] = export_df["Рейтинг"].apply(
        lambda v: None if v is None or str(v).strip() == "" else v
    ).fillna("без рейтинга")
    export_df["Эмитент"] = export_df["Эмитент"].fillna("—")
    export_df["flags"] = export_df["flags"].fillna("")
    export_df["Статус к номиналу"] = export_df["Статус к номиналу"].fillna("нет данных")

    return export_df[[
        "Инструмент",
        "ISIN",
        "Тип",
        "Рейтинг",
        "Эмитент",
        "YTM %",
        "Доля позиции %",
        "Доля эмитента %",
        "Срок до погашения, лет",
        "Статус к номиналу",
        "flags",
        "P&L ₽",
        "P&L %",
        "Полная стоимость ₽",
    ]]
