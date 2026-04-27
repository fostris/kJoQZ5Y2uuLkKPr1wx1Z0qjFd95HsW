"""Plotly chart helpers for Streamlit UI."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def _normalize_chart_source(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare source DataFrame with mandatory columns for YTM chart."""
    source = df.copy() if df is not None else pd.DataFrame()

    defaults = {
        "name": "—",
        "isin": "—",
        "asset_type": "—",
        "issuer": "—",
        "ytm": None,
        "years_to_maturity": None,
        "position_share": None,
    }
    for column, default_value in defaults.items():
        if column not in source.columns:
            source[column] = default_value

    source["ytm"] = pd.to_numeric(source["ytm"], errors="coerce")
    source["years_to_maturity"] = pd.to_numeric(source["years_to_maturity"], errors="coerce")
    source["position_share"] = pd.to_numeric(source["position_share"], errors="coerce")
    source["name"] = source["name"].fillna("—").astype(str)
    source["isin"] = source["isin"].fillna("—").astype(str)
    source["asset_type"] = source["asset_type"].fillna("—").astype(str)

    return source


def _build_excluded_rows(excluded_df: pd.DataFrame) -> list[dict[str, str]]:
    """Build human-readable list of rows excluded from YTM chart."""
    excluded_rows: list[dict[str, str]] = []
    for _, row in excluded_df.iterrows():
        reasons: list[str] = []
        if pd.isna(row.get("ytm")):
            reasons.append("нет YTM")
        if pd.isna(row.get("years_to_maturity")):
            reasons.append("нет срока до погашения")
        excluded_rows.append(
            {
                "name": str(row.get("name") or "—"),
                "isin": str(row.get("isin") or "—"),
                "reason": ", ".join(reasons) if reasons else "неполные данные",
            }
        )
    return excluded_rows


def plot_ytm_vs_maturity(df: pd.DataFrame) -> dict[str, Any]:
    """Scatter chart: X=maturity years, Y=YTM, size=position share, color=asset type."""
    source = _normalize_chart_source(df)
    if source.empty:
        return {
            "figure": None,
            "included_count": 0,
            "excluded_positions": [],
        }

    valid_mask = source["ytm"].notna() & source["years_to_maturity"].notna()
    included = source[valid_mask].copy()
    excluded = source[~valid_mask].copy()

    excluded_positions = _build_excluded_rows(excluded)

    if included.empty:
        return {
            "figure": None,
            "included_count": 0,
            "excluded_positions": excluded_positions,
        }

    included["position_share_pct"] = included["position_share"].fillna(0.0) * 100.0
    max_share = included["position_share_pct"].max()
    included["marker_size"] = included["position_share_pct"] if max_share > 0 else 1.0

    fig = px.scatter(
        included,
        x="years_to_maturity",
        y="ytm",
        size="marker_size",
        color="asset_type",
        hover_name="name",
        hover_data={
            "isin": True,
            "ytm": ":.2f",
            "years_to_maturity": ":.2f",
            "position_share_pct": ":.2f",
            "asset_type": True,
            "marker_size": False,
        },
        labels={
            "years_to_maturity": "Срок до погашения, лет",
            "ytm": "YTM, %",
            "asset_type": "Тип актива",
            "isin": "ISIN",
            "position_share_pct": "Доля позиции, %",
        },
        title=None,
    )
    fig.update_traces(marker=dict(sizemode="area", sizemin=8, opacity=0.75))
    fig.update_layout(
        xaxis_title="Срок до погашения, лет",
        yaxis_title="YTM, %",
        legend_title_text="Тип актива",
        margin=dict(t=20, b=20),
        hovermode="closest",
    )

    return {
        "figure": fig,
        "included_count": int(len(included)),
        "excluded_positions": excluded_positions,
    }


def plot_coupon_cashflow_by_month(cashflow_df: pd.DataFrame) -> dict[str, Any]:
    """Bar chart for coupon cashflow over months with chronological sorting."""
    source = cashflow_df.copy() if cashflow_df is not None else pd.DataFrame()
    if source.empty:
        return {"figure": None, "dataframe": source}

    if "month" not in source.columns:
        source["month"] = None
    if "income" not in source.columns:
        source["income"] = 0.0
    if "payments_count" not in source.columns:
        source["payments_count"] = 0
    if "month_label" not in source.columns:
        source["month_label"] = None

    source["income"] = pd.to_numeric(source["income"], errors="coerce").fillna(0.0)
    source["payments_count"] = pd.to_numeric(source["payments_count"], errors="coerce").fillna(0).astype(int)

    source["month_date"] = pd.to_datetime(source["month"], format="%Y-%m", errors="coerce")
    month_label_date = pd.to_datetime(source["month_label"], format="%m.%Y", errors="coerce")
    source["month_date"] = source["month_date"].where(source["month_date"].notna(), month_label_date)

    source = source[source["month_date"].notna()].sort_values("month_date").copy()
    if source.empty:
        return {"figure": None, "dataframe": source}

    source["month_label"] = source["month_date"].dt.strftime("%m.%Y")

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=source["month_label"],
            y=source["income"],
            text=source["income"].apply(lambda v: f"{v:,.0f} ₽"),
            textposition="outside",
            marker_color="#22d3ee",
            hovertemplate="<b>%{x}</b><br>Доход: %{y:,.2f} ₽<br>Выплат: %{customdata}<extra></extra>",
            customdata=source["payments_count"],
        )
    )
    fig.update_layout(
        xaxis_title="",
        yaxis_title="₽",
        height=300,
        margin=dict(t=20, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return {"figure": fig, "dataframe": source}


def plot_maturity_ladder(ladder_df: pd.DataFrame) -> dict[str, Any]:
    """Stacked bar chart for yearly maturity/amortization ladder."""
    source = ladder_df.copy() if ladder_df is not None else pd.DataFrame()
    if source.empty:
        return {"figure": None, "dataframe": source}

    defaults = {
        "year": None,
        "maturity_return": 0.0,
        "amortization_return": 0.0,
        "total_return": 0.0,
    }
    for column, default_value in defaults.items():
        if column not in source.columns:
            source[column] = default_value

    source["year"] = pd.to_numeric(source["year"], errors="coerce")
    source["maturity_return"] = pd.to_numeric(source["maturity_return"], errors="coerce").fillna(0.0)
    source["amortization_return"] = pd.to_numeric(source["amortization_return"], errors="coerce").fillna(0.0)
    source["total_return"] = pd.to_numeric(source["total_return"], errors="coerce").fillna(
        source["maturity_return"] + source["amortization_return"]
    )

    source = source[source["year"].notna()].sort_values("year").copy()
    if source.empty:
        return {"figure": None, "dataframe": source}

    source["year"] = source["year"].astype(int)
    source["year_str"] = source["year"].astype(str)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=source["year_str"],
            y=source["maturity_return"],
            name="Погашения",
            marker_color="#a78bfa",
        )
    )
    fig.add_trace(
        go.Bar(
            x=source["year_str"],
            y=source["amortization_return"],
            name="Амортизации",
            marker_color="#22d3ee",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=source["year_str"],
            y=source["total_return"],
            name="Итого возврат",
            mode="lines+markers+text",
            line=dict(color="#f59e0b", width=2),
            text=source["total_return"].apply(lambda v: f"{v:,.0f} ₽"),
            textposition="top center",
        )
    )
    fig.update_layout(
        barmode="stack",
        xaxis_title="Год",
        yaxis_title="₽",
        height=340,
        margin=dict(t=20, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.1),
    )

    return {"figure": fig, "dataframe": source}
