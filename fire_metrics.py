"""Чистые расчёты для FIRE-вкладки."""

from __future__ import annotations

import random
from typing import Any, Mapping, Sequence

import pandas as pd


def calculate_fire_basics(
    fire_return_nominal: float,
    fire_inflation: float,
    fire_monthly_expenses: float,
    fire_withdrawal_rate: float,
    broker_portfolio: float,
    external_assets_total: float,
    fire_age: int,
    fire_target_age_min: int,
) -> dict:
    """Базовые FIRE-метрики."""
    fire_return_real = (1 + fire_return_nominal / 100) / (1 + fire_inflation / 100) - 1
    fire_annual_expenses = fire_monthly_expenses * 12
    fire_target = fire_annual_expenses / (fire_withdrawal_rate / 100)
    current_portfolio = broker_portfolio + external_assets_total
    progress_pct = min(current_portfolio / fire_target, 1.0) if fire_target > 0 else 0.0
    years_to_fire = fire_target_age_min - fire_age

    return {
        "fire_return_real": fire_return_real,
        "fire_annual_expenses": fire_annual_expenses,
        "fire_target": fire_target,
        "current_portfolio": current_portfolio,
        "progress_pct": progress_pct,
        "years_to_fire": years_to_fire,
    }


SCENARIO_PRESETS = {
    "base": {
        "label": "Базовый",
        "inflation_rate": 0.07,
        "nominal_return_rate": 0.11,
        "weight": 0.55,
    },
    "stagflation": {
        "label": "Стагфляционный",
        "inflation_rate": 0.10,
        "nominal_return_rate": 0.11,
        "weight": 0.20,
    },
    "optimistic": {
        "label": "Оптимистичный",
        "inflation_rate": 0.04,
        "nominal_return_rate": 0.115,
        "weight": 0.10,
    },
}


def _safe_monthly_rate(annual_rate: float) -> float:
    if annual_rate <= -1.0:
        return -1.0
    return (1.0 + annual_rate) ** (1.0 / 12.0) - 1.0


def _target_capital(annual_expense: float, swr: float) -> float:
    if swr <= 0:
        return float("inf")
    return annual_expense / swr


def build_fire_projection(
    *,
    current_capital: float,
    monthly_contribution: float,
    monthly_target_expense: float,
    inflation_rate: float,
    nominal_return_rate: float,
    swr_target: float,
    swr_withdrawal: float,
    horizon_years: int = 30,
) -> dict:
    """FIRE-проекция с расчётом в реальных рублях."""
    start_capital = max(float(current_capital or 0.0), 0.0)
    monthly_contrib = max(float(monthly_contribution or 0.0), 0.0)
    monthly_expense = max(float(monthly_target_expense or 0.0), 0.0)
    inflation = float(inflation_rate or 0.0)
    nominal_return = float(nominal_return_rate or 0.0)
    swr_goal = float(swr_target or 0.0)
    swr_operational = float(swr_withdrawal or 0.0)
    years = max(int(horizon_years or 0), 0)

    real_return_rate = nominal_return - inflation
    annual_target_expense_today = monthly_expense * 12.0
    target_capital_goal = _target_capital(annual_target_expense_today, swr_goal)
    target_capital_operational = _target_capital(annual_target_expense_today, swr_operational)

    monthly_real_return = _safe_monthly_rate(real_return_rate)
    trajectory: list[dict[str, float | int]] = []
    years_to_fire_goal: float | None = None
    years_to_fire_operational: float | None = None

    capital_real = start_capital
    if capital_real >= target_capital_goal:
        years_to_fire_goal = 0.0
    if capital_real >= target_capital_operational:
        years_to_fire_operational = 0.0

    total_months = years * 12
    for month_index in range(1, total_months + 1):
        capital_real = capital_real * (1.0 + monthly_real_return) + monthly_contrib
        year = month_index // 12

        if years_to_fire_goal is None and capital_real >= target_capital_goal:
            years_to_fire_goal = month_index / 12.0
        if years_to_fire_operational is None and capital_real >= target_capital_operational:
            years_to_fire_operational = month_index / 12.0

        if month_index % 12 != 0:
            continue

        capital_nominal = capital_real * ((1.0 + inflation) ** year)
        trajectory.append(
            {
                "year": year,
                "capital_real": capital_real,
                "capital_nominal": capital_nominal,
            }
        )

    if years_to_fire_goal is not None and years_to_fire_goal > years:
        years_to_fire_goal = None
    if years_to_fire_operational is not None and years_to_fire_operational > years:
        years_to_fire_operational = None

    return {
        "real_return_rate": real_return_rate,
        "annual_target_expense_today": annual_target_expense_today,
        "target_capital_swr_target_real": target_capital_goal,
        "target_capital_swr_withdrawal_real": target_capital_operational,
        "years_to_fire_swr_target": years_to_fire_goal,
        "years_to_fire_swr_withdrawal": years_to_fire_operational,
        "trajectory": trajectory,
        "params": {
            "current_capital": start_capital,
            "monthly_contribution": monthly_contrib,
            "monthly_target_expense": monthly_expense,
            "inflation_rate": inflation,
            "nominal_return_rate": nominal_return,
            "swr_target": swr_goal,
            "swr_withdrawal": swr_operational,
            "horizon_years": years,
        },
    }


def build_fire_scenarios(
    *,
    current_capital: float,
    monthly_contribution: float,
    monthly_target_expense: float,
    swr_target: float = 0.03,
    swr_withdrawal: float = 0.035,
    horizon_years: int = 30,
    presets: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict:
    """Рассчитать FIRE-проекции по набору сценариев."""
    scenario_presets: Mapping[str, Mapping[str, Any]] = presets or SCENARIO_PRESETS
    scenarios: dict[str, dict] = {}
    used_presets: dict[str, dict] = {}

    for key, preset in scenario_presets.items():
        inflation_rate = float(preset.get("inflation_rate", 0.0) or 0.0)
        nominal_return_rate = float(preset.get("nominal_return_rate", 0.0) or 0.0)
        used_presets[key] = {
            "label": str(preset.get("label") or key),
            "inflation_rate": inflation_rate,
            "nominal_return_rate": nominal_return_rate,
            "weight": float(preset.get("weight", 0.0) or 0.0),
        }
        scenarios[key] = build_fire_projection(
            current_capital=current_capital,
            monthly_contribution=monthly_contribution,
            monthly_target_expense=monthly_target_expense,
            inflation_rate=inflation_rate,
            nominal_return_rate=nominal_return_rate,
            swr_target=swr_target,
            swr_withdrawal=swr_withdrawal,
            horizon_years=horizon_years,
        )

    return {
        "scenarios": scenarios,
        "presets": used_presets,
    }


def build_contribution_series(initial_monthly: float, growth_pct: float, periods: int) -> list[float]:
    """Ряд взносов по годам."""
    values = []
    current = initial_monthly
    for _ in range(periods):
        values.append(current)
        current *= (1 + growth_pct / 100)
    return values


def get_age_based_target_stocks(age: int) -> int:
    """Целевой % акций по возрасту (глайд-пат)."""
    if age < 35:
        return 50
    if age < 45:
        return 40
    return 30


def build_glide_path(ages: Sequence[int]) -> tuple[list[float], list[float]]:
    """Линии глайд-пата: %акций/%облигаций."""
    glide_stocks = []
    glide_bonds = []
    for age in ages:
        if age < 35:
            stocks = 50
        elif age < 40:
            stocks = 50 - (age - 34) * 4
        elif age < 50:
            stocks = 30 - (age - 39) * 1
        else:
            stocks = 20
        glide_stocks.append(stocks)
        glide_bonds.append(100 - stocks)
    return glide_stocks, glide_bonds


def calculate_security_mix(pos_df: pd.DataFrame) -> dict:
    """Текущее распределение акций/облигаций для FIRE-глайд-пата."""
    if pos_df.empty:
        return {
            "bonds_value": 0.0,
            "stocks_value": 0.0,
            "etf_value": 0.0,
            "total_sec": 0.0,
            "bonds_pct": None,
            "stocks_pct": None,
        }

    bonds_value = float(pos_df[pos_df["asset_type"].isin(["bond_ofz_pd", "bond_ofz_in", "bond_corp"])]["value_end"].sum())
    stocks_value = float(pos_df[pos_df["asset_type"] == "stock"]["value_end"].sum())
    etf_value = float(pos_df[pos_df["asset_type"] == "etf"]["value_end"].sum())
    total_sec = bonds_value + stocks_value + etf_value

    if total_sec <= 0:
        bonds_pct = None
        stocks_pct = None
    else:
        bonds_pct = bonds_value / total_sec * 100
        stocks_pct = (stocks_value + etf_value) / total_sec * 100

    return {
        "bonds_value": bonds_value,
        "stocks_value": stocks_value,
        "etf_value": etf_value,
        "total_sec": total_sec,
        "bonds_pct": bonds_pct,
        "stocks_pct": stocks_pct,
    }


def simulate_fire_monte_carlo(
    *,
    current_portfolio: float,
    fire_age: int,
    fire_target_age_max: int,
    fire_monthly_contrib: float,
    fire_contrib_growth: float,
    fire_return_nominal: float,
    fire_inflation: float,
    fire_target: float,
    mc_simulations: int,
    mc_volatility: float,
    mc_crash_prob: float,
    mc_crash_severity: float,
    random_seed: int = 42,
) -> dict:
    """Monte Carlo симуляция достижения FIRE."""
    rng = random.Random(random_seed)

    years_sim = fire_target_age_max - fire_age + 5
    mean_annual = fire_return_nominal / 100
    vol_annual = mc_volatility / 100
    crash_prob = mc_crash_prob / 100
    crash_mean = mc_crash_severity / 100

    all_paths = []
    fire_ages_mc = []

    for _ in range(int(mc_simulations)):
        balance = current_portfolio
        monthly_c = fire_monthly_contrib
        path = [balance]
        sim_fire_age = None

        for year in range(1, years_sim + 1):
            age = fire_age + year
            if rng.random() < crash_prob:
                annual_return = crash_mean + rng.gauss(0, 0.1)
            else:
                annual_return = rng.gauss(mean_annual, vol_annual)

            monthly_return = (1 + annual_return) ** (1 / 12) - 1
            for _ in range(12):
                balance = balance * (1 + monthly_return) + monthly_c

            balance = max(balance, 0)
            monthly_c *= (1 + fire_contrib_growth / 100)
            real_balance = balance / ((1 + fire_inflation / 100) ** year)
            path.append(real_balance)

            if sim_fire_age is None and real_balance >= fire_target:
                sim_fire_age = age

        all_paths.append(path)
        if sim_fire_age is not None:
            fire_ages_mc.append(sim_fire_age)

    fire_prob = (len(fire_ages_mc) / mc_simulations * 100) if mc_simulations else 0.0

    return {
        "years_sim": years_sim,
        "all_paths": all_paths,
        "fire_ages_mc": fire_ages_mc,
        "fire_prob": fire_prob,
    }


def calculate_percentile_bands(all_paths: Sequence[Sequence[float]], num_points: int) -> dict:
    """Перцентильные полосы 5/25/50/75/95 по траекториям."""
    p5, p25, p50, p75, p95 = [], [], [], [], []

    for t in range(num_points):
        values_at_t = [path[t] for path in all_paths if t < len(path)]
        if not values_at_t:
            continue
        values_at_t = sorted(values_at_t)
        n = len(values_at_t)
        p5.append(values_at_t[int(n * 0.05)])
        p25.append(values_at_t[int(n * 0.25)])
        p50.append(values_at_t[int(n * 0.50)])
        p75.append(values_at_t[int(n * 0.75)])
        p95.append(values_at_t[int(n * 0.95)])

    return {"p5": p5, "p25": p25, "p50": p50, "p75": p75, "p95": p95}


def calculate_fire_window_stats(
    fire_ages_mc: Sequence[int],
    fire_target_age_min: int,
    fire_target_age_max: int,
    mc_simulations: int,
) -> dict:
    """Статистика сценариев достижения FIRE по возрастным окнам."""
    in_window = sum(1 for age in fire_ages_mc if fire_target_age_min <= age <= fire_target_age_max)
    before_window = sum(1 for age in fire_ages_mc if age < fire_target_age_min)
    after_window = sum(1 for age in fire_ages_mc if age > fire_target_age_max)
    never = mc_simulations - len(fire_ages_mc)

    return {
        "in_window": in_window,
        "before_window": before_window,
        "after_window": after_window,
        "never": never,
    }
