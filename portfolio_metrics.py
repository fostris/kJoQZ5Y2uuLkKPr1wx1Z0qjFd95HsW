"""Портфельные расчеты без привязки к Streamlit/БД/API."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
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


def _row_get(row, key: str, default=None):
    if row is None:
        return default
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return default


def _sum_deposits_amount(deposits_rows: Iterable[Mapping] | None) -> float:
    total = 0.0
    for row in (deposits_rows or []):
        amount = _to_float(_row_get(row, "amount", 0))
        if amount is not None:
            total += amount
    return float(total)


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
            "total_deposited_all": _sum_deposits_amount(deposits_rows),
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

    total_deposited_all = _sum_deposits_amount(deposits_rows)
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


def _parse_date_value(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()

    text = str(value).strip()
    if not text:
        return None

    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_flow_rows(
    rows: Iterable[Mapping] | None,
    *,
    sign: float,
) -> list[dict]:
    normalized: list[dict] = []
    for row in (rows or []):
        flow_date = _parse_date_value(_row_get(row, "date"))
        amount = _to_float(_row_get(row, "amount", 0))
        if flow_date is None or amount is None or amount == 0:
            continue
        normalized.append(
            {
                "date": flow_date,
                "amount": abs(float(amount)) * sign,
            }
        )
    normalized.sort(key=lambda item: item["date"])
    return normalized


def _build_snapshot_rows(
    historical_snapshots: list[dict],
    current_report_id: int,
    current_value: float,
    current_date: date,
) -> list[dict]:
    snapshots: list[dict] = []
    has_current_snapshot = False

    for row in historical_snapshots or []:
        snap_date = _parse_date_value(_row_get(row, "period_end") or _row_get(row, "date"))
        snap_value = _to_float(_row_get(row, "total_value", _row_get(row, "total_end")))
        snap_report_id = _row_get(row, "report_id")
        if snap_date is None or snap_value is None:
            continue
        snap = {
            "report_id": int(snap_report_id) if snap_report_id not in (None, "") else None,
            "date": snap_date,
            "total_value": float(snap_value),
        }
        snapshots.append(snap)
        if snap["report_id"] == current_report_id:
            has_current_snapshot = True

    if not has_current_snapshot:
        snapshots.append(
            {
                "report_id": int(current_report_id),
                "date": current_date,
                "total_value": float(current_value),
            }
        )

    snapshots.sort(key=lambda item: (item["date"], item["report_id"] or -1))
    return snapshots


def _filter_flows_between(
    flows: list[dict],
    start_date: date,
    end_date: date,
) -> list[dict]:
    return [row for row in flows if start_date < row["date"] <= end_date]


def _modified_dietz_pct(
    *,
    start_value: float,
    end_value: float,
    start_date: date,
    end_date: date,
    cashflows: list[dict],
) -> float | None:
    if start_value == 0:
        return None
    if end_date <= start_date:
        return None

    total_flow = sum(float(row["amount"]) for row in cashflows)
    abs_change = end_value - start_value - total_flow

    if len(cashflows) == 1:
        denominator = start_value + total_flow
    else:
        duration_days = max((end_date - start_date).days, 1)
        weighted_flows = 0.0
        for row in cashflows:
            elapsed_days = (row["date"] - start_date).days
            remaining_weight = (duration_days - elapsed_days) / duration_days
            if remaining_weight < 0:
                remaining_weight = 0.0
            elif remaining_weight > 1:
                remaining_weight = 1.0
            weighted_flows += float(row["amount"]) * remaining_weight
        denominator = start_value + weighted_flows

    if denominator == 0:
        return None
    return abs_change / denominator * 100.0


def compute_period_returns(
    *,
    current_report_id: int,
    current_value: float,
    current_date: date,
    historical_snapshots: list[dict],
    deposits: list[dict],
    withdrawals: list[dict] | None = None,
) -> dict[str, dict | None]:
    """Доходность по периодам (day/week/month/3m/all) с нейтрализацией внешних потоков."""
    period_days = {
        "day": 1,
        "week": 7,
        "month": 30,
        "3m": 90,
    }
    normalized_current_date = _parse_date_value(current_date)
    if normalized_current_date is None:
        return {**{key: None for key in period_days}, "all": None}

    snapshots = _build_snapshot_rows(
        historical_snapshots=historical_snapshots,
        current_report_id=current_report_id,
        current_value=current_value,
        current_date=normalized_current_date,
    )
    snapshots = [row for row in snapshots if row["date"] <= normalized_current_date]
    if not snapshots:
        return {**{key: None for key in period_days}, "all": None}

    end_snapshot = None
    for row in snapshots:
        if row["report_id"] == current_report_id:
            end_snapshot = row
            break
    if end_snapshot is None:
        end_snapshot = max(snapshots, key=lambda item: item["date"])

    deposits_flows = _normalize_flow_rows(deposits, sign=1.0)
    withdrawals_flows = _normalize_flow_rows(withdrawals, sign=-1.0)
    all_flows = sorted(deposits_flows + withdrawals_flows, key=lambda item: item["date"])

    result: dict[str, dict | None] = {}
    for key, days in period_days.items():
        target_start_date = end_snapshot["date"] - timedelta(days=days)
        start_candidates = [
            row for row in snapshots
            if row["date"] <= target_start_date and row["date"] < end_snapshot["date"]
        ]
        if not start_candidates:
            result[key] = None
            continue
        start_snapshot = max(start_candidates, key=lambda item: item["date"])
        start_value = float(start_snapshot["total_value"])
        end_value = float(end_snapshot["total_value"])

        period_flows = _filter_flows_between(all_flows, start_snapshot["date"], end_snapshot["date"])
        total_flow = sum(row["amount"] for row in period_flows)
        abs_change = end_value - start_value - total_flow
        twr_pct = _modified_dietz_pct(
            start_value=start_value,
            end_value=end_value,
            start_date=start_snapshot["date"],
            end_date=end_snapshot["date"],
            cashflows=period_flows,
        )

        result[key] = {
            "abs_change": abs_change,
            "twr_pct": twr_pct,
            "start_date": start_snapshot["date"],
            "start_value": start_value,
            "end_date": end_snapshot["date"],
            "end_value": end_value,
            "net_flow": total_flow,
        }

    deposits_total = sum(row["amount"] for row in deposits_flows if row["date"] <= end_snapshot["date"])
    withdrawals_total = -sum(row["amount"] for row in withdrawals_flows if row["date"] <= end_snapshot["date"])
    net_contributions = deposits_total - withdrawals_total
    abs_pnl = float(end_snapshot["total_value"]) - net_contributions

    chain_snapshots = [row for row in snapshots if row["date"] <= end_snapshot["date"]]
    twr_all_pct: float | None = None
    if len(chain_snapshots) >= 2:
        twr_factor = 1.0
        twr_defined = True
        for idx in range(1, len(chain_snapshots)):
            start_row = chain_snapshots[idx - 1]
            end_row = chain_snapshots[idx]
            segment_flows = _filter_flows_between(all_flows, start_row["date"], end_row["date"])
            seg_pct = _modified_dietz_pct(
                start_value=float(start_row["total_value"]),
                end_value=float(end_row["total_value"]),
                start_date=start_row["date"],
                end_date=end_row["date"],
                cashflows=segment_flows,
            )
            if seg_pct is None:
                twr_defined = False
                break
            twr_factor *= (1.0 + seg_pct / 100.0)
        if twr_defined:
            twr_all_pct = (twr_factor - 1.0) * 100.0

    first_snapshot = chain_snapshots[0]
    result["all"] = {
        "abs_pnl": abs_pnl,
        "twr_pct": twr_all_pct,
        "start_date": first_snapshot["date"],
        "start_value": float(first_snapshot["total_value"]),
        "end_date": end_snapshot["date"],
        "end_value": float(end_snapshot["total_value"]),
        "net_contributions": net_contributions,
        "deposits_total": deposits_total,
        "withdrawals_total": withdrawals_total,
    }
    return result


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
