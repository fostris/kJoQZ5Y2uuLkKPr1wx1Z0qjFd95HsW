"""
📊 Портфель ИИС-3 — Streamlit Dashboard
Запуск: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date
from pathlib import Path

from analytics.bonds import calculate_weighted_ytm, calculate_weighted_years_to_maturity
from analytics.cashflows import build_coupon_cashflow_by_month, build_maturity_ladder
from analytics.alerts import build_alerts, get_rule_label
from analytics.data_quality import build_bond_data_quality_report
from analytics.decision_scenarios import (
    REDUCE_FACTOR_LABELS,
    build_buy_candidates,
    build_reduce_candidates,
    get_exclusion_reason_label,
)
from analytics.fx_exposure import (
    ALLOWED_CURRENCIES,
    ALLOWED_EXPOSURE_TYPES,
    compute_fx_exposure,
)
from analytics.ratings import (
    RATING_BUCKETS,
    RATING_BUCKET_UNRATED,
    build_rating_distribution,
)
import concentration
import db
import moex_api
import parser as bp
from report_export import build_portfolio_summary_html
from report_selection import resolve_default_report_id, should_switch_to_new_report
from fire_metrics import build_fire_scenarios
from formatters import format_rub
from portfolio_metrics import (
    build_asset_type_aggregation,
    compute_period_returns,
    calculate_pnl_summary,
    calculate_total_nkd,
    calculate_total_portfolio_value,
    calculate_trades_stats,
)
from portfolio_tables import (
    POSITIONS_DATA_QUALITY_FILTER_OPTIONS,
    POSITIONS_TABLE_VIEW_MODES,
    POSITIONS_WARNING_FILTER_OPTIONS,
    apply_positions_advanced_filters,
    get_positions_table_columns,
    prepare_positions_export_table,
    prepare_positions_dataset,
    prepare_positions_display_table,
)
from rebalancing import (
    DEFAULT_TARGETS as REBALANCE_DEFAULT_TARGETS,
    build_current_allocation,
    build_rebalance_comparison,
    split_rebalance_gaps,
)
from ui.charts import plot_coupon_cashflow_by_month, plot_maturity_ladder, plot_ytm_vs_maturity

# ─── Инициализация ───
db.init_db()

# ─── Конфигурация страницы ───
st.set_page_config(
    page_title="Портфель ИИС-3",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Тёмная тема / стиль ───
st.markdown("""
<style>
    .stMetric .metric-container { background: #111827; border-radius: 12px; padding: 16px; }
    div[data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace; }
    .block-container { padding-top: 2rem; }
    h1, h2, h3 { font-weight: 700 !important; }
    .iis-reminder {
        background: linear-gradient(135deg, #064e3b 0%, #111827 100%);
        border: 1px solid #10b981;
        border-radius: 12px;
        padding: 20px;
        margin: 12px 0;
    }
</style>
""", unsafe_allow_html=True)

# ─── Константы FIRE / ИИС ───
IIS3_TAX_DEDUCTION_LIMIT = 400_000  # Максимум для вычета типа А за год
IIS3_TAX_REFUND_RATE = 0.13
CURRENT_YEAR = str(date.today().year)

TYPE_LABELS = {
    "bond_ofz_pd": "ОФЗ-ПД",
    "bond_ofz_in": "ОФЗ-ИН",
    "bond_corp": "Корп. облигации",
    "etf": "БПИФы / ETF",
    "stock": "Акции",
}

TYPE_COLORS = {
    "bond_ofz_pd": "#22d3ee",
    "bond_ofz_in": "#3b82f6",
    "bond_corp": "#a78bfa",
    "etf": "#f59e0b",
    "stock": "#10b981",
}

FX_RECOMMENDED_MIN_SHARE = 0.15
FX_RECOMMENDED_MAX_SHARE = 0.25
FX_EXPOSURE_LABELS = {
    "rub": "Рублёвая",
    "fx_substitute": "Замещайка",
    "fx_direct": "Прямая FX",
    "gold": "Золото",
    "commodity_proxy": "Commodity proxy",
}

BOND_ASSET_TYPES = concentration.BOND_ASSET_TYPES
PREMIUM_FILTER_OPTIONS = {
    "all": "Все",
    "premium": "Выше номинала",
    "discount": "Ниже номинала",
    "near par": "Около номинала",
}
ATTENTION_CONCENTRATION_THRESHOLD = 0.10
REBALANCE_TARGET_PRESETS = {
    "current_default": {
        "label": "Текущий дефолт",
        "targets": dict(REBALANCE_DEFAULT_TARGETS),
    },
    "macro_fire_rf": {
        "label": "Макро/FIRE РФ (ОФЗ-ИН 7%)",
        "targets": {
            "bond_ofz_pd": 13.0,
            "bond_ofz_in": 7.0,
            "bond_corp": 40.0,
            "etf": 10.0,
            "stock": 30.0,
        },
    },
}

try:
    from fire_metrics import SCENARIO_PRESETS as FIRE_SCENARIO_PRESETS
except ImportError:
    FIRE_SCENARIO_PRESETS = {
        "base": {"label": "Базовый", "inflation_rate": 0.07, "nominal_return_rate": 0.11, "weight": 0.55},
        "stagflation": {"label": "Стагфляционный", "inflation_rate": 0.10, "nominal_return_rate": 0.11, "weight": 0.20},
        "optimistic": {"label": "Оптимистичный", "inflation_rate": 0.04, "nominal_return_rate": 0.115, "weight": 0.10},
    }


def fmt(n: float) -> str:
    return format_rub(n)


def format_sync_freshness_caption(entity_label: str, freshness: dict) -> str:
    """Сформировать подпись о свежести данных синхронизации."""
    if not freshness or freshness.get("total", 0) == 0:
        return f"{entity_label}: синхронизация ещё не выполнялась."

    success_count = int(freshness.get("success_count") or 0)
    error_count = int(freshness.get("error_count") or 0)
    latest_success_at = freshness.get("latest_success_at")
    latest_error_at = freshness.get("latest_error_at")
    latest_error_message = freshness.get("latest_error_message")

    parts = []
    if latest_success_at:
        parts.append(f"последнее успешное обновление: {latest_success_at}")
    else:
        parts.append("успешных обновлений пока нет")
    parts.append(f"успехов: {success_count}, ошибок: {error_count}")
    if latest_error_at:
        error_text = str(latest_error_message or "без текста ошибки").strip()
        if len(error_text) > 120:
            error_text = error_text[:117] + "..."
        parts.append(f"последняя ошибка: {latest_error_at} ({error_text})")

    return f"{entity_label}: " + "; ".join(parts) + "."


@st.cache_data(ttl=300, show_spinner=False)
def load_bond_ytm_map(isins: tuple[str, ...]) -> dict[str, float | None]:
    """Получить YTM по ISIN с кешем Streamlit."""
    ytm_map: dict[str, float | None] = {}
    for isin in isins:
        if not isin:
            continue
        ytm_map[isin] = moex_api.get_bond_ytm_by_isin(isin)
    return ytm_map


@st.cache_data(ttl=1800, show_spinner=False)
def load_bond_issuer_map(isins: tuple[str, ...]) -> dict[str, str | None]:
    """Получить эмитента по ISIN с кешем Streamlit."""
    issuer_map: dict[str, str | None] = {}
    for isin in isins:
        if not isin:
            continue
        issuer_map[isin] = moex_api.get_issuer_by_isin(isin)
    return issuer_map


# ─── Сайдбар ───
with st.sidebar:
    st.title("📊 Портфель ИИС-3")
    st.caption("Дашборд брокерских отчётов Сбербанк")

    st.divider()

    # Загрузка нового отчёта
    st.subheader("📥 Импорт отчёта")
    uploaded = st.file_uploader(
        "Загрузить HTML-отчёт брокера",
        type=["html", "htm"],
        help="Перетащите файл отчёта или выберите из папки",
    )

    reports_before_import = db.get_all_reports()
    previous_max_period_end = reports_before_import[0]["period_end"] if reports_before_import else None

    if uploaded:
        # Сохраняем временно
        reports_dir = Path(__file__).parent / "reports"
        reports_dir.mkdir(exist_ok=True)
        tmp_path = reports_dir / uploaded.name
        tmp_path.write_bytes(uploaded.read())

        try:
            report = bp.parse_report(tmp_path)
            report_id = db.import_report(report)
            if report_id > 0:
                st.success(f"✅ Импортирован: {report.period_end}")
                st.metric("Портфель", f"{fmt(report.total_end)} ₽",
                          f"{report.total_change:+,.2f} ₽")
                if should_switch_to_new_report(report.period_end, previous_max_period_end):
                    st.session_state["selected_report_id"] = int(report_id)
                st.rerun()
            elif report_id == -1:
                st.info(f"ℹ️ Отчёт за {report.period_end} уже загружен")
        except Exception as e:
            st.error(f"Ошибка парсинга: {e}")

    st.divider()

    # Список отчётов
    all_reports = db.get_all_reports()
    if all_reports:
        st.subheader(f"📋 Отчёты ({len(all_reports)})")
        report_ids = [int(r["id"]) for r in all_reports]
        report_labels = {
            int(r["id"]): str(r["period_end"] or "")
            for r in all_reports
        }
        default_report_id = resolve_default_report_id([dict(r) for r in all_reports])

        if "selected_report_id" not in st.session_state:
            st.session_state["selected_report_id"] = default_report_id
        elif st.session_state["selected_report_id"] not in report_ids:
            st.session_state["selected_report_id"] = default_report_id

        st.selectbox(
            "Выберите дату отчёта",
            report_ids,
            format_func=lambda rid: report_labels.get(int(rid), f"ID {rid}"),
            key="selected_report_id",
        )
    else:
        st.warning("Загрузите первый HTML-отчёт брокера ↑")
        st.stop()


# ─── Загрузка данных ───
latest = db.get_latest_report()
if not latest:
    st.warning("Нет загруженных отчётов")
    st.stop()

# Находим выбранный отчёт
selected_report = None
selected_report_id = st.session_state.get("selected_report_id")
for r in all_reports:
    if int(r["id"]) == int(selected_report_id):
        selected_report = r
        break

if not selected_report:
    fallback_report_id = resolve_default_report_id([dict(r) for r in all_reports])
    if fallback_report_id is None:
        st.error("Отчёт не найден")
        st.stop()
    st.session_state["selected_report_id"] = int(fallback_report_id)
    selected_report = next((r for r in all_reports if int(r["id"]) == int(fallback_report_id)), None)
    if not selected_report:
        st.error("Отчёт не найден")
        st.stop()

report_id = selected_report["id"]
positions = db.get_positions(report_id)
cash_flows = db.get_cash_flows(report_id)
trades = db.get_trades(report_id)
all_deposits = db.get_all_deposits()
pos_list = [dict(p) for p in positions] if positions else []

# Преобразуем в DataFrame
pos_df = pd.DataFrame([dict(p) for p in positions]) if positions else pd.DataFrame()
dep_df = pd.DataFrame([dict(d) for d in all_deposits]) if all_deposits else pd.DataFrame()

if not pos_df.empty:
    bond_df = pos_df[pos_df["asset_type"].isin(BOND_ASSET_TYPES)]
    bond_isins = tuple(sorted({
        isin for isin in bond_df["isin"].dropna().tolist()
        if isinstance(isin, str) and isin
    }))
else:
    bond_isins = tuple()
ytm_by_isin = load_bond_ytm_map(bond_isins) if bond_isins else {}
issuer_by_isin = load_bond_issuer_map(bond_isins) if bond_isins else {}
issuer_reference_map = db.get_issuer_reference_map()
bond_ratings_map = db.get_bond_ratings_map()
rating_by_isin = {
    str(isin): (row.get("rating") if isinstance(row, dict) else None)
    for isin, row in bond_ratings_map.items()
}
maturities = db.get_bond_maturities()
coupon_calendar = db.get_coupon_calendar()
bond_amortizations = db.get_bond_amortizations()
cost_basis_all = db.get_cost_basis_map()
maturity_by_isin = {
    row["isin"]: row["maturity_date"]
    for row in maturities
    if row["isin"] in bond_isins
}
concentration_metrics = concentration.calculate_concentration_metrics(
    pos_list,
    issuer_by_isin=issuer_by_isin,
    issuer_reference_by_name=issuer_reference_map,
)
fx_override_rows = db.list_instrument_fx()
fx_overrides_map = {
    str(row["isin"]).upper(): {
        "currency": row["currency"],
        "exposure_type": row["exposure_type"],
        "note": row["note"],
    }
    for row in fx_override_rows
    if row["isin"]
}
fx_exposure_metrics = compute_fx_exposure(pos_list, fx_overrides_map)
ytm_metrics = calculate_weighted_ytm(
    positions=pos_list,
    ytm_by_isin=ytm_by_isin,
    bond_asset_types=BOND_ASSET_TYPES,
)
maturity_metrics = calculate_weighted_years_to_maturity(
    positions=pos_list,
    maturity_by_isin=maturity_by_isin,
    as_of_date=date.today(),
    bond_asset_types=BOND_ASSET_TYPES,
)
data_quality_report = build_bond_data_quality_report(
    positions=pos_list,
    ytm_map=ytm_by_isin,
    issuer_map=issuer_by_isin,
    maturities=[dict(row) for row in maturities],
    coupons=[dict(row) for row in coupon_calendar],
    cost_basis=cost_basis_all,
    amortizations=[dict(row) for row in bond_amortizations],
    bond_asset_types=BOND_ASSET_TYPES,
)
data_quality_issue_isins = {
    str(row.get("isin")).upper()
    for row in data_quality_report.get("bonds", [])
    if isinstance(row.get("isin"), str) and row.get("isin")
}
cashflow_12m_report = build_coupon_cashflow_by_month(
    coupons=[dict(row) for row in coupon_calendar],
    positions=pos_list,
    months=12,
    as_of_date=date.today(),
)
maturity_ladder_report = build_maturity_ladder(
    positions=pos_list,
    maturities=[dict(row) for row in maturities],
    amortizations=[dict(row) for row in bond_amortizations],
    as_of_date=date.today(),
)
rating_distribution = build_rating_distribution(
    positions=pos_list,
    rating_by_isin=rating_by_isin,
    bond_asset_types=BOND_ASSET_TYPES,
)

position_share_map = {}
for row in concentration_metrics["positions"]:
    key = row.get("isin") or row.get("name")
    if key:
        position_share_map[key] = row.get("position_share")

issuer_share_map = {
    row["issuer"]: row.get("issuer_share")
    for row in concentration_metrics["issuers"]
}
alerts_result = build_alerts(
    positions=pos_list,
    concentration_data={
        **concentration_metrics,
        "position_hhi_target": concentration.MAX_POSITION_HHI,
    },
    data_quality_data={
        "ytm_by_isin": ytm_by_isin,
        "maturity_by_isin": maturity_by_isin,
        "rating_by_isin": rating_by_isin,
        "cost_basis": cost_basis_all,
        "issuer_by_isin": {
            _isin: (issuer_by_isin.get(_isin) or name)
            for _isin, name in {
                str(row.get("isin") or "").strip().upper(): str(row.get("name") or "")
                for row in pos_list
                if str(row.get("isin") or "").strip()
            }.items()
        },
    },
    as_of_date=date.today(),
)


# ═══════════════════════════════════════════════
# ОСНОВНОЙ КОНТЕНТ
# ═══════════════════════════════════════════════

# ─── Заголовок ───
col_title, col_date = st.columns([3, 1])
with col_title:
    st.markdown(f"## Портфель · {selected_report['investor'] or 'ИИС-3'}")
    st.caption(f"Договор {selected_report['contract']} · Период {selected_report['period_start']} — {selected_report['period_end']}")
with col_date:
    st.markdown(f"### {selected_report['period_end']}")

st.divider()

# ═══════════════════════════════════════════════
# ВКЛАДКИ
# ═══════════════════════════════════════════════

tab_overview, tab_positions, tab_deposits, tab_calendar, tab_rebalance, tab_trades, tab_fire = st.tabs([
    "📊 Обзор", "📋 Позиции", "💰 Пополнения и вычет", "📅 Календарь", "⚖️ Ребалансировка", "🔄 Сделки", "🔥 FIRE"
])


# ─── TAB: ОБЗОР ───
with tab_overview:
    # KPI карточки
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            "Общая стоимость",
            f"{fmt(selected_report['total_end'])} ₽",
            f"{selected_report['total_change']:+,.2f} ₽",
        )
    with c2:
        st.metric("Ценные бумаги", f"{fmt(selected_report['securities_end'])} ₽")
    with c3:
        st.metric("Свободные ДС", f"{fmt(selected_report['cash_end'])} ₽")
    with c4:
        total_nkd = calculate_total_nkd(pos_df)
        st.metric("Накопленный НКД", f"{fmt(total_nkd)} ₽")

    st.divider()
    st.subheader("🏦 Доходность облигаций")

    weighted_ytm = ytm_metrics.get("weighted_ytm")
    ytm_coverage = ytm_metrics.get("coverage_pct")
    total_bond_value = ytm_metrics.get("total_bond_value") or 0.0
    covered_bond_value = ytm_metrics.get("covered_value") or 0.0
    missing_ytm_count = int(ytm_metrics.get("missing_count") or 0)
    missing_ytm_positions = ytm_metrics.get("missing_positions") or []
    weighted_years_to_maturity = maturity_metrics.get("weighted_years_to_maturity")
    maturity_coverage = maturity_metrics.get("coverage_pct")
    missing_maturity_count = int(maturity_metrics.get("missing_count") or 0)

    y1, y2, y3 = st.columns(3)
    with y1:
        st.metric(
            "Средневзвешенная YTM",
            f"{weighted_ytm:.2f}%" if weighted_ytm is not None else "нет данных",
        )
    with y2:
        st.metric(
            "Покрытие YTM",
            f"{ytm_coverage * 100:.1f}%" if ytm_coverage is not None else "нет данных",
        )
    with y3:
        st.metric(
            "Ср. срок до погашения",
            f"{weighted_years_to_maturity:.2f} лет" if weighted_years_to_maturity is not None else "нет данных",
        )

    if ytm_coverage is not None:
        st.caption(
            f"Покрытие по стоимости облигаций: {fmt(covered_bond_value)} ₽ из {fmt(total_bond_value)} ₽."
        )
        if ytm_coverage < 0.70:
            st.warning(
                f"Покрытие YTM ниже 70%: {ytm_coverage * 100:.1f}% облигационной части. "
                f"Без YTM позиций: {missing_ytm_count}."
            )
        elif missing_ytm_count == 0 and total_bond_value > 0:
            st.info("YTM есть по всем облигационным позициям.")
    else:
        st.caption("Для расчёта YTM: нет данных по облигациям.")
    st.caption(format_sync_freshness_caption("YTM (MOEX)", db.get_data_sync_freshness("ytm")))

    if missing_ytm_positions:
        missing_df = pd.DataFrame(missing_ytm_positions).copy()
        missing_df["portfolio_share"] = missing_df["portfolio_share"].apply(
            lambda v: v * 100 if v is not None else None
        )
        missing_df = missing_df.rename(
            columns={
                "name": "Инструмент",
                "isin": "ISIN",
                "portfolio_share": "Доля портфеля %",
                "market_value": "Полная стоимость",
            }
        )
        st.dataframe(
            missing_df[["Инструмент", "ISIN", "Доля портфеля %", "Полная стоимость"]],
            hide_index=True,
            use_container_width=True,
            column_config={
                "Доля портфеля %": st.column_config.NumberColumn(format="%.2f%%"),
                "Полная стоимость": st.column_config.NumberColumn(format="%.2f ₽"),
            },
        )
    if maturity_coverage is not None:
        st.caption(
            f"Покрытие срока погашения: {maturity_coverage * 100:.1f}% облигационной части; "
            f"без даты погашения позиций: {missing_maturity_count}."
        )
    else:
        st.caption("Для расчёта срока до погашения: нет данных.")

    st.divider()
    st.subheader("⭐ Рейтинги облигаций")

    rating_rows = rating_distribution.get("rows", [])
    rated_total = float(rating_distribution.get("total_bond_value") or 0.0)
    unrated_share = rating_distribution.get("unrated_share")

    if rated_total <= 0:
        st.info("Нет облигационных позиций для агрегата рейтингов.")
    else:
        rating_share_map = rating_distribution.get("share_map", {})
        bucket_cols = st.columns(len(RATING_BUCKETS))
        for idx, bucket in enumerate(RATING_BUCKETS):
            bucket_share = rating_share_map.get(bucket)
            with bucket_cols[idx]:
                st.metric(
                    bucket,
                    f"{bucket_share * 100:.1f}%" if bucket_share is not None else "0.0%",
                )

        rating_df = pd.DataFrame(rating_rows).rename(
            columns={
                "bucket": "Рейтинг",
                "market_value": "Рыночная стоимость",
                "share": "Доля облигационной части",
                "bonds_count": "Бумаг",
            }
        )
        rating_df["Доля облигационной части"] = rating_df["Доля облигационной части"].apply(
            lambda value: value * 100 if value is not None else None
        )
        st.dataframe(
            rating_df[["Рейтинг", "Рыночная стоимость", "Доля облигационной части", "Бумаг"]],
            hide_index=True,
            use_container_width=True,
            column_config={
                "Рыночная стоимость": st.column_config.NumberColumn(format="%.2f ₽"),
                "Доля облигационной части": st.column_config.NumberColumn(format="%.2f%%"),
                "Бумаг": st.column_config.NumberColumn(format="%d"),
            },
        )

        rating_chart_df = rating_df.copy()
        rating_fig = px.bar(
            rating_chart_df,
            x="Рейтинг",
            y="Доля облигационной части",
            text="Доля облигационной части",
            color="Рейтинг",
            labels={"Доля облигационной части": "Доля облигационной части, %"},
        )
        rating_fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        rating_fig.update_layout(
            showlegend=False,
            margin=dict(l=8, r=8, t=24, b=8),
            xaxis_title=None,
            yaxis_title="Доля облигационной части, %",
            yaxis=dict(rangemode="tozero"),
        )
        st.plotly_chart(rating_fig, use_container_width=True)

        if unrated_share is not None and unrated_share > 0:
            st.warning(
                f"Доля корзины «{RATING_BUCKET_UNRATED}»: {unrated_share * 100:.1f}% облигационной части."
            )
        else:
            st.info("Все облигационные позиции имеют заполненный рейтинг.")

    st.divider()
    st.subheader("🧪 Качество данных облигаций")

    quality_bond_count = data_quality_report.get("bond_count", 0)
    quality_score = data_quality_report.get("overall_score_pct")
    quality_severity = data_quality_report.get("overall_severity", "info")
    quality_problems = data_quality_report.get("problems", [])
    quality_bonds = data_quality_report.get("bonds", [])

    if quality_bond_count == 0:
        st.info("Нет данных по облигациям для оценки качества.")
    else:
        severity_label = {
            "critical": "критично",
            "high": "высокий риск",
            "warning": "предупреждение",
            "info": "инфо",
        }.get(quality_severity, "инфо")

        qc1, qc2, qc3, qc4 = st.columns(4)
        with qc1:
            st.metric(
                "Score качества",
                f"{quality_score:.1f}%" if quality_score is not None else "нет данных",
            )
        with qc2:
            st.metric("Проблемных бумаг", f"{data_quality_report.get('bonds_with_issues_count', 0)} из {quality_bond_count}")
        with qc3:
            st.metric("Проблемы данных", str(len(quality_problems)))
        with qc4:
            st.metric("Severity", severity_label)

        if quality_problems:
            top_problem = quality_problems[0]
            top_share = top_problem.get("missing_share")
            top_share_text = f"{top_share * 100:.1f}%" if top_share is not None else "нет данных"
            st.caption(
                f"Крупнейший пробел: {top_problem['title']} "
                f"(бумаг: {top_problem['missing_count']}, доля портфеля: {top_share_text})."
            )
        else:
            st.info("Критичных пробелов данных не обнаружено.")

        with st.expander("Показать детали качества данных"):
            if quality_problems:
                problems_df = pd.DataFrame(quality_problems).copy()
                problems_df["missing_share"] = problems_df["missing_share"].apply(
                    lambda v: v * 100 if v is not None else None
                )
                problems_df = problems_df.rename(
                    columns={
                        "title": "Проблема",
                        "missing_count": "Бумаг",
                        "missing_value": "Стоимость ₽",
                        "missing_share": "Доля портфеля %",
                        "severity": "Severity",
                    }
                )
                st.dataframe(
                    problems_df[["Проблема", "Severity", "Бумаг", "Стоимость ₽", "Доля портфеля %"]],
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Стоимость ₽": st.column_config.NumberColumn(format="%.2f ₽"),
                        "Доля портфеля %": st.column_config.NumberColumn(format="%.2f%%"),
                        "Бумаг": st.column_config.NumberColumn(format="%d"),
                    },
                )
            else:
                st.info("Проблемы данных не обнаружены.")

            if quality_bonds:
                bonds_df = pd.DataFrame(quality_bonds).copy()
                bonds_df["position_share"] = bonds_df["position_share"].apply(
                    lambda v: v * 100 if v is not None else None
                )
                bonds_df = bonds_df.rename(
                    columns={
                        "name": "Инструмент",
                        "isin": "ISIN",
                        "missing_fields_text": "Отсутствуют поля",
                        "missing_count": "Кол-во проблем",
                        "position_share": "Доля портфеля %",
                        "market_value": "Полная стоимость ₽",
                        "completeness_pct": "Заполненность %",
                    }
                )
                st.dataframe(
                    bonds_df[[
                        "Инструмент", "ISIN", "Отсутствуют поля", "Кол-во проблем",
                        "Доля портфеля %", "Полная стоимость ₽", "Заполненность %"
                    ]],
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Кол-во проблем": st.column_config.NumberColumn(format="%d"),
                        "Доля портфеля %": st.column_config.NumberColumn(format="%.2f%%"),
                        "Полная стоимость ₽": st.column_config.NumberColumn(format="%.2f ₽"),
                        "Заполненность %": st.column_config.NumberColumn(format="%.1f%%"),
                    },
                )
            else:
                st.info("Список бумаг с отсутствующими данными пуст.")

    st.divider()
    st.subheader("🚨 Алерты портфеля")

    alerts_summary = alerts_result.summary
    st.caption(
        "🚨 Риск: "
        f"{alerts_summary.get('risk_critical', 0)} критичных, "
        f"{alerts_summary.get('risk_warning', 0)} предупреждений.  \n"
        "📋 Данные: "
        f"{alerts_summary.get('data_total', 0)} пробелов "
        f"(critical: {alerts_summary.get('data_critical', 0)}, "
        f"warning: {alerts_summary.get('data_warning', 0)}, "
        f"info: {alerts_summary.get('data_info', 0)})."
    )

    def _severity_badge(severity: str) -> str:
        if severity == "critical":
            return "🔴 critical"
        if severity == "warning":
            return "🟡 warning"
        return "🔵 info"

    def _alerts_to_df(alerts_rows):
        if not alerts_rows:
            return pd.DataFrame(columns=["Severity", "Бумага", "ISIN", "Правило", "Детали"])
        rows = []
        for row in alerts_rows:
            rows.append(
                {
                    "Severity": _severity_badge(row.severity),
                    "Бумага": row.name or "—",
                    "ISIN": row.isin or "—",
                    "Правило": get_rule_label(row.rule_code),
                    "Детали": row.message,
                }
            )
        return pd.DataFrame(rows)

    risk_alerts = alerts_result.risk_alerts
    data_alerts = alerts_result.data_alerts

    with st.expander(f"🚨 Алерты риска ({len(risk_alerts)})", expanded=False):
        if risk_alerts:
            st.dataframe(
                _alerts_to_df(risk_alerts),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("Алертов риска не обнаружено.")

    with st.expander(f"📋 Алерты данных ({len(data_alerts)})", expanded=False):
        if data_alerts:
            st.dataframe(
                _alerts_to_df(data_alerts),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("Пробелов данных не обнаружено.")

    st.divider()

    # ─── Концентрация рисков ───
    st.subheader("⚠️ Концентрация рисков")

    largest_position_share = concentration_metrics.get("largest_position_share")
    largest_issuer_share = concentration_metrics.get("largest_issuer_share")
    corporate_bonds_share = concentration_metrics.get("corporate_bonds_share")
    position_hhi = concentration_metrics.get("position_hhi")
    issuer_hhi = concentration_metrics.get("issuer_hhi")

    rc1, rc2, rc3, rc4, rc5 = st.columns(5)
    with rc1:
        st.metric(
            "Крупнейшая позиция",
            f"{largest_position_share * 100:.1f}%" if largest_position_share is not None else "—",
            concentration_metrics.get("largest_position_name") or "—",
        )
    with rc2:
        st.metric(
            "Крупнейший эмитент",
            f"{largest_issuer_share * 100:.1f}%" if largest_issuer_share is not None else "—",
            concentration_metrics.get("largest_issuer_name") or "—",
        )
    with rc3:
        st.metric(
            "Корп. облигации",
            f"{corporate_bonds_share * 100:.1f}%" if corporate_bonds_share is not None else "—",
        )
    with rc4:
        st.metric("HHI позиции", f"{position_hhi:.3f}" if position_hhi is not None else "—")
    with rc5:
        st.metric("HHI эмитенты", f"{issuer_hhi:.3f}" if issuer_hhi is not None else "—")

    risk_warning_items = concentration_metrics.get("warning_items", [])
    risk_warnings = concentration_metrics.get("warnings", [])
    if risk_warning_items:
        for warning_item in risk_warning_items:
            severity = warning_item.get("severity", "warning")
            warning_text = str(warning_item.get("text") or "")
            if not warning_text:
                continue
            if severity == "critical":
                st.error(f"🛑 [critical] {warning_text}")
            elif severity == "high":
                st.warning(f"🔴 [high] {warning_text}")
            elif severity == "warning":
                st.warning(f"⚠️ [warning] {warning_text}")
            else:
                st.info(f"ℹ️ [info] {warning_text}")
    elif risk_warnings:
        for warning_text in risk_warnings:
            st.warning(f"⚠️ {warning_text}")
    else:
        st.success("Лимиты концентрации не превышены.")

    issuer_rows = concentration_metrics.get("issuers", [])
    if issuer_rows:
        issuer_df = pd.DataFrame(issuer_rows).copy()
        issuer_df = issuer_df.rename(
            columns={
                "issuer": "Эмитент",
                "market_value": "Рыночная стоимость",
                "issuer_share": "Доля портфеля",
                "issues_count": "Выпусков",
                "limit_breach": "Лимит",
            }
        )
        issuer_df["Доля портфеля"] = issuer_df["Доля портфеля"].apply(
            lambda v: v * 100 if v is not None else None
        )
        issuer_df["Лимит"] = issuer_df["Лимит"].map(lambda v: "⚠️ >10%" if v else "OK")
        st.dataframe(
            issuer_df[["Эмитент", "Рыночная стоимость", "Доля портфеля", "Выпусков", "Лимит"]],
            hide_index=True,
            use_container_width=True,
            column_config={
                "Рыночная стоимость": st.column_config.NumberColumn(format="%.2f ₽"),
                "Доля портфеля": st.column_config.NumberColumn(format="%.2f%%"),
                "Выпусков": st.column_config.NumberColumn(format="%d"),
            },
        )
    else:
        st.info("Недостаточно данных для группировки облигаций по эмитентам.")

    asset_type_rows = concentration_metrics.get("asset_types", [])
    if asset_type_rows:
        st.markdown("#### Распределение по типам активов")
        asset_type_df = pd.DataFrame(asset_type_rows).copy()
        asset_type_df["Тип актива"] = asset_type_df["asset_type"].map(TYPE_LABELS).fillna(asset_type_df["asset_type"])
        asset_type_df["Доля портфеля"] = asset_type_df["asset_type_share"].apply(
            lambda v: v * 100 if v is not None else None
        )
        st.dataframe(
            asset_type_df[["Тип актива", "market_value", "Доля портфеля", "positions_count"]].rename(
                columns={
                    "market_value": "Рыночная стоимость",
                    "positions_count": "Позиций",
                }
            ),
            hide_index=True,
            use_container_width=True,
            column_config={
                "Рыночная стоимость": st.column_config.NumberColumn(format="%.2f ₽"),
                "Доля портфеля": st.column_config.NumberColumn(format="%.2f%%"),
                "Позиций": st.column_config.NumberColumn(format="%d"),
            },
        )

    fallback_count = concentration_metrics.get("issuer_fallback_count", 0)
    if fallback_count:
        st.caption(
            f"Для {fallback_count} облигаций эмитент недоступен в API, использована временная fallback-группировка по названию выпуска."
        )
    st.caption(format_sync_freshness_caption("Эмитенты (MOEX)", db.get_data_sync_freshness("issuer")))

    sector_rows = concentration_metrics.get("sectors", [])
    issuer_group_rows = concentration_metrics.get("issuer_groups", [])
    sector_limit = concentration.MAX_SECTOR_SHARE
    issuer_group_limit = concentration.MAX_ISSUER_GROUP_SHARE

    sg_col1, sg_col2 = st.columns(2)
    with sg_col1:
        st.markdown("#### Концентрация по секторам")
        if sector_rows:
            sector_df = pd.DataFrame(sector_rows).rename(
                columns={
                    "sector": "Сектор",
                    "market_value": "Рыночная стоимость",
                    "dimension_share": "Доля портфеля",
                    "issuers_count": "Эмитентов",
                }
            )
            sector_df["Доля портфеля"] = sector_df["Доля портфеля"].apply(
                lambda v: v * 100 if v is not None else None
            )
            sector_df["Лимит"] = sector_df["Доля портфеля"].apply(
                lambda v: f"⚠️ >{sector_limit * 100:.0f}%"
                if v is not None and v > sector_limit * 100
                else "OK"
            )
            st.dataframe(
                sector_df[["Сектор", "Рыночная стоимость", "Доля портфеля", "Эмитентов", "Лимит"]],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Рыночная стоимость": st.column_config.NumberColumn(format="%.2f ₽"),
                    "Доля портфеля": st.column_config.NumberColumn(format="%.2f%%"),
                    "Эмитентов": st.column_config.NumberColumn(format="%d"),
                },
            )

            sector_chart_df = pd.DataFrame(sector_rows).sort_values(
                "dimension_share",
                ascending=False,
            )
            sector_chart_df["share_pct"] = sector_chart_df["dimension_share"].apply(
                lambda v: (v or 0.0) * 100
            )
            sector_fig = px.bar(
                sector_chart_df,
                x="sector",
                y="share_pct",
                text="share_pct",
                labels={
                    "sector": "Сектор",
                    "share_pct": "Доля портфеля, %",
                },
                color="sector",
            )
            sector_fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            sector_fig.update_layout(
                showlegend=False,
                margin=dict(l=8, r=8, t=24, b=8),
                xaxis_title=None,
                yaxis_title="Доля портфеля, %",
                yaxis=dict(rangemode="tozero"),
            )
            sector_fig.add_hline(
                y=sector_limit * 100,
                line_dash="dash",
                line_color="#ef4444",
                annotation_text=f"Лимит {sector_limit * 100:.0f}%",
                annotation_position="top left",
            )
            st.plotly_chart(sector_fig, use_container_width=True)

            breached_sectors = [
                row.get("sector")
                for row in sector_rows
                if (row.get("dimension_share") or 0.0) > sector_limit
            ]
            if breached_sectors:
                st.warning(
                    "Превышение секторного лимита: "
                    + ", ".join(str(name) for name in breached_sectors)
                    + "."
                )
        else:
            st.info("Нет данных для расчёта секторной концентрации.")

    with sg_col2:
        st.markdown("#### Концентрация по группам эмитентов")
        if issuer_group_rows:
            group_df = pd.DataFrame(issuer_group_rows).rename(
                columns={
                    "issuer_group": "Группа эмитентов",
                    "market_value": "Рыночная стоимость",
                    "dimension_share": "Доля портфеля",
                    "issuers_count": "Эмитентов",
                    "issuers": "Состав группы",
                }
            )
            group_df["Доля портфеля"] = group_df["Доля портфеля"].apply(
                lambda v: v * 100 if v is not None else None
            )
            group_df["Состав группы"] = group_df["Состав группы"].apply(
                lambda v: ", ".join(v) if isinstance(v, list) and v else "—"
            )
            group_df["Лимит"] = group_df["Доля портфеля"].apply(
                lambda v: f"⚠️ >{issuer_group_limit * 100:.0f}%"
                if v is not None and v > issuer_group_limit * 100
                else "OK"
            )
            st.dataframe(
                group_df[[
                    "Группа эмитентов",
                    "Рыночная стоимость",
                    "Доля портфеля",
                    "Эмитентов",
                    "Лимит",
                    "Состав группы",
                ]],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Рыночная стоимость": st.column_config.NumberColumn(format="%.2f ₽"),
                    "Доля портфеля": st.column_config.NumberColumn(format="%.2f%%"),
                    "Эмитентов": st.column_config.NumberColumn(format="%d"),
                },
            )
            breached_groups = [
                row.get("issuer_group")
                for row in issuer_group_rows
                if (row.get("dimension_share") or 0.0) > issuer_group_limit
            ]
            if breached_groups:
                st.warning(
                    "Превышение лимита по группам эмитентов: "
                    + ", ".join(str(name) for name in breached_groups)
                    + "."
                )
        else:
            st.info("Нет данных для расчёта концентрации по группам эмитентов.")

    st.divider()
    st.subheader("💱 Валютная экспозиция")
    st.caption(
        "FX-доля учитывает только `fx_substitute`, `fx_direct`, `gold`. "
        "`commodity_proxy` показывается отдельно и не входит в основной FX-порог."
    )

    fx_share = float(fx_exposure_metrics.get("fx_share") or 0.0)
    rub_share = float(fx_exposure_metrics.get("rub_share") or 0.0)
    fx_total_value = float(fx_exposure_metrics.get("total_value") or 0.0)
    fx_cols = st.columns(3)
    with fx_cols[0]:
        st.metric("FX-доля", f"{fx_share * 100:.1f}%")
    with fx_cols[1]:
        st.metric("Рублёвая доля", f"{rub_share * 100:.1f}%")
    with fx_cols[2]:
        st.metric("Объём позиций", f"{fmt(fx_total_value)} ₽")

    if fx_share < FX_RECOMMENDED_MIN_SHARE:
        st.warning("FX-доля ниже 15%: ниже минимальной диверсификации.")
    elif fx_share > FX_RECOMMENDED_MAX_SHARE:
        st.warning("FX-доля выше 25%: выше рекомендуемого диапазона.")
    else:
        st.success("FX-доля в рекомендуемом диапазоне 15–25%.")

    by_currency = fx_exposure_metrics.get("by_currency", {})
    by_exposure_type = fx_exposure_metrics.get("by_exposure_type", {})

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        if by_currency:
            cur_df = pd.DataFrame(
                [{"currency": key, "value": value} for key, value in by_currency.items()]
            ).sort_values("value", ascending=False)
            fig_cur = px.bar(
                cur_df,
                x="currency",
                y="value",
                text="value",
                labels={"currency": "Валюта", "value": "Стоимость, ₽"},
                color="currency",
            )
            fig_cur.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
            fig_cur.update_layout(showlegend=False, margin=dict(l=8, r=8, t=24, b=8))
            st.plotly_chart(fig_cur, use_container_width=True)
        else:
            st.info("Нет данных для распределения по валютам.")
    with chart_col2:
        if by_exposure_type:
            exp_df = pd.DataFrame(
                [{"exposure_type": key, "value": value} for key, value in by_exposure_type.items()]
            ).sort_values("value", ascending=False)
            exp_df["exposure_label"] = exp_df["exposure_type"].map(FX_EXPOSURE_LABELS).fillna(exp_df["exposure_type"])
            fig_exp = px.bar(
                exp_df,
                x="exposure_label",
                y="value",
                text="value",
                labels={"exposure_label": "Тип экспозиции", "value": "Стоимость, ₽"},
                color="exposure_label",
            )
            fig_exp.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
            fig_exp.update_layout(showlegend=False, margin=dict(l=8, r=8, t=24, b=8))
            st.plotly_chart(fig_exp, use_container_width=True)
        else:
            st.info("Нет данных для распределения по типам экспозиции.")

    fx_rows = fx_exposure_metrics.get("rows", [])
    if fx_rows:
        fx_rows_df = pd.DataFrame(fx_rows).copy()
        fx_rows_df["Тип экспозиции"] = fx_rows_df["exposure_type"].map(FX_EXPOSURE_LABELS).fillna(
            fx_rows_df["exposure_type"]
        )
        st.dataframe(
            fx_rows_df[["name", "isin", "value", "currency", "Тип экспозиции"]].rename(
                columns={
                    "name": "Инструмент",
                    "isin": "ISIN",
                    "value": "Стоимость, ₽",
                    "currency": "Валюта",
                }
            ),
            hide_index=True,
            use_container_width=True,
            column_config={"Стоимость, ₽": st.column_config.NumberColumn(format="%.2f ₽")},
        )

    with st.expander("⚙️ Настройка валютной экспозиции по ISIN"):
        portfolio_fx_rows = []
        for row in pos_list:
            isin = str(row.get("isin") or "").strip().upper()
            if not isin:
                continue
            fx_meta = fx_overrides_map.get(
                isin,
                {"currency": "RUB", "exposure_type": "rub", "note": ""},
            )
            portfolio_fx_rows.append(
                {
                    "isin": isin,
                    "name": str(row.get("name") or ""),
                    "currency": fx_meta.get("currency", "RUB"),
                    "exposure_type": fx_meta.get("exposure_type", "rub"),
                    "note": fx_meta.get("note", ""),
                }
            )

        if portfolio_fx_rows:
            fx_editor_df = (
                pd.DataFrame(portfolio_fx_rows)
                .drop_duplicates(subset=["isin"], keep="first")
                .sort_values(by=["name", "isin"])
                .reset_index(drop=True)
            )

            edited_fx_df = st.data_editor(
                fx_editor_df,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "isin": st.column_config.TextColumn("ISIN", disabled=True),
                    "name": st.column_config.TextColumn("Инструмент", disabled=True),
                    "currency": st.column_config.SelectboxColumn(
                        "Валюта",
                        options=sorted(ALLOWED_CURRENCIES),
                    ),
                    "exposure_type": st.column_config.SelectboxColumn(
                        "Тип экспозиции",
                        options=sorted(ALLOWED_EXPOSURE_TYPES),
                    ),
                    "note": st.column_config.TextColumn("Комментарий"),
                },
                key="fx_exposure_editor",
            )

            if st.button("💾 Сохранить FX-справочник", key="save_fx_overrides", type="primary"):
                for _, fx_row in edited_fx_df.iterrows():
                    isin = str(fx_row.get("isin") or "").strip().upper()
                    if not isin:
                        continue
                    db.set_instrument_fx(
                        isin=isin,
                        currency=str(fx_row.get("currency") or "RUB"),
                        exposure_type=str(fx_row.get("exposure_type") or "rub"),
                        note=str(fx_row.get("note") or ""),
                    )
                st.success("FX-справочник обновлён.")
                st.rerun()
        else:
            st.info("В портфеле нет позиций с ISIN для настройки FX-экспозиции.")

    st.markdown("#### 🗂 Справочник эмитентов")
    issuer_reference_rows = db.get_issuer_references()
    if issuer_reference_rows:
        ref_df = pd.DataFrame([dict(row) for row in issuer_reference_rows]).rename(
            columns={
                "issuer_name": "Эмитент",
                "issuer_group": "Группа",
                "sector": "Сектор",
                "issuer_type": "Тип эмитента",
                "comment": "Комментарий",
                "updated_at": "Обновлено",
            }
        )
        st.dataframe(
            ref_df[["Эмитент", "Группа", "Сектор", "Тип эмитента", "Комментарий", "Обновлено"]],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("Справочник эмитентов пока пуст.")

    with st.expander("➕ Добавить / обновить запись справочника"):
        existing_names = sorted({
            str(row["issuer_name"]) for row in issuer_reference_rows
            if row["issuer_name"]
        })
        suggested_names = sorted({
            str(row.get("issuer"))
            for row in issuer_rows
            if row.get("issuer")
        })
        selected_name = st.selectbox(
            "Выбрать существующего эмитента",
            options=[""] + existing_names,
            format_func=lambda v: "— новая запись —" if not v else v,
        )

        selected_reference = issuer_reference_map.get(selected_name) if selected_name else None
        issuer_name_input = st.text_input(
            "issuer_name",
            value=selected_name or "",
            placeholder="Точное имя эмитента",
        )
        issuer_group_input = st.text_input(
            "issuer_group",
            value=(selected_reference or {}).get("issuer_group") or "",
            placeholder="Например: ГК Система",
        )
        sector_input = st.text_input(
            "sector",
            value=(selected_reference or {}).get("sector") or "",
            placeholder="Например: Финансы",
        )
        issuer_type_input = st.text_input(
            "issuer_type",
            value=(selected_reference or {}).get("issuer_type") or "",
            placeholder="Например: Государственный / Корпоративный",
        )
        comment_input = st.text_area(
            "comment",
            value=(selected_reference or {}).get("comment") or "",
            placeholder="Заметка по эмитенту",
        )

        if suggested_names:
            st.caption("Подсказки из текущего портфеля: " + ", ".join(suggested_names[:12]))

        if st.button("💾 Сохранить запись эмитента"):
            if not issuer_name_input.strip():
                st.warning("Укажите issuer_name.")
            else:
                db.upsert_issuer_reference(
                    issuer_name=issuer_name_input,
                    issuer_group=issuer_group_input,
                    sector=sector_input,
                    issuer_type=issuer_type_input,
                    comment=comment_input,
                )
                st.success(f"✅ Справочник обновлён для «{issuer_name_input.strip()}».")
                st.rerun()

    if issuer_reference_rows:
        with st.expander("🗑 Удалить запись из справочника"):
            delete_target = st.selectbox(
                "Эмитент",
                options=sorted({str(row['issuer_name']) for row in issuer_reference_rows if row["issuer_name"]}),
            )
            if st.button("Удалить запись"):
                db.delete_issuer_reference(delete_target)
                st.success(f"✅ Запись «{delete_target}» удалена.")
                st.rerun()

    st.markdown("#### 🏷 Ручные рейтинги облигаций")
    bond_rating_rows = db.get_bond_ratings()
    if bond_rating_rows:
        ratings_df = pd.DataFrame([dict(row) for row in bond_rating_rows]).rename(
            columns={
                "isin": "ISIN",
                "issuer": "Эмитент",
                "rating": "Рейтинг",
                "rating_agency": "Агентство",
                "rating_date": "Дата рейтинга",
                "source_url": "Источник",
                "comment": "Комментарий",
                "updated_at": "Обновлено",
            }
        )
        st.dataframe(
            ratings_df[[
                "ISIN",
                "Эмитент",
                "Рейтинг",
                "Агентство",
                "Дата рейтинга",
                "Источник",
                "Комментарий",
                "Обновлено",
            ]],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("Ручные рейтинги пока не заполнены.")

    with st.expander("➕ Добавить / обновить рейтинг облигации"):
        existing_isins = sorted({
            str(row["isin"])
            for row in bond_rating_rows
            if row["isin"]
        })
        suggested_isins = sorted({
            str(row.get("isin"))
            for row in pos_list
            if row.get("asset_type") in BOND_ASSET_TYPES and row.get("isin")
        })
        selected_isin = st.selectbox(
            "Выбрать существующий ISIN",
            options=[""] + existing_isins,
            format_func=lambda value: "— новая запись —" if not value else value,
        )

        selected_rating = bond_ratings_map.get(selected_isin) if selected_isin else None
        rating_isin_input = st.text_input(
            "rating_isin",
            value=selected_isin or "",
            placeholder="RU000A10C5L7",
        )
        rating_issuer_input = st.text_input(
            "rating_issuer",
            value=(selected_rating or {}).get("issuer") or "",
            placeholder="Название эмитента",
        )
        rating_value_input = st.text_input(
            "rating",
            value=(selected_rating or {}).get("rating") or "",
            placeholder="Например: AA(RU) / A+ / BBB",
        )
        rating_agency_input = st.text_input(
            "rating_agency",
            value=(selected_rating or {}).get("rating_agency") or "",
            placeholder="Например: АКРА / Эксперт РА",
        )
        rating_date_input = st.text_input(
            "rating_date",
            value=(selected_rating or {}).get("rating_date") or "",
            placeholder="YYYY-MM-DD",
        )
        rating_source_input = st.text_input(
            "source_url",
            value=(selected_rating or {}).get("source_url") or "",
            placeholder="https://...",
        )
        rating_comment_input = st.text_area(
            "rating_comment",
            value=(selected_rating or {}).get("comment") or "",
            placeholder="Комментарий к источнику или статусу рейтинга",
        )

        if suggested_isins:
            st.caption("Подсказки ISIN из портфеля: " + ", ".join(suggested_isins[:15]))

        if st.button("💾 Сохранить рейтинг"):
            if not rating_isin_input.strip():
                st.warning("Укажите ISIN.")
            elif not rating_value_input.strip():
                st.warning("Укажите рейтинг.")
            else:
                db.upsert_bond_rating(
                    isin=rating_isin_input,
                    issuer=rating_issuer_input,
                    rating=rating_value_input,
                    rating_agency=rating_agency_input,
                    rating_date=rating_date_input,
                    source_url=rating_source_input,
                    comment=rating_comment_input,
                )
                st.success(f"✅ Рейтинг сохранён для «{rating_isin_input.strip().upper()}».")
                st.rerun()

    if bond_rating_rows:
        with st.expander("🗑 Удалить рейтинг"):
            delete_rating_isin = st.selectbox(
                "ISIN для удаления",
                options=sorted({str(row["isin"]) for row in bond_rating_rows if row["isin"]}),
            )
            if st.button("Удалить рейтинг"):
                db.delete_bond_rating(delete_rating_isin)
                st.success(f"✅ Рейтинг для «{delete_rating_isin}» удалён.")
                st.rerun()

    st.divider()
    st.subheader("📄 Экспорт краткого HTML-отчёта")

    top_positions_for_report = sorted(
        [
            {
                "name": row.get("name"),
                "isin": row.get("isin"),
                "position_share": row.get("position_share"),
                "market_value": row.get("market_value"),
            }
            for row in concentration_metrics.get("positions", [])
            if row.get("position_share") is not None
        ],
        key=lambda item: float(item.get("position_share") or 0.0),
        reverse=True,
    )
    report_html = build_portfolio_summary_html(
        report_date=str(selected_report["period_end"] or "нет данных"),
        portfolio_value=selected_report["total_end"],
        bond_value=ytm_metrics.get("total_bond_value"),
        weighted_ytm=ytm_metrics.get("weighted_ytm"),
        ytm_coverage_pct=ytm_metrics.get("coverage_pct"),
        largest_positions=top_positions_for_report,
        largest_issuers=concentration_metrics.get("issuers", []),
        warnings=concentration_metrics.get("warning_items", []),
        coupon_cashflow_12m=cashflow_12m_report,
        maturity_ladder=maturity_ladder_report,
    )
    report_date_label = str(selected_report["period_end"] or "report").replace(".", "-")
    st.download_button(
        "Скачать краткий HTML-отчёт",
        data=report_html.encode("utf-8"),
        file_name=f"portfolio_summary_{report_date_label}.html",
        mime="text/html",
        use_container_width=False,
    )
    st.caption("Отчёт включает ключевые метрики, крупнейшие позиции/эмитентов, предупреждения, купонный поток и лестницу погашений.")

    st.divider()

    # ─── Доходность портфеля ───
    report_date_dt = pd.to_datetime(selected_report["period_end"], format="%d.%m.%Y", errors="coerce")
    if pd.notna(report_date_dt):
        period_returns = compute_period_returns(
            current_report_id=int(report_id),
            current_value=float(selected_report["total_end"] or 0.0),
            current_date=report_date_dt.date(),
            historical_snapshots=[dict(row) for row in db.get_report_snapshots_summary()],
            deposits=[dict(row) for row in db.get_all_deposits()],
            withdrawals=db.get_external_withdrawals(),
        )

        st.subheader("📈 Доходность портфеля")
        period_labels = [
            ("day", "За день"),
            ("week", "За неделю"),
            ("month", "За месяц"),
            ("3m", "За 3 месяца"),
        ]
        period_cols = st.columns(4)
        for idx, (period_key, period_label) in enumerate(period_labels):
            period_data = period_returns.get(period_key)
            with period_cols[idx]:
                if not period_data:
                    st.metric(period_label, "—", "недостаточно данных")
                    continue
                abs_change = float(period_data.get("abs_change") or 0.0)
                twr_pct = period_data.get("twr_pct")
                twr_text = f"{twr_pct:+.2f}%" if twr_pct is not None else "—"
                st.metric(
                    period_label,
                    f"{abs_change:+,.2f} ₽",
                    twr_text,
                    delta_color="normal" if abs_change >= 0 else "inverse",
                )
                if twr_pct is None:
                    st.caption("TWR: —")

        all_data = period_returns.get("all") or {}
        all_abs_pnl = all_data.get("abs_pnl")
        all_twr_pct = all_data.get("twr_pct")
        all_net_contrib = all_data.get("net_contributions")

        all_col1, all_col2 = st.columns(2)
        with all_col1:
            if all_abs_pnl is None:
                st.metric("За всё время · Абсолютный P&L", "—")
            else:
                st.metric(
                    "За всё время · Абсолютный P&L",
                    f"{float(all_abs_pnl):+,.2f} ₽",
                    (
                        f"чистые пополнения {fmt(float(all_net_contrib or 0.0))} ₽"
                        if all_net_contrib is not None
                        else None
                    ),
                    delta_color="normal" if float(all_abs_pnl) >= 0 else "inverse",
                )
        with all_col2:
            st.metric(
                "За всё время · TWR",
                f"{all_twr_pct:+.2f}%" if all_twr_pct is not None else "—",
                (
                    f"{all_data['start_date'].strftime('%d.%m.%Y')} → {all_data['end_date'].strftime('%d.%m.%Y')}"
                    if all_data.get("start_date") and all_data.get("end_date")
                    else "недостаточно данных"
                ),
            )

        st.caption("Проценты по периодам рассчитаны по TWR (Modified Dietz) с нейтрализацией внешних потоков.")
        st.divider()

    if not pos_df.empty:
        col_pie, col_bar = st.columns(2)

        # Круговая диаграмма
        with col_pie:
            st.subheader("Структура портфеля")
            type_agg = build_asset_type_aggregation(pos_df, TYPE_LABELS)

            fig_pie = px.pie(
                type_agg,
                values="total",
                names="label",
                color="asset_type",
                color_discrete_map=TYPE_COLORS,
                hole=0.45,
            )
            fig_pie.update_traces(textinfo="percent+label", textfont_size=12)
            fig_pie.update_layout(
                showlegend=False,
                margin=dict(t=20, b=20, l=20, r=20),
                height=350,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        # Барчарт
        with col_bar:
            st.subheader("Стоимость по категориям")
            fig_bar = px.bar(
                type_agg.sort_values("total"),
                x="total",
                y="label",
                color="asset_type",
                color_discrete_map=TYPE_COLORS,
                orientation="h",
                text=type_agg.sort_values("total")["total"].apply(lambda v: f"{v:,.0f} ₽"),
            )
            fig_bar.update_traces(textposition="outside")
            fig_bar.update_layout(
                showlegend=False,
                xaxis_title="",
                yaxis_title="",
                margin=dict(t=20, b=20, l=20, r=80),
                height=350,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        # Лидеры роста / падения
        st.divider()
        col_up, col_down = st.columns(2)

        with col_up:
            st.subheader("▲ Лидеры роста")
            top_up = pos_df.nlargest(5, "change_value")[["name", "asset_type", "change_value"]].copy()
            top_up["Тип"] = top_up["asset_type"].map(TYPE_LABELS)
            top_up["Δ за день"] = top_up["change_value"].apply(lambda v: f"+{fmt(v)} ₽")
            st.dataframe(
                top_up[["name", "Тип", "Δ за день"]].rename(columns={"name": "Инструмент"}),
                hide_index=True,
                use_container_width=True,
            )

        with col_down:
            st.subheader("▼ Лидеры снижения")
            top_down = pos_df.nsmallest(5, "change_value")[["name", "asset_type", "change_value"]].copy()
            top_down["Тип"] = top_down["asset_type"].map(TYPE_LABELS)
            top_down["Δ за день"] = top_down["change_value"].apply(lambda v: f"{fmt(v)} ₽")
            st.dataframe(
                top_down[["name", "Тип", "Δ за день"]].rename(columns={"name": "Инструмент"}),
                hide_index=True,
                use_container_width=True,
            )

        # Движение ДС за день
        if cash_flows:
            st.divider()
            st.subheader("💸 Движение денежных средств")
            for cf in cash_flows:
                icon = "🟢" if cf["credit"] > 0 else "🔴"
                amount = cf["credit"] if cf["credit"] > 0 else cf["debit"]
                sign = "+" if cf["credit"] > 0 else "-"
                st.markdown(
                    f"{icon} **{cf['date']}** — {cf['description']} "
                    f"— **{sign}{fmt(amount)} {cf['currency']}**"
                )

    # История портфеля (если > 1 отчёта)
    history = db.get_portfolio_history()
    if len(history) > 1:
        st.divider()
        st.subheader("📈 Динамика портфеля vs Индекс МосБиржи")
        hist_df = pd.DataFrame([dict(h) for h in history])
        hist_df["period_end"] = pd.to_datetime(hist_df["period_end"], format="%d.%m.%Y")
        hist_df = hist_df.sort_values("period_end")

        # Нормализация портфеля к 100%
        base_portfolio = hist_df.iloc[0]["total_end"]
        hist_df["portfolio_pct"] = hist_df["total_end"] / base_portfolio * 100

        fig_hist = go.Figure()

        # Портфель
        fig_hist.add_trace(go.Scatter(
            x=hist_df["period_end"],
            y=hist_df["portfolio_pct"],
            mode="lines+markers",
            name="Портфель",
            line=dict(color="#22d3ee", width=2.5),
            customdata=hist_df["total_end"].values,
            hovertemplate="<b>Портфель</b><br>%{x}<br>%{y:.1f}% от старта<br>%{customdata:,.0f} ₽<extra></extra>",
        ))

        # Загрузка IMOEX
        try:
            import moex_api
            date_from = hist_df.iloc[0]["period_end"].strftime("%Y-%m-%d")
            date_to = hist_df.iloc[-1]["period_end"].strftime("%Y-%m-%d")
            imoex_data = moex_api.get_imoex_history(date_from, date_to)

            if imoex_data:
                imoex_df = pd.DataFrame(imoex_data)
                imoex_df["date"] = pd.to_datetime(imoex_df["date"])
                imoex_df = imoex_df.sort_values("date")

                # Нормализация IMOEX к 100%
                base_imoex = imoex_df.iloc[0]["close"]
                imoex_df["imoex_pct"] = imoex_df["close"] / base_imoex * 100

                fig_hist.add_trace(go.Scatter(
                    x=imoex_df["date"],
                    y=imoex_df["imoex_pct"],
                    mode="lines",
                    name="IMOEX",
                    line=dict(color="#64748b", width=1.5, dash="dot"),
                    hovertemplate="<b>IMOEX</b><br>%{x}<br>%{y:.1f}% от старта<extra></extra>",
                ))

                # Базовая линия 100%
                fig_hist.add_shape(
                    type="line",
                    x0=hist_df.iloc[0]["period_end"].isoformat(),
                    x1=hist_df.iloc[-1]["period_end"].isoformat(),
                    y0=100, y1=100,
                    line=dict(color="rgba(255,255,255,0.15)", width=1, dash="dash"),
                )

                # Сравнение доходностей
                portfolio_return = (hist_df.iloc[-1]["total_end"] / base_portfolio - 1) * 100
                imoex_return = (imoex_df.iloc[-1]["close"] / base_imoex - 1) * 100
                alpha = portfolio_return - imoex_return

                bc1, bc2, bc3 = st.columns(3)
                with bc1:
                    st.metric("Портфель", f"{portfolio_return:+.2f}%",
                              f"{fmt(hist_df.iloc[-1]['total_end'] - base_portfolio)} ₽")
                with bc2:
                    st.metric("IMOEX", f"{imoex_return:+.2f}%",
                              f"{imoex_df.iloc[-1]['close']:,.0f} пунктов")
                with bc3:
                    alpha_color = "normal" if alpha >= 0 else "inverse"
                    st.metric("Альфа (разница)", f"{alpha:+.2f}%",
                              "обгоняет рынок 🟢" if alpha >= 0 else "отстаёт от рынка 🔴",
                              delta_color=alpha_color)
        except Exception:
            pass  # IMOEX недоступен — показываем только портфель

        fig_hist.update_layout(
            yaxis_title="% от начальной стоимости",
            height=350,
            margin=dict(t=20, b=20),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=1.1),
            hovermode="x unified",
        )
        st.plotly_chart(fig_hist, use_container_width=True)


# ─── TAB: ПОЗИЦИИ ───
with tab_positions:
    if pos_df.empty:
        st.info("Нет данных о позициях")
    else:
        view_mode = st.radio(
            "Режим таблицы",
            options=list(POSITIONS_TABLE_VIEW_MODES),
            index=0,
            horizontal=True,
        )

        # Загрузка средних цен
        cost_map = cost_basis_all

        filters_state_id = int(st.session_state.get("positions_filters_state_id", 0))
        reset_col, _ = st.columns([1, 4])
        with reset_col:
            if st.button("Сбросить фильтры", key=f"positions_reset_filters_{filters_state_id}"):
                st.session_state["positions_filters_state_id"] = filters_state_id + 1
                st.rerun()

        filters_state_id = int(st.session_state.get("positions_filters_state_id", 0))

        # Базовые фильтры
        col_filter, col_status, col_sort = st.columns(3)
        with col_filter:
            type_filter = st.multiselect(
                "Тип актива",
                options=list(TYPE_LABELS.keys()),
                format_func=lambda x: TYPE_LABELS[x],
                default=list(TYPE_LABELS.keys()),
                key=f"positions_type_filter_{filters_state_id}",
            )
        with col_status:
            premium_filter = st.selectbox(
                "К номиналу",
                options=list(PREMIUM_FILTER_OPTIONS.keys()),
                format_func=lambda x: PREMIUM_FILTER_OPTIONS[x],
                index=0,
                key=f"positions_premium_filter_{filters_state_id}",
            )
        with col_sort:
            sort_col = st.selectbox(
                "Сортировка",
                ["По стоимости", "По изменению", "По P&L", "По YTM", "По имени"],
                key=f"positions_sort_col_{filters_state_id}",
            )

        filtered = prepare_positions_dataset(
            pos_df=pos_df,
            type_filter=type_filter,
            bond_asset_types=BOND_ASSET_TYPES,
            ytm_by_isin=ytm_by_isin,
            issuer_by_isin=issuer_by_isin,
            issuer_share_map=issuer_share_map,
            position_share_map=position_share_map,
            cost_map=cost_map,
            sort_col=sort_col,
            rating_by_isin=rating_by_isin,
            maturity_by_isin=maturity_by_isin,
            as_of_date=date.today(),
        )

        # Расширенные фильтры
        warning_filter_labels = {
            "all": "Все",
            "with_warnings": "Есть предупреждения",
            "without_warnings": "Без предупреждений",
        }
        data_quality_filter_labels = {
            "all": "Все",
            "with_issues": "Есть проблемы качества",
            "without_issues": "Без проблем качества",
        }

        issuer_options = sorted({
            issuer
            for issuer in filtered["issuer"].dropna().tolist()
            if isinstance(issuer, str) and issuer
        })

        adv_col1, adv_col2, adv_col3 = st.columns(3)
        with adv_col1:
            issuer_filter = st.multiselect(
                "Эмитент",
                options=issuer_options,
                default=[],
                key=f"positions_issuer_filter_{filters_state_id}",
            )
        with adv_col2:
            warning_filter = st.selectbox(
                "Предупреждения",
                options=list(POSITIONS_WARNING_FILTER_OPTIONS),
                format_func=lambda x: warning_filter_labels.get(x, x),
                index=0,
                key=f"positions_warning_filter_{filters_state_id}",
            )
        with adv_col3:
            data_quality_filter = st.selectbox(
                "Качество данных",
                options=list(POSITIONS_DATA_QUALITY_FILTER_OPTIONS),
                format_func=lambda x: data_quality_filter_labels.get(x, x),
                index=0,
                key=f"positions_quality_filter_{filters_state_id}",
            )

        range_col1, range_col2, range_col3 = st.columns(3)

        ytm_range = None
        ytm_values = filtered["ytm"].dropna()
        with range_col1:
            use_ytm_filter = st.checkbox(
                "YTM min/max",
                value=False,
                key=f"positions_use_ytm_filter_{filters_state_id}",
            )
            if use_ytm_filter:
                if ytm_values.empty:
                    st.caption("Нет данных YTM для выбранных позиций.")
                else:
                    ytm_min_value = float(ytm_values.min())
                    ytm_max_value = float(ytm_values.max())
                    if ytm_min_value == ytm_max_value:
                        ytm_range = (ytm_min_value, ytm_max_value)
                        st.caption(f"Доступно одно значение YTM: {ytm_min_value:.2f}%")
                    else:
                        ytm_range = st.slider(
                            "Диапазон YTM, %",
                            min_value=ytm_min_value,
                            max_value=ytm_max_value,
                            value=(ytm_min_value, ytm_max_value),
                            step=0.1,
                            key=f"positions_ytm_range_{filters_state_id}",
                        )

        position_share_range = None
        position_share_values = (filtered["position_share"].dropna() * 100.0)
        with range_col2:
            use_position_share_filter = st.checkbox(
                "Доля позиции min/max",
                value=False,
                key=f"positions_use_share_filter_{filters_state_id}",
            )
            if use_position_share_filter:
                if position_share_values.empty:
                    st.caption("Нет данных доли позиции для выбранных позиций.")
                else:
                    share_min_value = float(position_share_values.min())
                    share_max_value = float(position_share_values.max())
                    if share_min_value == share_max_value:
                        position_share_range = (share_min_value / 100.0, share_max_value / 100.0)
                        st.caption(f"Доступно одно значение доли: {share_min_value:.2f}%")
                    else:
                        selected_share_range = st.slider(
                            "Диапазон доли, %",
                            min_value=share_min_value,
                            max_value=share_max_value,
                            value=(share_min_value, share_max_value),
                            step=0.1,
                            key=f"positions_share_range_{filters_state_id}",
                        )
                        position_share_range = (
                            selected_share_range[0] / 100.0,
                            selected_share_range[1] / 100.0,
                        )

        years_to_maturity_range = None
        years_values = filtered["years_to_maturity"].dropna()
        with range_col3:
            use_maturity_filter = st.checkbox(
                "Срок до погашения min/max",
                value=False,
                key=f"positions_use_maturity_filter_{filters_state_id}",
            )
            if use_maturity_filter:
                if years_values.empty:
                    st.caption("Нет данных срока до погашения для выбранных позиций.")
                else:
                    years_min_value = float(years_values.min())
                    years_max_value = float(years_values.max())
                    if years_min_value == years_max_value:
                        years_to_maturity_range = (years_min_value, years_max_value)
                        st.caption(f"Доступно одно значение срока: {years_min_value:.2f} лет")
                    else:
                        years_to_maturity_range = st.slider(
                            "Диапазон срока, лет",
                            min_value=years_min_value,
                            max_value=years_max_value,
                            value=(years_min_value, years_max_value),
                            step=0.1,
                            key=f"positions_maturity_range_{filters_state_id}",
                        )

        data_quality_isins = {
            str(row.get("isin"))
            for row in data_quality_report.get("bonds", [])
            if isinstance(row.get("isin"), str) and row.get("isin")
        }
        filtered = apply_positions_advanced_filters(
            filtered=filtered,
            issuer_filter=issuer_filter,
            ytm_range=ytm_range,
            position_share_range=position_share_range,
            years_to_maturity_range=years_to_maturity_range,
            warning_filter=warning_filter,
            data_quality_filter=data_quality_filter,
            premium_filter=premium_filter,
            data_quality_isins=data_quality_isins,
            warning_share_threshold=ATTENTION_CONCENTRATION_THRESHOLD,
        )

        st.subheader("📈 YTM vs срок до погашения")
        ytm_chart_result = plot_ytm_vs_maturity(filtered)
        ytm_scatter = ytm_chart_result.get("figure")
        excluded_positions = ytm_chart_result.get("excluded_positions", [])
        included_count = int(ytm_chart_result.get("included_count") or 0)

        if ytm_scatter is not None:
            st.plotly_chart(ytm_scatter, use_container_width=True)
            st.caption(f"В график включено позиций: {included_count}.")
        else:
            st.info("Недостаточно данных для графика: нужны позиции одновременно с YTM и сроком до погашения.")

        if excluded_positions:
            excluded_df = pd.DataFrame(excluded_positions).rename(
                columns={
                    "name": "Инструмент",
                    "isin": "ISIN",
                    "reason": "Причина исключения",
                }
            )
            st.caption("Исключённые из графика позиции:")
            st.dataframe(
                excluded_df[["Инструмент", "ISIN", "Причина исключения"]],
                hide_index=True,
                use_container_width=True,
            )
        elif not filtered.empty:
            st.caption("Все выбранные позиции включены в график.")

        st.divider()

        # Таблица позиций
        total_value = calculate_total_portfolio_value(filtered)
        if filtered.empty:
            st.info("По выбранным фильтрам позиции не найдены. Нажмите «Сбросить фильтры» или расширьте диапазоны.")
        else:
            display_df = prepare_positions_display_table(
                filtered=filtered,
                type_labels=TYPE_LABELS,
                format_ytm_fn=moex_api.format_ytm,
            )

            selected_columns = get_positions_table_columns(
                view_mode=view_mode,
                available_columns=display_df.columns,
            )

            st.dataframe(
                display_df[selected_columns],
                hide_index=True,
                use_container_width=True,
                height=min(700, len(filtered) * 38 + 40),
                column_config={
                    "Ср. цена": st.column_config.NumberColumn(format="%.2f ₽"),
                    "Цена": st.column_config.NumberColumn(format="%.2f ₽"),
                    "Доля портфеля %": st.column_config.NumberColumn(format="%.1f%%"),
                    "Доля эмитента %": st.column_config.NumberColumn(format="%.1f%%"),
                    "Полная стоимость": st.column_config.NumberColumn(format="%.2f ₽"),
                    "Δ за день": st.column_config.NumberColumn(format="%+.2f ₽"),
                    "P&L ₽": st.column_config.NumberColumn(format="%+.2f ₽"),
                    "P&L %": st.column_config.NumberColumn(format="%+.1f%%"),
                },
            )

            export_df = prepare_positions_export_table(
                filtered=filtered,
                type_labels=TYPE_LABELS,
            )
            csv_bytes = export_df.to_csv(index=False).encode("utf-8-sig")
            report_date_label = str(selected_report["period_end"] or "report").replace(".", "-")
            st.download_button(
                "Скачать позиции CSV",
                data=csv_bytes,
                file_name=f"positions_{report_date_label}.csv",
                mime="text/csv",
                use_container_width=False,
            )

        # P&L итоги
        pnl_summary = calculate_pnl_summary(filtered, cost_map)
        if pnl_summary["has_pnl"]:
            st.divider()

            pc1, pc2, pc3, pc4 = st.columns(4)
            with pc1:
                st.metric("Позиций с P&L", f"{pnl_summary['has_pnl_count']} из {pnl_summary['total_count']}")
            with pc2:
                st.metric("Нереализ. P&L", f"{pnl_summary['total_pnl']:+,.2f} ₽")
            with pc3:
                st.metric("P&L %", f"{pnl_summary['total_pnl_pct']:+.2f}%")
            with pc4:
                st.metric("В плюсе / минусе", f"{pnl_summary['winners']} 🟢 / {pnl_summary['losers']} 🔴")

        # Общие итоги
        st.divider()
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Позиций", len(filtered))
        with c2:
            st.metric("Общая стоимость", f"{fmt(total_value)} ₽")
        with c3:
            total_change = filtered["change_value"].sum()
            st.metric("Изменение за день", f"{total_change:+,.2f} ₽")

        # ─── Управление средними ценами ───
        st.divider()
        st.subheader("📝 Средние цены покупки")

        mgmt_col1, mgmt_col2 = st.columns([1, 2])

        with mgmt_col1:
            if st.button("🔄 Пересчитать из сделок", help="Рассчитает средние цены из всех загруженных сделок"):
                count = db.sync_cost_basis_from_trades()
                st.success(f"✅ Рассчитано для {count} позиций")
                st.rerun()

        with mgmt_col2:
            st.caption(
                "Средние цены автоматически считаются из загруженных сделок. "
                "Если у позиции нет сделок (куплена до первого отчёта) — укажите цену вручную ниже."
            )

        # Список позиций без средней цены
        missing = [
            (row["isin"], row["name"], row["price_end"], row["qty"])
            for _, row in filtered.iterrows()
            if row["isin"] not in cost_map
        ]

        if missing:
            st.warning(f"⚠️ Нет средней цены для {len(missing)} позиций")

        with st.expander("➕ Указать среднюю цену вручную"):
            all_positions = [(row["isin"], row["name"], row["qty"]) for _, row in filtered.iterrows()]
            selected_pos = st.selectbox(
                "Позиция",
                all_positions,
                format_func=lambda x: f"{x[1]} ({x[0]})",
            )

            if selected_pos:
                existing = cost_map.get(selected_pos[0])
                default_price = existing["avg_price"] if existing else 0.0

                m_price = st.number_input(
                    "Средняя цена покупки, ₽",
                    value=default_price,
                    step=0.01,
                    min_value=0.0,
                    format="%.2f",
                )

                if st.button("💾 Сохранить цену"):
                    if m_price > 0:
                        total_cost = m_price * selected_pos[2]
                        db.upsert_cost_basis(
                            isin=selected_pos[0],
                            name=selected_pos[1],
                            avg_price=m_price,
                            total_qty=selected_pos[2],
                            total_cost=total_cost,
                            source="manual",
                        )
                        st.success(f"✅ Сохранено: {selected_pos[1]} — ср. цена {fmt(m_price)} ₽")
                        st.rerun()
                    else:
                        st.warning("Цена должна быть больше 0")


# ─── TAB: ПОПОЛНЕНИЯ И ВЫЧЕТ ───
with tab_deposits:
    if dep_df.empty:
        st.info("Нет данных о пополнениях")
    else:
        # Напоминание о вычете
        st.subheader("🏦 Налоговый вычет ИИС-3")

        # Считаем пополнения за текущий год
        year_deposits = dep_df[dep_df["year"] == CURRENT_YEAR] if "year" in dep_df.columns else pd.DataFrame()
        deposited_this_year = year_deposits["amount"].sum() if not year_deposits.empty else 0

        remaining_for_deduction = max(0, IIS3_TAX_DEDUCTION_LIMIT - deposited_this_year)
        potential_refund = min(deposited_this_year, IIS3_TAX_DEDUCTION_LIMIT) * IIS3_TAX_REFUND_RATE
        max_refund = IIS3_TAX_DEDUCTION_LIMIT * IIS3_TAX_REFUND_RATE

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric(
                f"Внесено в {CURRENT_YEAR}",
                f"{fmt(deposited_this_year)} ₽",
                f"из {fmt(IIS3_TAX_DEDUCTION_LIMIT)} ₽ лимита",
            )
        with c2:
            st.metric(
                "Осталось до макс. вычета",
                f"{fmt(remaining_for_deduction)} ₽",
                f"= ещё {fmt(remaining_for_deduction * IIS3_TAX_REFUND_RATE)} ₽ возврата" if remaining_for_deduction > 0 else "Лимит исчерпан ✅",
            )
        with c3:
            st.metric(
                "Вычет за год (13%)",
                f"{fmt(potential_refund)} ₽",
                f"макс. {fmt(max_refund)} ₽" if potential_refund < max_refund else "Максимум! 🎯",
            )

        if remaining_for_deduction > 0:
            months_left = 12 - date.today().month
            monthly = remaining_for_deduction / max(months_left, 1) if months_left > 0 else remaining_for_deduction
            st.markdown(f"""
            <div class="iis-reminder">
                <b>💡 Напоминание:</b> Чтобы получить максимальный вычет <b>{fmt(max_refund)} ₽</b>,
                нужно до конца {CURRENT_YEAR} года внести ещё <b>{fmt(remaining_for_deduction)} ₽</b>
                (~<b>{fmt(monthly)} ₽/мес</b> × {months_left} мес.).
            </div>
            """, unsafe_allow_html=True)

        # Прогресс-бар
        progress = min(deposited_this_year / IIS3_TAX_DEDUCTION_LIMIT, 1.0)
        st.progress(progress, text=f"Заполнено {progress:.0%} лимита вычета")

        st.divider()

        # История пополнений по типу ИИС
        col_iis, col_iis3 = st.columns(2)

        iis_old = dep_df[dep_df["iis_type"] == "ИИС"]
        iis3 = dep_df[dep_df["iis_type"] == "ИИС-3"]

        with col_iis:
            st.subheader("📄 ИИС (старый)")
            if not iis_old.empty:
                st.metric("Итого внесено", f"{fmt(iis_old['amount'].sum())} ₽")
                st.dataframe(
                    iis_old[["date", "amount"]].rename(columns={"date": "Дата", "amount": "Сумма, ₽"}),
                    hide_index=True,
                    use_container_width=True,
                    column_config={"Сумма, ₽": st.column_config.NumberColumn(format="%.0f ₽")},
                )
            else:
                st.info("Нет пополнений")

        with col_iis3:
            st.subheader("📄 ИИС-3")
            if not iis3.empty:
                st.metric("Итого внесено", f"{fmt(iis3['amount'].sum())} ₽")
                st.dataframe(
                    iis3[["date", "amount"]].rename(columns={"date": "Дата", "amount": "Сумма, ₽"}),
                    hide_index=True,
                    use_container_width=True,
                    column_config={"Сумма, ₽": st.column_config.NumberColumn(format="%.0f ₽")},
                )
            else:
                st.info("Нет пополнений")


# ─── TAB: КАЛЕНДАРЬ ───
with tab_calendar:
    st.subheader("📅 Календарь купонов")

    # ─── Кнопка синхронизации с MOEX ───
    col_sync, col_status = st.columns([1, 3])
    with col_sync:
        sync_clicked = st.button("🔄 Загрузить с MOEX", type="primary", use_container_width=True)
    with col_status:
        if sync_clicked:
            import moex_api
            with st.spinner("Загрузка купонов с Московской биржи..."):
                pos_list = [dict(p) for p in positions]
                stats = moex_api.sync_coupons_for_portfolio(pos_list, future_only=True)
            if stats["synced"] > 0:
                st.success(
                    f"✅ Загружено {stats['synced']} купонов "
                    f"по {stats['bonds_processed']} облигациям"
                )
            else:
                st.info(f"Обработано {stats['bonds_processed']} облигаций, новых купонов нет")
            if stats["errors"]:
                for e in stats["errors"]:
                    st.warning(f"⚠️ {e}")
            st.rerun()
    st.caption(format_sync_freshness_caption("Купоны (MOEX)", db.get_data_sync_freshness("coupon")))

    # ─── Отображение календаря ───
    coupons = db.get_coupon_calendar()
    if coupons:
        coup_df = pd.DataFrame([dict(c) for c in coupons])
        coup_df["coupon_date"] = pd.to_datetime(coup_df["coupon_date"])

        today = pd.Timestamp.today().normalize()
        upcoming = coup_df[coup_df["coupon_date"] >= today].sort_values("coupon_date")
        past = coup_df[coup_df["coupon_date"] < today].sort_values("coupon_date", ascending=False)

        if not upcoming.empty:
            # KPI карточки
            total_expected = upcoming["expected_income"].sum()
            next_coupon = upcoming.iloc[0]
            days_to_next = (next_coupon["coupon_date"] - today).days

            # Доход по месяцам (для KPI текущего месяца)
            upcoming_monthly = upcoming.copy()
            upcoming_monthly["month"] = upcoming_monthly["coupon_date"].dt.to_period("M")
            monthly_income = upcoming_monthly.groupby("month")["expected_income"].sum()

            cashflow_12m = build_coupon_cashflow_by_month(
                coupons=coupons,
                positions=positions,
                months=12,
                as_of_date=date.today(),
            )
            cashflow_df = pd.DataFrame(cashflow_12m["months"])
            cashflow_df["month_label"] = pd.to_datetime(
                cashflow_df["month"] + "-01",
                format="%Y-%m-%d",
            ).dt.strftime("%m.%Y")

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("Ожидаемый доход", f"{fmt(total_expected)} ₽",
                          f"{len(upcoming)} выплат")
            with c2:
                st.metric("Ближайший купон", f"{next_coupon['coupon_date'].strftime('%d.%m.%Y')}",
                          f"через {days_to_next} дн.")
            with c3:
                st.metric("Ближайшая выплата", f"{fmt(next_coupon['expected_income'])} ₽",
                          next_coupon["name"])
            with c4:
                current_month = today.to_period("M")
                this_month_income = monthly_income.get(current_month, 0)
                st.metric("В этом месяце", f"{fmt(this_month_income)} ₽")

            st.divider()

            # ─── Купонный поток на 12 месяцев ───
            st.subheader("📊 Купонный поток на 12 месяцев")
            if cashflow_12m["total_payments"] == 0:
                st.info("На ближайшие 12 месяцев: нет данных по купонным выплатам.")

            coupon_chart_result = plot_coupon_cashflow_by_month(cashflow_df)
            fig_monthly = coupon_chart_result.get("figure")
            sorted_cashflow_df = coupon_chart_result.get("dataframe", cashflow_df)
            if fig_monthly is not None:
                st.plotly_chart(fig_monthly, use_container_width=True)
            st.caption(f"Общая сумма купонного потока за 12 месяцев: **{fmt(cashflow_12m['total_income'])} ₽**.")

            cashflow_display = sorted_cashflow_df[[
                "month_label", "income", "payments_count", "bonds_text"
            ]].rename(
                columns={
                    "month_label": "Месяц",
                    "income": "Сумма купонов ₽",
                    "payments_count": "Выплат",
                    "bonds_text": "Список бумаг",
                }
            )
            st.dataframe(
                cashflow_display,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Сумма купонов ₽": st.column_config.NumberColumn(format="%.2f ₽"),
                    "Выплат": st.column_config.NumberColumn(format="%d"),
                },
            )

            st.divider()

            # ─── Таблица предстоящих купонов ───
            st.subheader("📆 Предстоящие выплаты")

            # Группировка по облигации
            view_mode = st.radio(
                "Группировка",
                ["По дате", "По облигации"],
                horizontal=True,
                label_visibility="collapsed",
            )

            if view_mode == "По дате":
                display = upcoming[["coupon_date", "name", "coupon_rate", "coupon_amount", "qty", "expected_income"]].copy()
                display["coupon_date"] = display["coupon_date"].dt.strftime("%d.%m.%Y")
                display.columns = ["Дата", "Облигация", "Ставка %", "Купон/шт ₽", "Кол-во", "Ожид. доход ₽"]
                st.dataframe(
                    display,
                    hide_index=True,
                    use_container_width=True,
                    height=min(600, len(display) * 38 + 40),
                    column_config={
                        "Ставка %": st.column_config.NumberColumn(format="%.2f%%"),
                        "Купон/шт ₽": st.column_config.NumberColumn(format="%.2f ₽"),
                        "Ожид. доход ₽": st.column_config.NumberColumn(format="%.2f ₽"),
                    },
                )
            else:
                bond_agg = upcoming.groupby("name").agg(
                    count=("coupon_date", "count"),
                    next_date=("coupon_date", "min"),
                    total_income=("expected_income", "sum"),
                    avg_coupon=("coupon_amount", "mean"),
                    qty=("qty", "first"),
                    rate=("coupon_rate", "first"),
                ).reset_index().sort_values("total_income", ascending=False)
                bond_agg["next_date"] = bond_agg["next_date"].dt.strftime("%d.%m.%Y")
                bond_agg.columns = ["Облигация", "Купонов", "Ближайший", "Итого доход ₽", "Ср. купон ₽", "Кол-во", "Ставка %"]
                st.dataframe(
                    bond_agg,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Итого доход ₽": st.column_config.NumberColumn(format="%.2f ₽"),
                        "Ср. купон ₽": st.column_config.NumberColumn(format="%.2f ₽"),
                        "Ставка %": st.column_config.NumberColumn(format="%.2f%%"),
                    },
                )

            # Итого
            st.divider()
            st.metric("💰 Итого ожидаемый купонный доход", f"{fmt(total_expected)} ₽")

        if not past.empty:
            with st.expander(f"📜 Прошедшие выплаты ({len(past)})"):
                display_p = past[["coupon_date", "name", "coupon_amount", "qty", "expected_income"]].copy()
                display_p["coupon_date"] = display_p["coupon_date"].dt.strftime("%d.%m.%Y")
                display_p.columns = ["Дата", "Облигация", "Купон/шт ₽", "Кол-во", "Доход ₽"]
                st.dataframe(display_p, hide_index=True, use_container_width=True)
    else:
        st.info("👆 Нажмите «Загрузить с MOEX» чтобы получить расписание купонов по облигациям в портфеле.")

    # ─── Ручное добавление ───
    with st.expander("➕ Добавить купон вручную"):
        col1, col2 = st.columns(2)
        with col1:
            c_name = st.text_input("Название облигации", placeholder="Селигдар 4Р")
            c_isin = st.text_input("ISIN", placeholder="RU000A10C5L7")
            c_date = st.date_input("Дата выплаты купона")
        with col2:
            c_rate = st.number_input("Ставка купона, %", value=0.0, step=0.1)
            c_amount = st.number_input("Сумма купона на 1 бумагу, ₽", value=0.0, step=0.01)
            c_qty = st.number_input("Количество в портфеле", value=0, step=1)

        if st.button("Сохранить купон"):
            if c_isin and c_name:
                expected = c_amount * c_qty
                db.upsert_coupon(
                    isin=c_isin,
                    name=c_name,
                    coupon_date=c_date.strftime("%Y-%m-%d"),
                    coupon_rate=c_rate,
                    coupon_amount=c_amount,
                    nominal=1000,
                    qty=c_qty,
                    expected_income=expected,
                )
                st.success(f"✅ Сохранено: {c_name} — {c_date} — ожидаемый доход {fmt(expected)} ₽")
                st.rerun()
            else:
                st.warning("Заполните ISIN и название")

    # ─── Дивидендный календарь ───
    st.divider()
    st.subheader("💎 Дивидендный календарь")

    col_div_sync, col_div_status = st.columns([1, 3])
    with col_div_sync:
        div_sync_clicked = st.button("🔄 Загрузить дивиденды с MOEX", use_container_width=True)
    with col_div_status:
        if div_sync_clicked:
            import moex_api
            with st.spinner("Загрузка дивидендов с Московской биржи..."):
                pos_list = [dict(p) for p in positions]
                div_stats = moex_api.sync_dividends_for_portfolio(pos_list, future_only=False)
            if div_stats["synced"] > 0:
                st.success(
                    f"✅ Загружено {div_stats['synced']} дивидендов "
                    f"по {div_stats['stocks_processed']} акциям"
                )
            else:
                st.info(f"Обработано {div_stats['stocks_processed']} акций, новых дивидендов нет")
            if div_stats["errors"]:
                for e in div_stats["errors"]:
                    st.warning(f"⚠️ {e}")
            st.rerun()

    dividends = db.get_dividend_calendar()
    if dividends:
        div_df = pd.DataFrame([dict(d) for d in dividends])
        div_df["record_date"] = pd.to_datetime(div_df["record_date"])

        today_div = pd.Timestamp.today().normalize()
        upcoming_div = div_df[div_df["record_date"] >= today_div].sort_values("record_date")
        past_div = div_df[div_df["record_date"] < today_div].sort_values("record_date", ascending=False)

        if not upcoming_div.empty:
            st.markdown("#### 📆 Предстоящие дивиденды")

            d1, d2, d3 = st.columns(3)
            with d1:
                st.metric("Ожидаемый доход", f"{fmt(upcoming_div['expected_income'].sum())} ₽")
            with d2:
                next_div = upcoming_div.iloc[0]
                days_to = (next_div["record_date"] - today_div).days
                st.metric("Ближайший", f"{next_div['record_date'].strftime('%d.%m.%Y')}",
                          f"{next_div['name']} · через {days_to} дн.")
            with d3:
                st.metric("Выплат впереди", f"{len(upcoming_div)}")

            display_div = upcoming_div[["record_date", "name", "ticker", "dividend_amount", "qty", "expected_income"]].copy()
            display_div["record_date"] = display_div["record_date"].dt.strftime("%d.%m.%Y")
            display_div.columns = ["Дата отсечки", "Компания", "Тикер", "Дивиденд/шт ₽", "Кол-во", "Ожид. доход ₽"]
            st.dataframe(
                display_div,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Дивиденд/шт ₽": st.column_config.NumberColumn(format="%.2f ₽"),
                    "Ожид. доход ₽": st.column_config.NumberColumn(format="%.2f ₽"),
                },
            )

        if not past_div.empty:
            with st.expander(f"📜 Прошедшие дивиденды ({len(past_div)})"):
                display_past_div = past_div[["record_date", "name", "ticker", "dividend_amount", "qty", "expected_income"]].copy()
                display_past_div["record_date"] = display_past_div["record_date"].dt.strftime("%d.%m.%Y")
                display_past_div.columns = ["Дата", "Компания", "Тикер", "Дивиденд/шт ₽", "Кол-во", "Доход ₽"]
                st.dataframe(display_past_div, hide_index=True, use_container_width=True)
                st.metric("Итого получено", f"{fmt(past_div['expected_income'].sum())} ₽")
    else:
        st.info("Нажмите «Загрузить дивиденды с MOEX» для получения дат выплат по акциям в портфеле.")

    # ─── Лестница погашений ───
    st.divider()
    st.subheader("🪜 Лестница погашений облигаций")

    col_mat_sync, col_mat_status = st.columns([1, 3])
    with col_mat_sync:
        mat_sync_clicked = st.button("🔄 Загрузить погашения с MOEX", use_container_width=True)
    with col_mat_status:
        if mat_sync_clicked:
            import moex_api
            with st.spinner("Загрузка данных о погашениях и амортизациях..."):
                pos_list = [dict(p) for p in positions]
                mat_stats = moex_api.sync_maturity_for_portfolio(pos_list)
            if mat_stats["synced"] > 0:
                st.success(
                    f"✅ Загружено {mat_stats['synced']} погашений "
                    f"по {mat_stats['bonds_processed']} облигациям"
                )
            else:
                st.info(f"Обработано {mat_stats['bonds_processed']} облигаций, данных нет")
            if mat_stats["errors"]:
                for e in mat_stats["errors"]:
                    st.warning(f"⚠️ {e}")
            st.rerun()
    st.caption(format_sync_freshness_caption("Погашения (MOEX)", db.get_data_sync_freshness("maturity")))

    maturities = db.get_bond_maturities()
    amortizations = db.get_bond_amortizations()

    if maturities:
        mat_df = pd.DataFrame([dict(m) for m in maturities])
        mat_df["maturity_date"] = pd.to_datetime(mat_df["maturity_date"])
        mat_df = mat_df.sort_values("maturity_date")

        today_mat = pd.Timestamp.today().normalize()
        mat_df["days_to"] = (mat_df["maturity_date"] - today_mat).dt.days
        mat_df["years_to"] = (mat_df["days_to"] / 365.25).round(1)

        # KPI
        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            st.metric("Облигаций", len(mat_df))
        with mc2:
            next_mat = mat_df[mat_df["days_to"] > 0].iloc[0] if not mat_df[mat_df["days_to"] > 0].empty else None
            if next_mat is not None:
                st.metric("Ближайшее погашение",
                          next_mat["maturity_date"].strftime("%d.%m.%Y"),
                          f"{next_mat['name']} · через {next_mat['days_to']} дн.")
            else:
                st.metric("Ближайшее погашение", "—")
        with mc3:
            total_maturity = mat_df["maturity_value"].sum()
            st.metric("Всего к погашению", f"{fmt(total_maturity)} ₽")

        # ─── Timeline chart ───
        fig_ladder = go.Figure()

        # Цвета по типу
        bond_colors = {"bond_ofz_pd": "#22d3ee", "bond_ofz_in": "#3b82f6", "bond_corp": "#a78bfa"}

        # Определим тип облигации по ISIN из позиций
        isin_to_type = {}
        if not pos_df.empty:
            for _, row in pos_df.iterrows():
                isin_to_type[row["isin"]] = row["asset_type"]

        for _, bond in mat_df.iterrows():
            btype = isin_to_type.get(bond["isin"], "bond_corp")
            color = bond_colors.get(btype, "#a78bfa")

            fig_ladder.add_trace(go.Bar(
                x=[bond["maturity_value"]],
                y=[bond["name"]],
                orientation="h",
                name=bond["name"],
                marker_color=color,
                text=f"{bond['maturity_date'].strftime('%d.%m.%Y')} · {fmt(bond['maturity_value'])} ₽ · {bond['years_to']} лет",
                textposition="outside",
                showlegend=False,
                hovertemplate=(
                    f"<b>{bond['name']}</b><br>"
                    f"Погашение: {bond['maturity_date'].strftime('%d.%m.%Y')}<br>"
                    f"Номинал: {bond['nominal']:,.0f} ₽ × {bond['qty']} шт.<br>"
                    f"К получению: {bond['maturity_value']:,.0f} ₽<br>"
                    f"Ставка: {bond['coupon_rate']:.2f}%<br>"
                    f"{'⚠️ Амортизация' if bond['has_amortization'] else ''}"
                    "<extra></extra>"
                ),
            ))

        fig_ladder.update_layout(
            xaxis_title="Сумма к погашению, ₽",
            yaxis_title="",
            height=max(300, len(mat_df) * 45),
            margin=dict(t=20, b=40, r=200),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            barmode="stack",
        )
        st.plotly_chart(fig_ladder, use_container_width=True)

        # ─── Таймлайн ───
        st.markdown("#### 📅 Таймлайн погашений")

        fig_timeline = go.Figure()

        for i, (_, bond) in enumerate(mat_df.iterrows()):
            btype = isin_to_type.get(bond["isin"], "bond_corp")
            color = bond_colors.get(btype, "#a78bfa")

            fig_timeline.add_trace(go.Scatter(
                x=[today_mat, bond["maturity_date"]],
                y=[i, i],
                mode="lines+markers",
                line=dict(color=color, width=3),
                marker=dict(size=[6, 12], color=[color, color], symbol=["circle", "diamond"]),
                name=bond["name"],
                showlegend=False,
                hovertemplate=f"<b>{bond['name']}</b><br>{bond['maturity_date'].strftime('%d.%m.%Y')}<br>{fmt(bond['maturity_value'])} ₽<extra></extra>",
            ))

            fig_timeline.add_annotation(
                x=bond["maturity_date"],
                y=i,
                text=f" {bond['name']} ({bond['maturity_date'].strftime('%m.%Y')})",
                showarrow=False,
                xanchor="left",
                font=dict(size=11),
            )

        # Линия "сегодня"
        fig_timeline.add_shape(
            type="line",
            x0=today_mat.isoformat(), x1=today_mat.isoformat(),
            y0=0, y1=1, yref="paper",
            line=dict(color="#f59e0b", width=2, dash="dot"),
        )
        fig_timeline.add_annotation(
            x=today_mat.isoformat(), y=1, yref="paper",
            text="Сегодня", showarrow=False,
            yanchor="bottom", font=dict(color="#f59e0b", size=11),
        )

        fig_timeline.update_layout(
            xaxis_title="",
            yaxis_visible=False,
            height=max(250, len(mat_df) * 35),
            margin=dict(t=40, b=20, r=200),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_timeline, use_container_width=True)

        # ─── Таблица ───
        with st.expander("📋 Детальная таблица"):
            display_mat = mat_df[[
                "name", "maturity_date", "nominal", "qty", "maturity_value",
                "coupon_rate", "has_amortization", "days_to", "years_to"
            ]].copy()
            display_mat["maturity_date"] = display_mat["maturity_date"].dt.strftime("%d.%m.%Y")
            display_mat["has_amortization"] = display_mat["has_amortization"].apply(lambda x: "Да" if x else "Нет")
            display_mat.columns = [
                "Облигация", "Дата погашения", "Номинал ₽", "Кол-во",
                "К получению ₽", "Ставка %", "Амортизация", "Дней", "Лет"
            ]
            st.dataframe(display_mat, hide_index=True, use_container_width=True,
                         column_config={
                             "Номинал ₽": st.column_config.NumberColumn(format="%.0f ₽"),
                             "К получению ₽": st.column_config.NumberColumn(format="%.0f ₽"),
                             "Ставка %": st.column_config.NumberColumn(format="%.2f%%"),
                         })

        # Лестница возврата номинала по годам
        maturity_rows = [dict(m) for m in maturities]
        amortization_rows = [dict(a) for a in amortizations] if amortizations else []
        ladder = build_maturity_ladder(
            positions=pos_list,
            maturities=maturity_rows,
            amortizations=amortization_rows,
            as_of_date=today_mat.date(),
        )

        if ladder["years"]:
            st.markdown("#### 💰 Лестница возврата номинала по годам")
            ladder_df = pd.DataFrame(ladder["years"])
            ladder_chart_result = plot_maturity_ladder(ladder_df)
            fig_yearly = ladder_chart_result.get("figure")
            ladder_df = ladder_chart_result.get("dataframe", ladder_df)
            if fig_yearly is not None:
                st.plotly_chart(fig_yearly, use_container_width=True)

            ladder_display = ladder_df[[
                "year", "maturity_return", "amortization_return", "total_return",
                "maturity_count", "amortization_count"
            ]].rename(
                columns={
                    "year": "Год",
                    "maturity_return": "Погашения ₽",
                    "amortization_return": "Амортизации ₽",
                    "total_return": "Итого возврат ₽",
                    "maturity_count": "Погашений",
                    "amortization_count": "Амортизаций",
                }
            )
            st.dataframe(
                ladder_display,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Погашения ₽": st.column_config.NumberColumn(format="%.2f ₽"),
                    "Амортизации ₽": st.column_config.NumberColumn(format="%.2f ₽"),
                    "Итого возврат ₽": st.column_config.NumberColumn(format="%.2f ₽"),
                    "Погашений": st.column_config.NumberColumn(format="%d"),
                    "Амортизаций": st.column_config.NumberColumn(format="%d"),
                },
            )

        # Амортизации
        if amortizations:
            amort_df = pd.DataFrame([dict(a) for a in amortizations])
            amort_df["amort_date"] = pd.to_datetime(amort_df["amort_date"])
            future_amort = amort_df[amort_df["amort_date"] >= today_mat].sort_values("amort_date")

            if not future_amort.empty:
                with st.expander(f"📉 Предстоящие амортизации ({len(future_amort)})"):
                    display_amort = future_amort[["amort_date", "name", "value_prc", "amort_value", "qty"]].copy()
                    display_amort["amort_date"] = display_amort["amort_date"].dt.strftime("%d.%m.%Y")
                    display_amort.columns = ["Дата", "Облигация", "% от номинала", "Сумма ₽", "Кол-во"]
                    st.dataframe(display_amort, hide_index=True, use_container_width=True,
                                 column_config={
                                     "% от номинала": st.column_config.NumberColumn(format="%.2f%%"),
                                     "Сумма ₽": st.column_config.NumberColumn(format="%.2f ₽"),
                                 })
                    st.metric("Итого амортизаций", f"{fmt(future_amort['amort_value'].sum())} ₽")
    else:
        st.info("Нажмите «Загрузить погашения с MOEX» для визуализации лестницы облигаций.")


# ─── TAB: РЕБАЛАНСИРОВКА ───
with tab_rebalance:
    st.subheader("⚖️ Ребалансировка портфеля")

    if pos_df.empty:
        st.info("Нет данных о позициях")
    else:
        # Текущее распределение
        type_agg_reb, total_portfolio_reb = build_current_allocation(pos_df, TYPE_LABELS)
        current_type_pct = {
            str(row["asset_type"]): float(row["current_pct"])
            for _, row in type_agg_reb.iterrows()
        }

        # Загрузка целевых долей из БД
        saved_targets = db.get_rebalance_targets()

        st.markdown("### Целевое распределение")
        st.caption("Укажите желаемую долю каждого типа актива. Сумма должна быть 100%.")

        preset_col1, preset_col2 = st.columns([2, 1])
        with preset_col1:
            preset_key = st.selectbox(
                "Пресет целевых долей",
                options=list(REBALANCE_TARGET_PRESETS.keys()),
                format_func=lambda key: REBALANCE_TARGET_PRESETS[key]["label"],
                key="rebalance_preset_key",
            )
        with preset_col2:
            if st.button("Применить пресет", use_container_width=True):
                preset_targets = REBALANCE_TARGET_PRESETS[preset_key]["targets"]
                for atype, value in preset_targets.items():
                    st.session_state[f"target_{atype}"] = float(value)
                st.success("Пресет применён к форме.")

        # Форма настройки целей
        target_cols = st.columns(len(TYPE_LABELS))
        new_targets = {}
        for i, (atype, label) in enumerate(TYPE_LABELS.items()):
            with target_cols[i]:
                current = type_agg_reb[type_agg_reb["asset_type"] == atype]["current_pct"].values
                current_val = current[0] if len(current) > 0 else 0
                default = saved_targets.get(atype, REBALANCE_DEFAULT_TARGETS.get(atype, 0))
                new_targets[atype] = st.number_input(
                    f"{label}",
                    value=default,
                    step=1.0,
                    min_value=0.0,
                    max_value=100.0,
                    key=f"target_{atype}",
                    help=f"Текущая доля: {current_val:.1f}%",
                )

        total_target = sum(new_targets.values())

        col_save, col_info = st.columns([1, 3])
        with col_save:
            if st.button("💾 Сохранить цели", type="primary", use_container_width=True):
                if abs(total_target - 100) < 0.1:
                    db.set_rebalance_targets(new_targets)
                    st.success("✅ Целевые доли сохранены")
                    st.rerun()
                else:
                    st.error(f"Сумма долей: {total_target:.1f}% (должна быть 100%)")
        with col_info:
            if abs(total_target - 100) > 0.1:
                st.warning(f"⚠️ Сумма целевых долей: **{total_target:.1f}%** — нужно ровно 100%")
            else:
                st.success(f"✓ Сумма долей: {total_target:.1f}%")

        st.divider()

        # ─── Сравнение текущего vs целевого ───
        st.markdown("### Текущее vs Целевое")

        comp_df = build_rebalance_comparison(
            type_agg=type_agg_reb,
            new_targets=new_targets,
            type_labels=TYPE_LABELS,
            total_portfolio=total_portfolio_reb,
        )

        # Визуализация
        fig_comp = go.Figure()
        fig_comp.add_trace(go.Bar(
            name="Текущая %",
            x=comp_df["Тип"],
            y=comp_df["Текущая %"],
            marker_color=[TYPE_COLORS.get(t, "#64748b") for t in comp_df["asset_type"]],
            text=comp_df["Текущая %"].apply(lambda v: f"{v:.1f}%"),
            textposition="outside",
        ))
        fig_comp.add_trace(go.Scatter(
            name="Целевая %",
            x=comp_df["Тип"],
            y=comp_df["Целевая %"],
            mode="markers+lines",
            marker=dict(color="#ef4444", size=12, symbol="diamond"),
            line=dict(color="#ef4444", width=2, dash="dash"),
        ))
        fig_comp.update_layout(
            barmode="group",
            height=350,
            margin=dict(t=30, b=40),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=1.1),
            yaxis_title="%",
        )
        st.plotly_chart(fig_comp, use_container_width=True)

        # Таблица отклонений
        display_comp = comp_df[["Тип", "Текущая ₽", "Текущая %", "Целевая %", "Целевая ₽", "Отклонение ₽", "Отклонение %"]].copy()
        st.dataframe(
            display_comp,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Текущая ₽": st.column_config.NumberColumn(format="%.0f ₽"),
                "Текущая %": st.column_config.NumberColumn(format="%.1f%%"),
                "Целевая %": st.column_config.NumberColumn(format="%.1f%%"),
                "Целевая ₽": st.column_config.NumberColumn(format="%.0f ₽"),
                "Отклонение ₽": st.column_config.NumberColumn(format="%+.0f ₽"),
                "Отклонение %": st.column_config.NumberColumn(format="%+.1f%%"),
            },
        )

        st.divider()

        # ─── Рекомендации ───
        st.markdown("### 📋 Рекомендации по ребалансировке")

        overweight, underweight = split_rebalance_gaps(comp_df, tolerance_rub=100.0)

        if overweight.empty and underweight.empty:
            st.success("✅ Портфель сбалансирован! Все отклонения в пределах допуска (±100 ₽).")
        else:
            rec_col1, rec_col2 = st.columns(2)
            with rec_col1:
                if not overweight.empty:
                    st.markdown("#### 🔴 Продать (перевес)")
                    for _, row in overweight.iterrows():
                        st.markdown(
                            f"**{row['Тип']}**: избыток **{fmt(abs(row['Отклонение ₽']))} ₽** "
                            f"({row['Текущая %']:.1f}% → {row['Целевая %']:.1f}%)"
                        )
            with rec_col2:
                if not underweight.empty:
                    st.markdown("#### 🟢 Купить (недовес)")
                    for _, row in underweight.iterrows():
                        st.markdown(
                            f"**{row['Тип']}**: докупить на **{fmt(abs(row['Отклонение ₽']))} ₽** "
                            f"({row['Текущая %']:.1f}% → {row['Целевая %']:.1f}%)"
                        )

        st.divider()
        st.markdown("### 🧭 Сценарий: что докупить (rule-based)")
        st.caption(
            "Список ниже — это только варианты «можно рассмотреть», а не инвестиционная рекомендация. "
            "Автоматические покупки не выполняются."
        )

        sc_col1, sc_col2, sc_col3 = st.columns(3)
        with sc_col1:
            scenario_free_cash = st.number_input(
                "Свободная сумма, ₽",
                min_value=0.0,
                value=50_000.0,
                step=1_000.0,
                key="buy_scenario_free_cash",
            )
            scenario_min_ytm = st.number_input(
                "Минимальная YTM, %",
                min_value=0.0,
                max_value=50.0,
                value=12.0,
                step=0.1,
                key="buy_scenario_min_ytm",
            )
        with sc_col2:
            scenario_max_issuer_share = st.number_input(
                "Макс доля эмитента, %",
                min_value=1.0,
                max_value=100.0,
                value=10.0,
                step=0.5,
                key="buy_scenario_max_issuer_share",
            )
            scenario_max_years_to_maturity = st.number_input(
                "Макс срок до погашения, лет",
                min_value=0.5,
                max_value=50.0,
                value=7.0,
                step=0.5,
                key="buy_scenario_max_years_to_maturity",
            )
        with sc_col3:
            scenario_max_position_share = st.number_input(
                "Макс доля позиции, %",
                min_value=1.0,
                max_value=100.0,
                value=10.0,
                step=0.5,
                key="buy_scenario_max_position_share",
            )
            scenario_exclude_without_ytm = st.checkbox(
                "Исключать бумаги без YTM",
                value=True,
                key="buy_scenario_exclude_without_ytm",
            )
            scenario_exclude_without_maturity = st.checkbox(
                "Исключать бумаги без даты погашения",
                value=True,
                key="buy_scenario_exclude_without_maturity",
            )

        buy_scenario = build_buy_candidates(
            positions=pos_list,
            free_cash=float(scenario_free_cash),
            issuer_by_isin=issuer_by_isin,
            ytm_by_isin=ytm_by_isin,
            maturity_by_isin=maturity_by_isin,
            position_share_map=position_share_map,
            issuer_share_map=issuer_share_map,
            current_type_pct=current_type_pct,
            target_type_pct={k: float(v) for k, v in new_targets.items()},
            total_portfolio_value=float(concentration_metrics.get("total_portfolio_value") or 0.0),
            max_issuer_share=float(scenario_max_issuer_share) / 100.0,
            max_position_share=float(scenario_max_position_share) / 100.0,
            min_ytm=float(scenario_min_ytm),
            max_years_to_maturity=float(scenario_max_years_to_maturity),
            exclude_without_ytm=bool(scenario_exclude_without_ytm),
            exclude_without_maturity=bool(scenario_exclude_without_maturity),
            bond_asset_types=BOND_ASSET_TYPES,
            warning_share_threshold=ATTENTION_CONCENTRATION_THRESHOLD,
            data_quality_issue_isins=data_quality_issue_isins,
            as_of_date=date.today(),
            max_candidates=10,
        )

        scenario_candidates = buy_scenario.get("candidates", [])
        if scenario_candidates:
            candidates_df = pd.DataFrame(scenario_candidates).copy()
            candidates_df["Тип"] = candidates_df["asset_type"].map(TYPE_LABELS).fillna(candidates_df["asset_type"])
            candidates_df["YTM"] = candidates_df["ytm"].apply(
                lambda value: f"{value:.2f}%" if value is not None else "нет данных"
            )
            candidates_df["Лет до погашения"] = candidates_df["years_to_maturity"].apply(
                lambda value: f"{value:.2f}" if value is not None else "нет данных"
            )
            candidates_df["Доля позиции %"] = candidates_df["position_share"].apply(
                lambda value: value * 100 if value is not None else None
            )
            candidates_df["Доля эмитента %"] = candidates_df["issuer_share"].apply(
                lambda value: value * 100 if value is not None else None
            )
            candidates_df["После покупки: доля позиции %"] = candidates_df["projected_position_share"].apply(
                lambda value: value * 100 if value is not None else None
            )
            candidates_df["После покупки: доля эмитента %"] = candidates_df["projected_issuer_share"].apply(
                lambda value: value * 100 if value is not None else None
            )
            candidates_df["Отклонение от цели, п.п."] = candidates_df["target_gap_pct"]
            candidates_df["Ориентир суммы, ₽"] = candidates_df["suggested_amount"]
            candidates_df["Предупреждения"] = candidates_df["warnings"].apply(
                lambda items: "нет" if not items else "; ".join(items)
            )
            candidates_df = candidates_df.rename(
                columns={
                    "name": "Инструмент",
                    "isin": "ISIN",
                    "issuer": "Эмитент",
                    "explanation": "Обоснование",
                }
            )

            st.dataframe(
                candidates_df[
                    [
                        "Инструмент",
                        "ISIN",
                        "Тип",
                        "Эмитент",
                        "YTM",
                        "Лет до погашения",
                        "Доля позиции %",
                        "Доля эмитента %",
                        "После покупки: доля позиции %",
                        "После покупки: доля эмитента %",
                        "Отклонение от цели, п.п.",
                        "Ориентир суммы, ₽",
                        "Предупреждения",
                        "Обоснование",
                    ]
                ],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Доля позиции %": st.column_config.NumberColumn(format="%.2f%%"),
                    "Доля эмитента %": st.column_config.NumberColumn(format="%.2f%%"),
                    "После покупки: доля позиции %": st.column_config.NumberColumn(format="%.2f%%"),
                    "После покупки: доля эмитента %": st.column_config.NumberColumn(format="%.2f%%"),
                    "Отклонение от цели, п.п.": st.column_config.NumberColumn(format="%+.2f"),
                    "Ориентир суммы, ₽": st.column_config.NumberColumn(format="%.2f ₽"),
                },
            )
        else:
            st.warning("По заданным ограничениям кандидаты не найдены.")

        excluded_summary = buy_scenario.get("excluded_summary", [])
        if excluded_summary:
            summary_df = pd.DataFrame(excluded_summary).copy()
            summary_df["Причина"] = summary_df["reason_code"].apply(get_exclusion_reason_label)
            summary_df = summary_df.rename(columns={"count": "Количество"})
            st.caption("Почему бумаги были исключены из сценария:")
            st.dataframe(
                summary_df[["Причина", "Количество"]],
                hide_index=True,
                use_container_width=True,
                column_config={"Количество": st.column_config.NumberColumn(format="%d")},
            )

        st.divider()
        st.markdown("### 🔻 Сценарий: что снизить (risk score)")
        st.caption(
            "Risk score использует прозрачные правила и нужен только для приоритизации проверки позиций. "
            "Это не обещание результата и не автоматическое действие."
        )

        rs_col1, rs_col2, rs_col3 = st.columns(3)
        with rs_col1:
            reduce_position_share_ref = st.number_input(
                "Ориентир доли позиции, %",
                min_value=1.0,
                max_value=100.0,
                value=10.0,
                step=0.5,
                key="reduce_position_share_ref",
            )
            reduce_issuer_share_ref = st.number_input(
                "Ориентир доли эмитента, %",
                min_value=1.0,
                max_value=100.0,
                value=10.0,
                step=0.5,
                key="reduce_issuer_share_ref",
            )
        with rs_col2:
            reduce_long_maturity_years = st.number_input(
                "Порог длинного срока, лет",
                min_value=1.0,
                max_value=50.0,
                value=7.0,
                step=0.5,
                key="reduce_long_maturity_years",
            )
            reduce_low_ytm_base = st.number_input(
                "Базовый порог YTM, %",
                min_value=0.0,
                max_value=30.0,
                value=6.0,
                step=0.1,
                key="reduce_low_ytm_base",
            )
        with rs_col3:
            reduce_low_ytm_slope = st.number_input(
                "Надбавка YTM за каждый год срока, %",
                min_value=0.0,
                max_value=5.0,
                value=0.5,
                step=0.1,
                key="reduce_low_ytm_slope",
            )

        st.caption("Факторы score (можно отключить):")
        factor_toggle_cols = st.columns(4)
        factor_enabled = {}
        for idx, (factor_code, factor_label) in enumerate(REDUCE_FACTOR_LABELS.items()):
            with factor_toggle_cols[idx % 4]:
                factor_enabled[factor_code] = st.checkbox(
                    factor_label,
                    value=True,
                    key=f"reduce_factor_{factor_code}",
                )

        reduce_scenario = build_reduce_candidates(
            positions=pos_list,
            issuer_by_isin=issuer_by_isin,
            ytm_by_isin=ytm_by_isin,
            maturity_by_isin=maturity_by_isin,
            rating_by_isin=rating_by_isin,
            position_share_map=position_share_map,
            issuer_share_map=issuer_share_map,
            data_quality_issue_isins=data_quality_issue_isins,
            bond_asset_types=BOND_ASSET_TYPES,
            factor_enabled=factor_enabled,
            position_share_reference=float(reduce_position_share_ref) / 100.0,
            issuer_share_reference=float(reduce_issuer_share_ref) / 100.0,
            long_maturity_years=float(reduce_long_maturity_years),
            low_ytm_base=float(reduce_low_ytm_base),
            low_ytm_year_slope=float(reduce_low_ytm_slope),
            as_of_date=date.today(),
            max_candidates=15,
        )

        reduce_candidates = reduce_scenario.get("candidates", [])
        if reduce_candidates:
            reduce_df = pd.DataFrame(reduce_candidates).copy()
            reduce_df["Тип"] = reduce_df["asset_type"].map(TYPE_LABELS).fillna(reduce_df["asset_type"])
            reduce_df["YTM"] = reduce_df["ytm"].apply(
                lambda value: f"{value:.2f}%" if value is not None else "нет данных"
            )
            reduce_df["Лет до погашения"] = reduce_df["years_to_maturity"].apply(
                lambda value: f"{value:.2f}" if value is not None else "нет данных"
            )
            reduce_df["Доля позиции %"] = reduce_df["position_share"].apply(
                lambda value: value * 100 if value is not None else None
            )
            reduce_df["Доля эмитента %"] = reduce_df["issuer_share"].apply(
                lambda value: value * 100 if value is not None else None
            )
            reduce_df["Рейтинг"] = reduce_df["rating"].apply(lambda value: value if value else "без рейтинга")
            reduce_df["Risk score"] = reduce_df["risk_score"]
            reduce_df["Вклад факторов"] = reduce_df["factors"].apply(
                lambda factors: "; ".join(
                    f"{item['label']} ({float(item['points']):.1f})"
                    for item in factors[:4]
                )
            )
            reduce_df = reduce_df.rename(
                columns={
                    "name": "Инструмент",
                    "isin": "ISIN",
                    "issuer": "Эмитент",
                    "severity": "Severity",
                    "reason": "Причины",
                    "suggested_action": "Что сделать",
                }
            )

            st.dataframe(
                reduce_df[
                    [
                        "Инструмент",
                        "ISIN",
                        "Тип",
                        "Эмитент",
                        "Risk score",
                        "Severity",
                        "Доля позиции %",
                        "Доля эмитента %",
                        "YTM",
                        "Лет до погашения",
                        "Рейтинг",
                        "Вклад факторов",
                        "Причины",
                        "Что сделать",
                    ]
                ],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Risk score": st.column_config.NumberColumn(format="%.2f"),
                    "Доля позиции %": st.column_config.NumberColumn(format="%.2f%%"),
                    "Доля эмитента %": st.column_config.NumberColumn(format="%.2f%%"),
                },
            )
        else:
            st.info(
                "Кандидаты на сокращение не найдены по активным факторам. "
                "Измените параметры или включите дополнительные факторы."
            )

        # Конкретные позиции для ребалансировки (по самым крупным отклонениям)
        if not underweight.empty:
            st.divider()
            st.markdown("### 🎯 Куда направить следующее пополнение?")

            biggest_gap = underweight.iloc[0]
            amount_needed = abs(biggest_gap["Отклонение ₽"])

            st.markdown(f"""
            <div class="iis-reminder" style="border-color: #10b981;">
                <b>💡 Приоритет:</b> направить пополнение в <b>{biggest_gap['Тип']}</b>
                (недовес {fmt(amount_needed)} ₽). Это поможет приблизить портфель к целевой структуре
                без необходимости продажи других позиций.
            </div>
            """, unsafe_allow_html=True)


# ─── TAB: СДЕЛКИ ───
with tab_trades:
    st.subheader("🔄 Сделки за период")

    if trades:
        trades_df = pd.DataFrame([dict(t) for t in trades])
        display_t = trades_df[[
            "trade_date", "name", "ticker", "side", "qty", "price", "amount",
            "broker_fee", "exchange_fee", "status"
        ]].copy()
        display_t.columns = [
            "Дата", "Инструмент", "Тикер", "Тип", "Кол-во",
            "Цена", "Сумма", "Ком. брокера", "Ком. биржи", "Статус"
        ]
        st.dataframe(
            display_t,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Цена": st.column_config.NumberColumn(format="%.2f ₽"),
                "Сумма": st.column_config.NumberColumn(format="%.2f ₽"),
                "Ком. брокера": st.column_config.NumberColumn(format="%.2f ₽"),
                "Ком. биржи": st.column_config.NumberColumn(format="%.2f ₽"),
            },
        )

        # Статистика сделок
        trades_stats = calculate_trades_stats(trades_df)
        st.divider()
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Сделок", trades_stats["count"])
        with c2:
            st.metric("Оборот", f"{fmt(trades_stats['total_amount'])} ₽")
        with c3:
            st.metric("Комиссии", f"{fmt(trades_stats['total_fees'])} ₽")
    else:
        st.info("Нет сделок за выбранный период")

    # Все сделки
    all_trades = db.get_trades()
    if all_trades and len(all_trades) > len(trades or []):
        with st.expander(f"📜 Все сделки ({len(all_trades)})"):
            all_t_df = pd.DataFrame([dict(t) for t in all_trades])
            st.dataframe(
                all_t_df[["trade_date", "name", "ticker", "side", "qty", "price", "amount"]].rename(
                    columns={
                        "trade_date": "Дата", "name": "Инструмент", "ticker": "Тикер",
                        "side": "Тип", "qty": "Кол-во", "price": "Цена", "amount": "Сумма",
                    }
                ),
                hide_index=True,
                use_container_width=True,
            )


# ─── TAB: FIRE ───
with tab_fire:
    st.subheader("🔥 FIRE-трекер")
    broker_portfolio = float(selected_report["total_end"] or 0.0)
    external_assets_total = float(db.get_fire_assets_total() or 0.0)
    default_current_capital = broker_portfolio + external_assets_total

    if "fire_official_inflation_pct" not in st.session_state:
        st.session_state["fire_official_inflation_pct"] = 7.0
    if "fire_personal_inflation_pct" not in st.session_state:
        st.session_state["fire_personal_inflation_pct"] = st.session_state["fire_official_inflation_pct"] + 2.0

    pcol1, pcol2, pcol3 = st.columns(3)
    with pcol1:
        current_capital_input = st.number_input(
            "Текущий капитал, ₽",
            value=float(default_current_capital),
            step=10_000.0,
            min_value=0.0,
            help="Автоподстановка: брокерский портфель + внешние активы FIRE.",
        )
        monthly_contribution = st.number_input(
            "Ежемесячное пополнение, ₽",
            value=20_000.0,
            step=1_000.0,
            min_value=0.0,
        )
    with pcol2:
        monthly_target_expense = st.number_input(
            "Целевые траты, ₽/мес",
            value=80_000.0,
            step=5_000.0,
            min_value=0.0,
        )
        horizon_years = int(
            st.number_input("Горизонт, лет", value=30, min_value=1, max_value=80, step=1)
        )
    with pcol3:
        official_inflation_pct = st.number_input(
            "Официальная инфляция, %",
            key="fire_official_inflation_pct",
            step=0.1,
            min_value=0.0,
            max_value=25.0,
        )
        personal_inflation_pct = st.number_input(
            "Личная инфляция, %",
            key="fire_personal_inflation_pct",
            step=0.1,
            min_value=0.0,
            max_value=30.0,
            help=(
                "На горизонте 25 лет разница между 6% и 8% инфляции — кратная разница "
                "в целевом капитале. Услуги и продукты растут быстрее средней корзины Росстата."
            ),
        )

    swr_col1, swr_col2 = st.columns(2)
    with swr_col1:
        swr_target_pct = st.number_input(
            "SWR target, %",
            value=3.0,
            step=0.1,
            min_value=1.0,
            max_value=10.0,
        )
    with swr_col2:
        swr_withdrawal_pct = st.number_input(
            "SWR withdrawal, %",
            value=3.5,
            step=0.1,
            min_value=1.0,
            max_value=10.0,
        )

    st.caption(
        f"Портфель брокера: {fmt(broker_portfolio)} ₽ · внешние активы: {fmt(external_assets_total)} ₽."
    )

    with st.expander("Параметры сценариев", expanded=False):
        scenario_columns = st.columns(3)
        scenario_input_presets = {}
        for idx, scenario_key in enumerate(["base", "stagflation", "optimistic"]):
            preset = FIRE_SCENARIO_PRESETS[scenario_key]
            with scenario_columns[idx]:
                st.markdown(f"**{preset['label']}**")
                default_inflation = preset["inflation_rate"] * 100
                if scenario_key == "base":
                    default_inflation = float(personal_inflation_pct)
                inflation_pct = st.number_input(
                    "Личная инфляция, %",
                    value=float(default_inflation),
                    step=0.1,
                    min_value=0.0,
                    max_value=30.0,
                    key=f"fire_{scenario_key}_inflation_pct",
                )
                nominal_pct = st.number_input(
                    "Номинальная доходность, %",
                    value=float(preset["nominal_return_rate"] * 100),
                    step=0.1,
                    min_value=0.0,
                    max_value=40.0,
                    key=f"fire_{scenario_key}_nominal_pct",
                )
                delta_pp = inflation_pct - float(official_inflation_pct)
                st.caption(f"(официальная + {delta_pp:+.1f} п.п.)")

                scenario_input_presets[scenario_key] = {
                    "label": preset["label"],
                    "inflation_rate": inflation_pct / 100.0,
                    "nominal_return_rate": nominal_pct / 100.0,
                    "weight": float(preset.get("weight", 0.0)),
                }

    fire_scenarios = build_fire_scenarios(
        current_capital=float(current_capital_input),
        monthly_contribution=float(monthly_contribution),
        monthly_target_expense=float(monthly_target_expense),
        swr_target=float(swr_target_pct) / 100.0,
        swr_withdrawal=float(swr_withdrawal_pct) / 100.0,
        horizon_years=horizon_years,
        presets=scenario_input_presets,
    )

    scenario_results = fire_scenarios["scenarios"]
    scenario_presets = fire_scenarios["presets"]

    st.divider()
    result_cols = st.columns(3)
    for idx, scenario_key in enumerate(["base", "stagflation", "optimistic"]):
        scenario = scenario_results.get(scenario_key, {})
        preset = scenario_presets.get(scenario_key, {})
        years_to_target = scenario.get("years_to_fire_swr_target")
        years_to_withdrawal = scenario.get("years_to_fire_swr_withdrawal")

        with result_cols[idx]:
            st.markdown(f"### {preset.get('label', scenario_key)}")
            st.metric(
                f"Цель капитала (SWR {swr_target_pct:.1f}%)",
                f"{scenario.get('target_capital_swr_target_real', 0.0):,.0f} ₽",
            )
            st.metric(
                f"Опер. изъятие (SWR {swr_withdrawal_pct:.1f}%)",
                f"{scenario.get('target_capital_swr_withdrawal_real', 0.0):,.0f} ₽",
            )
            st.metric(
                "Годы до FIRE (SWR target)",
                "не достигается"
                if years_to_target is None
                else f"{years_to_target:.1f}",
                f"горизонт {horizon_years} лет",
            )
            st.metric(
                "Годы до FIRE (SWR withdrawal)",
                "не достигается"
                if years_to_withdrawal is None
                else f"{years_to_withdrawal:.1f}",
            )
            st.metric(
                "Реальная доходность",
                f"{(scenario.get('real_return_rate', 0.0) * 100):.2f}%",
            )

    st.divider()
    st.subheader("📈 Траектория капитала (реальные рубли)")
    fig_fire = go.Figure()
    scenario_colors = {
        "base": "#22d3ee",
        "stagflation": "#ef4444",
        "optimistic": "#10b981",
    }

    for scenario_key in ["base", "stagflation", "optimistic"]:
        scenario = scenario_results.get(scenario_key, {})
        preset = scenario_presets.get(scenario_key, {})
        trajectory = scenario.get("trajectory", [])
        if not trajectory:
            continue
        traj_df = pd.DataFrame(trajectory)
        fig_fire.add_trace(
            go.Scatter(
                x=traj_df["year"],
                y=traj_df["capital_real"],
                mode="lines",
                name=preset.get("label", scenario_key),
                line=dict(color=scenario_colors.get(scenario_key, "#94a3b8"), width=2.5),
            )
        )

    reference_scenario = scenario_results.get("base", {})
    fire_target_line = reference_scenario.get("target_capital_swr_target_real")
    if fire_target_line is not None:
        fig_fire.add_hline(
            y=fire_target_line,
            line_dash="dash",
            line_color="#f59e0b",
            annotation_text=f"Цель SWR target: {fire_target_line:,.0f} ₽",
            annotation_position="top left",
        )

    fig_fire.update_layout(
        xaxis_title="Год прогноза",
        yaxis_title="Реальный капитал, ₽",
        height=420,
        margin=dict(t=30, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.1),
        hovermode="x unified",
    )
    st.plotly_chart(fig_fire, use_container_width=True)
    st.caption(
        "Все суммы — в реальных рублях (с поправкой на инфляцию). "
        "Целевой капитал считается по SWR target; оперативное изъятие — по SWR withdrawal."
    )

    # ─── Внешние активы ───
    st.divider()
    st.subheader("🏦 Внешние активы")
    st.caption("Вклады, НПФ, наличные и другие активы за пределами брокерского счёта — учитываются в общей сумме FIRE")

    fire_assets = db.get_fire_assets()

    ASSET_CATEGORIES = {
        "deposit": "💳 Вклад",
        "npf": "🏛 НПФ",
        "cash": "💵 Наличные",
        "crypto": "🪙 Крипто",
        "property": "🏠 Недвижимость",
        "other": "📦 Другое",
    }

    if fire_assets:
        assets_df = pd.DataFrame([dict(a) for a in fire_assets])
        assets_df["Категория"] = assets_df["category"].map(ASSET_CATEGORIES)
        assets_df["updated_at"] = pd.to_datetime(assets_df["updated_at"]).dt.strftime("%d.%m.%Y")

        st.dataframe(
            assets_df[["name", "Категория", "value", "rate", "notes", "updated_at"]].rename(columns={
                "name": "Название",
                "value": "Сумма ₽",
                "rate": "Ставка %",
                "notes": "Заметки",
                "updated_at": "Обновлено",
            }),
            hide_index=True,
            use_container_width=True,
            column_config={
                "Сумма ₽": st.column_config.NumberColumn(format="%.2f ₽"),
                "Ставка %": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )

        # Итого по категориям
        cat_totals = assets_df.groupby("Категория")["value"].sum().sort_values(ascending=False)
        cols_cat = st.columns(min(len(cat_totals), 4))
        for i, (cat, total) in enumerate(cat_totals.items()):
            with cols_cat[i % len(cols_cat)]:
                st.metric(cat, f"{fmt(total)} ₽")

        # Удаление
        with st.expander("🗑 Удалить актив"):
            asset_to_delete = st.selectbox(
                "Выберите актив",
                [(a["id"], a["name"], a["value"]) for a in fire_assets],
                format_func=lambda x: f"{x[1]} ({fmt(x[2])} ₽)",
            )
            if st.button("Удалить", type="secondary"):
                db.delete_fire_asset(asset_to_delete[0])
                st.success(f"Удалён: {asset_to_delete[1]}")
                st.rerun()
    else:
        st.info("Добавьте внешние активы чтобы учесть их в FIRE-расчёте")

    # Форма добавления
    with st.expander("➕ Добавить актив"):
        acol1, acol2 = st.columns(2)
        with acol1:
            a_name = st.text_input("Название", placeholder="Вклад Сбер Лучший %")
            a_category = st.selectbox("Категория", list(ASSET_CATEGORIES.keys()),
                                       format_func=lambda x: ASSET_CATEGORIES[x])
            a_value = st.number_input("Сумма, ₽", value=0.0, step=1000.0, min_value=0.0)
        with acol2:
            a_rate = st.number_input("Ставка / доходность, %", value=0.0, step=0.1)
            a_notes = st.text_input("Заметки", placeholder="до 31.12.2026, автопрод.")

        if st.button("💾 Сохранить актив", type="primary"):
            if a_name and a_value > 0:
                db.upsert_fire_asset(
                    name=a_name,
                    category=a_category,
                    value=a_value,
                    rate=a_rate,
                    notes=a_notes,
                )
                st.success(f"✅ Сохранено: {a_name} — {fmt(a_value)} ₽")
                st.rerun()
            else:
                st.warning("Укажите название и сумму")


# ─── Футер ───
st.divider()
st.caption(f"Последнее обновление: {latest['report_date']} · Отчётов в базе: {len(all_reports)}")
