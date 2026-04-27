"""
📊 Портфель ИИС-3 — Streamlit Dashboard
Запуск: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
from pathlib import Path

from analytics.bonds import calculate_weighted_ytm, calculate_weighted_years_to_maturity
from analytics.cashflows import build_coupon_cashflow_by_month, build_maturity_ladder
from analytics.data_quality import build_attention_list, build_bond_data_quality_report
import concentration
import db
import moex_api
import parser as bp
from report_export import build_portfolio_summary_html
from fire_metrics import (
    build_contribution_series,
    build_fire_projection,
    build_glide_path,
    calculate_fire_basics,
    calculate_fire_window_stats,
    calculate_percentile_bands,
    calculate_security_mix,
    get_age_based_target_stocks,
    simulate_fire_monte_carlo,
)
from formatters import format_rub
from portfolio_metrics import (
    build_asset_type_aggregation,
    calculate_overview_returns,
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

BOND_ASSET_TYPES = concentration.BOND_ASSET_TYPES
PREMIUM_FILTER_OPTIONS = {
    "all": "Все",
    "premium": "Выше номинала",
    "discount": "Ниже номинала",
    "near par": "Около номинала",
}
ATTENTION_NEAR_MATURITY_DAYS = 90
ATTENTION_LOSS_PCT_THRESHOLD = -10.0
ATTENTION_LONG_MATURITY_YEARS = 7.0
ATTENTION_CONCENTRATION_THRESHOLD = 0.10


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
            elif report_id == -1:
                st.info(f"ℹ️ Отчёт за {report.period_end} уже загружен")
        except Exception as e:
            st.error(f"Ошибка парсинга: {e}")

    st.divider()

    # Список отчётов
    all_reports = db.get_all_reports()
    if all_reports:
        st.subheader(f"📋 Отчёты ({len(all_reports)})")
        report_dates = [r["period_end"] for r in all_reports]
        selected_date = st.selectbox(
            "Выберите дату отчёта",
            report_dates,
            index=0,
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
for r in all_reports:
    if r["period_end"] == selected_date:
        selected_report = r
        break

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
)
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

position_share_map = {}
for row in concentration_metrics["positions"]:
    key = row.get("isin") or row.get("name")
    if key:
        position_share_map[key] = row.get("position_share")

issuer_share_map = {
    row["issuer"]: row.get("issuer_share")
    for row in concentration_metrics["issuers"]
}
attention_list = build_attention_list(
    positions=pos_list,
    position_share_map=position_share_map,
    issuer_share_map=issuer_share_map,
    issuer_map=issuer_by_isin,
    ytm_map=ytm_by_isin,
    maturity_by_isin=maturity_by_isin,
    coupons=[dict(row) for row in coupon_calendar],
    cost_basis=cost_basis_all,
    as_of_date=date.today(),
    near_maturity_days_threshold=ATTENTION_NEAR_MATURITY_DAYS,
    loss_pct_threshold=ATTENTION_LOSS_PCT_THRESHOLD,
    long_maturity_years_threshold=ATTENTION_LONG_MATURITY_YEARS,
    concentration_threshold=ATTENTION_CONCENTRATION_THRESHOLD,
    bond_asset_types=BOND_ASSET_TYPES,
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
    st.subheader("🚨 Бумаги, требующие внимания")
    if attention_list:
        attention_df = pd.DataFrame(attention_list).copy()
        attention_df["position_share"] = attention_df["position_share"].apply(
            lambda v: v * 100 if v is not None else None
        )
        attention_df["issuer_share"] = attention_df["issuer_share"].apply(
            lambda v: v * 100 if v is not None else None
        )
        attention_df["pnl_pct"] = attention_df["pnl_pct"].apply(
            lambda v: f"{v:.1f}%" if v is not None else "нет данных"
        )
        attention_df["days_to_maturity"] = attention_df["days_to_maturity"].apply(
            lambda v: int(v) if pd.notna(v) else "нет данных"
        )
        attention_df = attention_df.rename(
            columns={
                "name": "Инструмент",
                "isin": "ISIN",
                "severity": "Severity",
                "reason": "Причины",
                "suggested_action": "Рекомендуемое действие",
                "position_share": "Доля позиции %",
                "issuer_share": "Доля эмитента %",
                "market_value": "Полная стоимость ₽",
                "pnl_pct": "P&L %",
                "days_to_maturity": "Дней до погашения",
            }
        )
        st.caption(
            f"Пороги: доля > {ATTENTION_CONCENTRATION_THRESHOLD * 100:.0f}%, "
            f"погашение ≤ {ATTENTION_NEAR_MATURITY_DAYS} дней, "
            f"убыток ≤ {ATTENTION_LOSS_PCT_THRESHOLD:.1f}%, "
            f"срок > {ATTENTION_LONG_MATURITY_YEARS:.1f} лет."
        )
        st.dataframe(
            attention_df[[
                "Инструмент", "ISIN", "Severity", "Причины", "Рекомендуемое действие",
                "Доля позиции %", "Доля эмитента %", "P&L %",
                "Дней до погашения", "Полная стоимость ₽"
            ]],
            hide_index=True,
            use_container_width=True,
            column_config={
                "Доля позиции %": st.column_config.NumberColumn(format="%.2f%%"),
                "Доля эмитента %": st.column_config.NumberColumn(format="%.2f%%"),
                "Полная стоимость ₽": st.column_config.NumberColumn(format="%.2f ₽"),
            },
        )
    else:
        st.info("По текущим критериям бумаги, требующие внимания, не обнаружены.")

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

    fallback_count = concentration_metrics.get("issuer_fallback_count", 0)
    if fallback_count:
        st.caption(
            f"Для {fallback_count} облигаций эмитент недоступен в API, использована временная fallback-группировка по названию выпуска."
        )
    st.caption(format_sync_freshness_caption("Эмитенты (MOEX)", db.get_data_sync_freshness("issuer")))

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
    history = db.get_portfolio_history()
    returns_summary = calculate_overview_returns(history, db.get_all_deposits())
    returns_data = returns_summary["returns_data"]
    if returns_data:
        latest_val = returns_summary["latest_val"]
        total_deposited_all = returns_summary["total_deposited_all"]
        net_profit = returns_summary["net_profit"]
        net_pct = returns_summary["net_pct"]
        if latest_val is not None:
            st.subheader("📈 Доходность портфеля")
            cols = st.columns(min(len(returns_data), 4))
            for i, (label, data) in enumerate(returns_data.items()):
                with cols[i % len(cols)]:
                    color = "normal" if data["abs"] >= 0 else "inverse"
                    pct_str = f"{data['pct']:+.2f}%" if data["pct"] is not None else "—"
                    st.metric(
                        label,
                        f"{data['abs']:+,.2f} ₽",
                        pct_str,
                        delta_color=color,
                    )

            # Абсолютная доходность (портфель минус все пополнения)
            if total_deposited_all > 0 and net_profit is not None and net_pct is not None:
                st.caption(
                    f"💼 Абсолютная P&L: **{net_profit:+,.2f} ₽** ({net_pct:+.2f}%) — "
                    f"портфель {fmt(latest_val)} ₽ минус внесено {fmt(total_deposited_all)} ₽"
                )

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

        # Загрузка целевых долей из БД
        saved_targets = db.get_rebalance_targets()

        st.markdown("### Целевое распределение")
        st.caption("Укажите желаемую долю каждого типа актива. Сумма должна быть 100%.")

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

    # ─── Параметры (настраиваемые) ───
    with st.expander("⚙️ Параметры FIRE-плана", expanded=False):
        pcol1, pcol2, pcol3 = st.columns(3)
        with pcol1:
            fire_age = st.number_input("Текущий возраст", value=25, min_value=18, max_value=65)
            fire_target_age_min = st.number_input("Целевой возраст FIRE (от)", value=40, min_value=25, max_value=70)
            fire_target_age_max = st.number_input("Целевой возраст FIRE (до)", value=44, min_value=25, max_value=70)
            fire_life_expectancy = st.number_input("Горизонт планирования (до возраста)", value=85, min_value=50, max_value=100)
        with pcol2:
            fire_monthly_expenses = st.number_input("Целевые расходы, ₽/мес", value=80_000, step=5_000)
            fire_withdrawal_rate = st.number_input("Ставка изъятия, %", value=3.5, step=0.1, min_value=1.0, max_value=10.0)
            fire_inflation = st.number_input("Инфляция, %", value=6.0, step=0.5, min_value=0.0, max_value=20.0)
        with pcol3:
            fire_monthly_contrib = st.number_input("Пополнение, ₽/мес", value=20_000, step=1_000)
            fire_contrib_growth = st.number_input("Рост пополнений, %/год", value=5.0, step=1.0, min_value=0.0, max_value=30.0)
            fire_return_nominal = st.number_input("Ожид. доходность (номинал.), %", value=12.0, step=0.5, min_value=0.0, max_value=30.0)

    # Текущий портфель (брокерский) + внешние активы
    broker_portfolio = selected_report["total_end"]
    external_assets_total = db.get_fire_assets_total()
    fire_basics = calculate_fire_basics(
        fire_return_nominal=fire_return_nominal,
        fire_inflation=fire_inflation,
        fire_monthly_expenses=fire_monthly_expenses,
        fire_withdrawal_rate=fire_withdrawal_rate,
        broker_portfolio=broker_portfolio,
        external_assets_total=external_assets_total,
        fire_age=fire_age,
        fire_target_age_min=fire_target_age_min,
    )
    fire_return_real = fire_basics["fire_return_real"]
    fire_annual_expenses = fire_basics["fire_annual_expenses"]
    fire_target = fire_basics["fire_target"]
    current_portfolio = fire_basics["current_portfolio"]
    progress_pct = fire_basics["progress_pct"]
    years_to_fire = fire_basics["years_to_fire"]

    # ─── KPI ───
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if external_assets_total > 0:
            st.metric("Всего активов", f"{current_portfolio:,.0f} ₽",
                      f"брокер {fmt(broker_portfolio)} + внешние {fmt(external_assets_total)}")
        else:
            st.metric("Текущий портфель", f"{current_portfolio:,.0f} ₽")
    with c2:
        st.metric("Цель FIRE", f"{fire_target:,.0f} ₽",
                  f"{fire_monthly_expenses:,.0f} ₽/мес × 12 / {fire_withdrawal_rate}%")
    with c3:
        st.metric("Прогресс", f"{progress_pct:.1%}",
                  f"осталось {fmt(fire_target - current_portfolio)} ₽")
    with c4:
        st.metric("Лет до цели", f"{years_to_fire}",
                  f"возраст {fire_target_age_min}–{fire_target_age_max}")

    # Прогресс-бар
    st.progress(progress_pct, text=f"Накоплено {progress_pct:.1%} от цели FIRE ({fmt(current_portfolio)} из {fmt(fire_target)} ₽)")

    st.divider()

    # ─── Прогноз накоплений ───
    st.subheader("📈 Прогноз накоплений")

    proj_df, fire_reached_age = build_fire_projection(
        current_portfolio=current_portfolio,
        fire_age=fire_age,
        fire_life_expectancy=fire_life_expectancy,
        fire_monthly_contrib=fire_monthly_contrib,
        fire_contrib_growth=fire_contrib_growth,
        fire_return_nominal=fire_return_nominal,
        fire_inflation=fire_inflation,
        fire_target=fire_target,
    )

    # ─── График номинальный ───
    fig_fire = go.Figure()

    # Портфель (номинал)
    fig_fire.add_trace(go.Scatter(
        x=proj_df["Возраст"],
        y=proj_df["Портфель"],
        mode="lines",
        name="Портфель (номинал.)",
        line=dict(color="#22d3ee", width=2.5),
        fill="tozeroy",
        fillcolor="rgba(34,211,238,0.08)",
    ))

    # Портфель (реальный)
    fig_fire.add_trace(go.Scatter(
        x=proj_df["Возраст"],
        y=proj_df["Портфель (реальн.)"],
        mode="lines",
        name="Портфель (реальн.)",
        line=dict(color="#10b981", width=2.5),
        fill="tozeroy",
        fillcolor="rgba(16,185,129,0.08)",
    ))

    # Цель FIRE (реальная — горизонтальная линия)
    fig_fire.add_trace(go.Scatter(
        x=proj_df["Возраст"],
        y=proj_df["Цель FIRE (реальн.)"],
        mode="lines",
        name=f"Цель FIRE ({fmt(fire_target)} ₽)",
        line=dict(color="#ef4444", width=2, dash="dash"),
    ))

    # Зона FIRE (40-44)
    fig_fire.add_vrect(
        x0=fire_target_age_min, x1=fire_target_age_max,
        fillcolor="rgba(245,158,11,0.1)",
        line_width=0,
        annotation_text="FIRE окно",
        annotation_position="top",
    )

    # Точка текущего возраста
    fig_fire.add_vline(
        x=fire_age,
        line_dash="dot",
        line_color="#64748b",
        annotation_text="Сейчас",
        annotation_position="top",
    )

    # Точка достижения FIRE
    if fire_reached_age and fire_reached_age <= fire_life_expectancy:
        fire_row = proj_df[proj_df["Возраст"] == fire_reached_age].iloc[0]
        fig_fire.add_trace(go.Scatter(
            x=[fire_reached_age],
            y=[fire_row["Портфель (реальн.)"]],
            mode="markers+text",
            name=f"FIRE в {fire_reached_age} лет",
            marker=dict(color="#f59e0b", size=14, symbol="star"),
            text=[f"🔥 FIRE в {fire_reached_age}"],
            textposition="top center",
            textfont=dict(size=13),
        ))

    fig_fire.update_layout(
        xaxis_title="Возраст",
        yaxis_title="₽",
        height=450,
        margin=dict(t=40, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.12),
        hovermode="x unified",
    )
    st.plotly_chart(fig_fire, use_container_width=True)

    # ─── Результат прогноза ───
    st.divider()

    if fire_reached_age:
        years_until = fire_reached_age - fire_age
        fire_year = datetime.now().year + years_until
        st.markdown(f"""
        <div class="iis-reminder" style="border-color: #f59e0b; background: linear-gradient(135deg, #422006 0%, #111827 100%);">
            <h3 style="margin:0; color: #f59e0b;">🔥 FIRE достижим в {fire_reached_age} лет ({fire_year} год)</h3>
            <p style="margin: 8px 0 0; color: #e2e8f0;">
                При текущих параметрах через <b>{years_until} лет</b> реальная стоимость портфеля
                достигнет <b>{fmt(fire_target)} ₽</b> (в сегодняшних ценах),
                что обеспечит пассивный доход <b>{fmt(fire_monthly_expenses)} ₽/мес</b>
                при ставке изъятия {fire_withdrawal_rate}%.
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.error(
            f"⚠️ При текущих параметрах FIRE не достигается до {fire_life_expectancy} лет. "
            "Попробуйте увеличить пополнения или снизить целевые расходы."
        )

    # ─── Таблица по годам ───
    with st.expander("📋 Прогноз по годам (детально)"):
        detail_df = proj_df.copy()
        detail_df["Пополнения/мес"] = build_contribution_series(
            initial_monthly=fire_monthly_contrib,
            growth_pct=fire_contrib_growth,
            periods=len(detail_df),
        )

        st.dataframe(
            detail_df[["Год", "Возраст", "Портфель", "Портфель (реальн.)", "Пополнения/мес"]].rename(columns={
                "Портфель": "Портфель (номинал.) ₽",
                "Портфель (реальн.)": "Портфель (реальн.) ₽",
                "Пополнения/мес": "Взнос/мес ₽",
            }),
            hide_index=True,
            use_container_width=True,
            height=500,
            column_config={
                "Портфель (номинал.) ₽": st.column_config.NumberColumn(format="%.0f ₽"),
                "Портфель (реальн.) ₽": st.column_config.NumberColumn(format="%.0f ₽"),
                "Взнос/мес ₽": st.column_config.NumberColumn(format="%.0f ₽"),
            },
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

    # ─── Глайд-пат ───
    st.divider()
    st.subheader("⚖️ Глайд-пат (распределение активов)")

    # Текущее распределение из портфеля
    security_mix = calculate_security_mix(pos_df)
    if security_mix["total_sec"] > 0:
        bonds_value = security_mix["bonds_value"]
        stocks_value = security_mix["stocks_value"]
        etf_value = security_mix["etf_value"]
        bonds_pct = security_mix["bonds_pct"]
        stocks_pct = security_mix["stocks_pct"]

        if bonds_pct is not None and stocks_pct is not None:
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Облигации", f"{bonds_pct:.1f}%", f"{fmt(bonds_value)} ₽")
            with c2:
                st.metric("Акции + ETF", f"{stocks_pct:.1f}%", f"{fmt(stocks_value + etf_value)} ₽")
            with c3:
                target_stocks = get_age_based_target_stocks(fire_age)
                target_bonds = 100 - target_stocks
                st.metric("Целевое (акции/облиг.)",
                          f"{target_stocks}/{target_bonds}",
                          "по глайд-пату")

            # Визуализация глайд-пата
            glide_ages = list(range(25, 71))
            glide_stocks, glide_bonds = build_glide_path(glide_ages)

            fig_glide = go.Figure()
            fig_glide.add_trace(go.Scatter(
                x=glide_ages, y=glide_stocks,
                mode="lines",
                name="Акции %",
                line=dict(color="#10b981", width=2),
                fill="tozeroy",
                fillcolor="rgba(16,185,129,0.15)",
                stackgroup="one",
            ))
            fig_glide.add_trace(go.Scatter(
                x=glide_ages, y=glide_bonds,
                mode="lines",
                name="Облигации %",
                line=dict(color="#a78bfa", width=2),
                fill="tonexty",
                fillcolor="rgba(167,139,250,0.15)",
                stackgroup="one",
            ))

            # Текущий возраст
            fig_glide.add_vline(
                x=fire_age, line_dash="dot", line_color="#f59e0b",
                annotation_text=f"Сейчас ({fire_age})",
            )

            fig_glide.update_layout(
                xaxis_title="Возраст",
                yaxis_title="%",
                yaxis_range=[0, 100],
                height=300,
                margin=dict(t=20, b=40),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                legend=dict(orientation="h", y=1.1),
            )
            st.plotly_chart(fig_glide, use_container_width=True)

    # ─── Стресс-тест FIRE (Monte Carlo) ───
    st.divider()
    st.subheader("🎲 Стресс-тест FIRE (Monte Carlo)")
    st.caption(
        "Симуляция случайных сценариев доходности портфеля. "
        "Вместо фиксированной доходности — разброс от кризисных до бычьих лет."
    )

    with st.expander("⚙️ Параметры симуляции", expanded=False):
        mc_col1, mc_col2 = st.columns(2)
        with mc_col1:
            mc_simulations = st.number_input(
                "Количество сценариев", value=500, min_value=50, max_value=5000, step=50,
                help="Больше = точнее, но медленнее"
            )
            mc_volatility = st.number_input(
                "Волатильность (σ), %", value=15.0, step=1.0, min_value=1.0, max_value=50.0,
                help="Стандартное отклонение годовой доходности. РФ рынок ~15–25%"
            )
        with mc_col2:
            mc_crash_prob = st.number_input(
                "Вероятность кризиса, %/год", value=5.0, step=1.0, min_value=0.0, max_value=30.0,
                help="Шанс просадки -30...-50% в отдельный год"
            )
            mc_crash_severity = st.number_input(
                "Глубина кризиса, %", value=-40.0, step=5.0, min_value=-80.0, max_value=-10.0,
                help="Средняя просадка в кризисный год"
            )

    if st.button("🚀 Запустить симуляцию", type="primary"):
        progress_bar = st.progress(0, text="Симуляция...")
        mc_result = simulate_fire_monte_carlo(
            current_portfolio=current_portfolio,
            fire_age=fire_age,
            fire_target_age_max=fire_target_age_max,
            fire_monthly_contrib=fire_monthly_contrib,
            fire_contrib_growth=fire_contrib_growth,
            fire_return_nominal=fire_return_nominal,
            fire_inflation=fire_inflation,
            fire_target=fire_target,
            mc_simulations=int(mc_simulations),
            mc_volatility=mc_volatility,
            mc_crash_prob=mc_crash_prob,
            mc_crash_severity=mc_crash_severity,
            random_seed=42,
        )
        years_sim = mc_result["years_sim"]
        all_paths = mc_result["all_paths"]
        fire_ages_mc = mc_result["fire_ages_mc"]
        fire_prob = mc_result["fire_prob"]

        progress_bar.progress(1.0, text="Готово!")

        # ─── Результаты ───
        rc1, rc2, rc3, rc4 = st.columns(4)
        with rc1:
            color = "#10b981" if fire_prob >= 70 else "#f59e0b" if fire_prob >= 40 else "#ef4444"
            st.markdown(f"""
            <div style="text-align:center; padding:16px; background:#111827; border-radius:12px; border: 2px solid {color};">
                <div style="color:#64748b; font-size:12px; font-weight:600; text-transform:uppercase;">Вероятность FIRE</div>
                <div style="color:{color}; font-size:36px; font-weight:700; font-family:monospace;">{fire_prob:.0f}%</div>
                <div style="color:#64748b; font-size:11px;">до {fire_target_age_max} лет</div>
            </div>
            """, unsafe_allow_html=True)
        with rc2:
            if fire_ages_mc:
                median_age = sorted(fire_ages_mc)[len(fire_ages_mc) // 2]
                st.metric("Медианный возраст FIRE", f"{median_age} лет",
                          f"{median_age - fire_age} лет от сейчас")
            else:
                st.metric("Медианный возраст FIRE", "—", "Не достигается")
        with rc3:
            if fire_ages_mc:
                best_case = min(fire_ages_mc)
                st.metric("Лучший сценарий", f"{best_case} лет", "🟢 оптимист")
            else:
                st.metric("Лучший сценарий", "—")
        with rc4:
            if fire_ages_mc:
                worst_case = max(fire_ages_mc)
                st.metric("Худший (из успешных)", f"{worst_case} лет", "🔴 пессимист")
            else:
                st.metric("Худший сценарий", "—")

        st.divider()

        # ─── График веера сценариев ───

        ages_axis = list(range(fire_age, fire_age + years_sim + 1))

        # Считаем перцентили
        percentile_bands = calculate_percentile_bands(all_paths, years_sim + 1)
        p5 = percentile_bands["p5"]
        p25 = percentile_bands["p25"]
        p50 = percentile_bands["p50"]
        p75 = percentile_bands["p75"]
        p95 = percentile_bands["p95"]
        axis_len = min(len(ages_axis), len(p50))
        ages_axis = ages_axis[:axis_len]
        p5 = p5[:axis_len]
        p25 = p25[:axis_len]
        p50 = p50[:axis_len]
        p75 = p75[:axis_len]
        p95 = p95[:axis_len]

        fig_mc = go.Figure()

        # 5-95 перцентиль (широкий веер)
        fig_mc.add_trace(go.Scatter(
            x=ages_axis, y=p95,
            mode="lines", line=dict(width=0),
            showlegend=False,
        ))
        fig_mc.add_trace(go.Scatter(
            x=ages_axis, y=p5,
            mode="lines", line=dict(width=0),
            fill="tonexty",
            fillcolor="rgba(34,211,238,0.08)",
            name="5–95 перцентиль",
        ))

        # 25-75 перцентиль (узкий веер)
        fig_mc.add_trace(go.Scatter(
            x=ages_axis, y=p75,
            mode="lines", line=dict(width=0),
            showlegend=False,
        ))
        fig_mc.add_trace(go.Scatter(
            x=ages_axis, y=p25,
            mode="lines", line=dict(width=0),
            fill="tonexty",
            fillcolor="rgba(34,211,238,0.15)",
            name="25–75 перцентиль",
        ))

        # Медиана
        fig_mc.add_trace(go.Scatter(
            x=ages_axis, y=p50,
            mode="lines",
            name="Медиана (50%)",
            line=dict(color="#22d3ee", width=2.5),
        ))

        # Цель FIRE
        fig_mc.add_hline(
            y=fire_target,
            line_dash="dash",
            line_color="#ef4444",
            annotation_text=f"Цель: {fire_target:,.0f} ₽",
            annotation_position="top right",
        )

        # FIRE окно
        fig_mc.add_vrect(
            x0=fire_target_age_min, x1=fire_target_age_max,
            fillcolor="rgba(245,158,11,0.08)",
            line_width=0,
            annotation_text="FIRE окно",
            annotation_position="top",
        )

        fig_mc.update_layout(
            xaxis_title="Возраст",
            yaxis_title="Реальная стоимость портфеля, ₽",
            height=450,
            margin=dict(t=40, b=40),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=1.12),
            hovermode="x unified",
        )
        st.plotly_chart(fig_mc, use_container_width=True)

        # ─── Распределение возраста FIRE ───
        if fire_ages_mc:
            st.divider()
            st.subheader("📊 Распределение возраста достижения FIRE")

            fig_hist = go.Figure()
            fig_hist.add_trace(go.Histogram(
                x=fire_ages_mc,
                nbinsx=max(10, (max(fire_ages_mc) - min(fire_ages_mc))),
                marker_color="#22d3ee",
                opacity=0.8,
            ))

            # Медиана
            median_age = sorted(fire_ages_mc)[len(fire_ages_mc) // 2]
            fig_hist.add_vline(
                x=median_age, line_dash="dash", line_color="#f59e0b",
                annotation_text=f"Медиана: {median_age}",
            )

            # FIRE окно
            fig_hist.add_vrect(
                x0=fire_target_age_min, x1=fire_target_age_max,
                fillcolor="rgba(16,185,129,0.1)",
                line_width=1,
                line_color="#10b981",
                annotation_text="Целевое окно",
            )

            fig_hist.update_layout(
                xaxis_title="Возраст достижения FIRE",
                yaxis_title="Количество сценариев",
                height=300,
                margin=dict(t=30, b=40),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_hist, use_container_width=True)

            # Вероятность по окнам
            window_stats = calculate_fire_window_stats(
                fire_ages_mc=fire_ages_mc,
                fire_target_age_min=fire_target_age_min,
                fire_target_age_max=fire_target_age_max,
                mc_simulations=int(mc_simulations),
            )
            in_window = window_stats["in_window"]
            before_window = window_stats["before_window"]
            after_window = window_stats["after_window"]
            never = window_stats["never"]

            wc1, wc2, wc3, wc4 = st.columns(4)
            with wc1:
                st.metric(f"До {fire_target_age_min} лет", f"{before_window / mc_simulations * 100:.1f}%",
                          f"{before_window} сценариев")
            with wc2:
                st.metric(f"{fire_target_age_min}–{fire_target_age_max} лет", f"{in_window / mc_simulations * 100:.1f}%",
                          f"{in_window} сценариев")
            with wc3:
                st.metric(f"После {fire_target_age_max} лет", f"{after_window / mc_simulations * 100:.1f}%",
                          f"{after_window} сценариев")
            with wc4:
                st.metric("Не достигается", f"{never / mc_simulations * 100:.1f}%",
                          f"{int(never)} сценариев")


# ─── Футер ───
st.divider()
st.caption(f"Последнее обновление: {latest['report_date']} · Отчётов в базе: {len(all_reports)}")
