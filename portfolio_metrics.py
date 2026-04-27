"""Портфельные расчеты без привязки к Streamlit/БД/API."""

from __future__ import annotations

import math
from typing import Iterable, Mapping

import pandas as pd


DEFAULT_RETURN_PERIODS = {
    "За день": 1,
    "За неделю": 7,
    "За месяц": 30,
    "За 3 месяца": 90,
    "За полгода": 180,
    "За год": 365,
}


def _to_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(converted):
        return None
    return converted


def calculate_total_position_value(value_end, nkd_end) -> float | None:
    """Полная стоимость позиции: value_end + nkd_end."""
    value = _to_float(value_end)
    nkd = _to_float(nkd_end)
    if value is None:
        return None
    return value + (nkd or 0.0)


def calculate_total_nkd(pos_df: pd.DataFrame) -> float:
    """Суммарный НКД по позициям."""
    if pos_df.empty or "nkd_end" not in pos_df:
        return 0.0
    return float(pos_df["nkd_end"].sum())


def calculate_total_portfolio_value(positions_df: pd.DataFrame) -> float:
    """Суммарная стоимость портфеля на основе value_end + nkd_end."""
    if positions_df.empty:
        return 0.0
    value = positions_df["value_end"].fillna(0).sum() if "value_end" in positions_df else 0.0
    nkd = positions_df["nkd_end"].fillna(0).sum() if "nkd_end" in positions_df else 0.0
    return float(value + nkd)


def add_position_shares(
    positions_df: pd.DataFrame,
    value_column: str,
    share_column: str = "position_share",
) -> pd.DataFrame:
    """Добавить долю позиции от total по value_column в диапазоне 0..1."""
    out = positions_df.copy()
    if out.empty:
        out[share_column] = pd.Series(dtype="float64")
        return out

    if value_column not in out.columns:
        out[share_column] = 0.0
        return out

    base = pd.to_numeric(out[value_column], errors="coerce").fillna(0.0)
    total = float(base.sum())
    if total <= 0:
        out[share_column] = 0.0
        return out

    out[share_column] = base / total
    return out


def build_asset_type_aggregation(pos_df: pd.DataFrame, type_labels: Mapping[str, str]) -> pd.DataFrame:
    """Агрегация портфеля по типам активов."""
    if pos_df.empty:
        return pd.DataFrame(columns=["asset_type", "value", "nkd", "count", "total", "label"])

    type_agg = pos_df.groupby("asset_type").agg(
        value=("value_end", "sum"),
        nkd=("nkd_end", "sum"),
        count=("name", "count"),
    ).reset_index()
    type_agg["total"] = type_agg["value"] + type_agg["nkd"]
    type_agg["label"] = type_agg["asset_type"].map(type_labels)
    return type_agg.sort_values("total", ascending=False)


def _find_value_at(hist_df: pd.DataFrame, latest_date: pd.Timestamp, days_ago: int) -> float | None:
    target_date = latest_date - pd.Timedelta(days=days_ago)
    mask = hist_df[hist_df["period_end_dt"] <= target_date]
    if mask.empty:
        return None
    return float(mask.iloc[-1]["total_end"])


def _calc_return(val_then: float | None, val_now: float) -> float | None:
    if val_then and val_then > 0:
        return (val_now - val_then) / val_then * 100
    return None


def calculate_overview_returns(
    history_rows: Iterable[Mapping],
    deposits_rows: Iterable[Mapping] | None,
    periods: Mapping[str, int] | None = None,
) -> dict:
    """Доходность портфеля по стандартным периодам и за все время."""
    periods = periods or DEFAULT_RETURN_PERIODS
    history_rows = list(history_rows)

    if len(history_rows) <= 1:
        return {
            "returns_data": {},
            "latest_val": None,
            "total_deposited_all": float(sum(d.get("amount", 0) for d in (deposits_rows or []))),
            "net_profit": None,
            "net_pct": None,
        }

    hist_df = pd.DataFrame([dict(h) for h in history_rows])
    hist_df["period_end_dt"] = pd.to_datetime(hist_df["period_end"], format="%d.%m.%Y")
    hist_df = hist_df.sort_values("period_end_dt")

    latest_val = float(hist_df.iloc[-1]["total_end"])
    latest_date = hist_df.iloc[-1]["period_end_dt"]

    returns_data = {}
    for label, days in periods.items():
        val_then = _find_value_at(hist_df, latest_date, days)
        if val_then is not None:
            returns_data[label] = {
                "abs": latest_val - val_then,
                "pct": _calc_return(val_then, latest_val),
            }

    first_val = float(hist_df.iloc[0]["total_end"])
    first_date = hist_df.iloc[0]["period_end_dt"]
    days_total = int((latest_date - first_date).days)
    if first_val > 0 and days_total > 0:
        returns_data["За всё время"] = {
            "abs": latest_val - first_val,
            "pct": _calc_return(first_val, latest_val),
            "days": days_total,
        }

    total_deposited_all = float(sum(d.get("amount", 0) for d in (deposits_rows or [])))
    if total_deposited_all > 0:
        net_profit = latest_val - total_deposited_all
        net_pct = net_profit / total_deposited_all * 100
    else:
        net_profit = None
        net_pct = None

    return {
        "returns_data": returns_data,
        "latest_val": latest_val,
        "total_deposited_all": total_deposited_all,
        "net_profit": net_profit,
        "net_pct": net_pct,
    }


def add_pnl_columns(positions_df: pd.DataFrame, cost_map: Mapping[str, Mapping]) -> pd.DataFrame:
    """Добавить в DataFrame колонки avg_price/pnl/pnl_pct."""
    if positions_df.empty:
        out = positions_df.copy()
        out["avg_price"] = []
        out["pnl"] = []
        out["pnl_pct"] = []
        return out

    out = positions_df.copy()
    avg_prices = []
    pnl_values = []
    pnl_pcts = []

    for _, row in out.iterrows():
        cb = cost_map.get(row.get("isin"))
        if cb and cb.get("avg_price", 0) > 0:
            avg_p = float(cb["avg_price"])
            value_end = _to_float(row.get("value_end"))
            nkd_end = _to_float(row.get("nkd_end"))
            qty = _to_float(row.get("qty")) or 0.0
            current_val = float((value_end or 0.0) + (nkd_end or 0.0))
            cost_val = avg_p * qty
            pnl = current_val - cost_val
            pnl_pct = (pnl / cost_val * 100) if cost_val > 0 else 0.0
            avg_prices.append(avg_p)
            pnl_values.append(pnl)
            pnl_pcts.append(pnl_pct)
        else:
            avg_prices.append(None)
            pnl_values.append(None)
            pnl_pcts.append(None)

    out["avg_price"] = avg_prices
    out["pnl"] = pnl_values
    out["pnl_pct"] = pnl_pcts
    return out


def calculate_pnl_summary(filtered_df: pd.DataFrame, cost_map: Mapping[str, Mapping]) -> dict:
    """Сводные метрики P&L по уже подготовленному DataFrame."""
    if filtered_df.empty or "pnl" not in filtered_df:
        return {
            "has_pnl": False,
            "has_pnl_count": 0,
            "total_count": len(filtered_df),
            "total_pnl": 0.0,
            "total_cost": 0.0,
            "total_pnl_pct": 0.0,
            "winners": 0,
            "losers": 0,
        }

    has_pnl = filtered_df["pnl"].notna()
    if not has_pnl.any():
        return {
            "has_pnl": False,
            "has_pnl_count": 0,
            "total_count": len(filtered_df),
            "total_pnl": 0.0,
            "total_cost": 0.0,
            "total_pnl_pct": 0.0,
            "winners": 0,
            "losers": 0,
        }

    total_pnl = float(filtered_df.loc[has_pnl, "pnl"].sum())
    total_cost = float(sum(
        cost_map[row["isin"]]["avg_price"] * row["qty"]
        for _, row in filtered_df[has_pnl].iterrows()
        if row["isin"] in cost_map
    ))
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0
    winners = int((filtered_df.loc[has_pnl, "pnl"] > 0).sum())
    losers = int((filtered_df.loc[has_pnl, "pnl"] < 0).sum())

    return {
        "has_pnl": True,
        "has_pnl_count": int(has_pnl.sum()),
        "total_count": len(filtered_df),
        "total_pnl": total_pnl,
        "total_cost": total_cost,
        "total_pnl_pct": total_pnl_pct,
        "winners": winners,
        "losers": losers,
    }


def calculate_trades_stats(trades_df: pd.DataFrame) -> dict:
    """Сводка по сделкам."""
    if trades_df.empty:
        return {"count": 0, "total_amount": 0.0, "total_fees": 0.0}
    total_amount = float(trades_df["amount"].sum())
    total_fees = float(trades_df["broker_fee"].sum() + trades_df["exchange_fee"].sum())
    return {"count": len(trades_df), "total_amount": total_amount, "total_fees": total_fees}
