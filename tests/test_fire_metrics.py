import unittest

from fire_metrics import build_fire_projection, build_fire_scenarios


class FireMetricsTests(unittest.TestCase):
    def test_target_capital_by_two_swr_values(self):
        result = build_fire_projection(
            current_capital=5_000_000.0,
            monthly_contribution=20_000.0,
            monthly_target_expense=80_000.0,
            inflation_rate=0.07,
            nominal_return_rate=0.11,
            swr_target=0.03,
            swr_withdrawal=0.035,
            horizon_years=30,
        )
        self.assertAlmostEqual(result["annual_target_expense_today"], 960_000.0)
        self.assertAlmostEqual(result["target_capital_swr_target_real"], 32_000_000.0)
        self.assertAlmostEqual(result["target_capital_swr_withdrawal_real"], 960_000.0 / 0.035)

    def test_negative_real_return_decreases_capital_real(self):
        result = build_fire_projection(
            current_capital=1_000_000.0,
            monthly_contribution=0.0,
            monthly_target_expense=80_000.0,
            inflation_rate=0.10,
            nominal_return_rate=0.05,
            swr_target=0.03,
            swr_withdrawal=0.035,
            horizon_years=3,
        )
        trajectory = result["trajectory"]
        self.assertLess(result["real_return_rate"], 0.0)
        self.assertLess(trajectory[0]["capital_real"], 1_000_000.0)
        self.assertLess(trajectory[1]["capital_real"], trajectory[0]["capital_real"])

    def test_goal_reachable_within_horizon(self):
        result = build_fire_projection(
            current_capital=30_000_000.0,
            monthly_contribution=50_000.0,
            monthly_target_expense=80_000.0,
            inflation_rate=0.03,
            nominal_return_rate=0.10,
            swr_target=0.03,
            swr_withdrawal=0.035,
            horizon_years=10,
        )
        years = result["years_to_fire_swr_target"]
        self.assertIsNotNone(years)
        self.assertGreaterEqual(years, 0.0)
        self.assertLessEqual(years, 10.0)

    def test_goal_not_reachable_within_horizon(self):
        result = build_fire_projection(
            current_capital=1_000_000.0,
            monthly_contribution=0.0,
            monthly_target_expense=80_000.0,
            inflation_rate=0.07,
            nominal_return_rate=0.07,
            swr_target=0.03,
            swr_withdrawal=0.035,
            horizon_years=10,
        )
        self.assertIsNone(result["years_to_fire_swr_target"])

    def test_build_fire_scenarios_returns_all_default_keys(self):
        result = build_fire_scenarios(
            current_capital=5_000_000.0,
            monthly_contribution=20_000.0,
            monthly_target_expense=80_000.0,
            horizon_years=30,
        )
        self.assertIn("base", result["scenarios"])
        self.assertIn("stagflation", result["scenarios"])
        self.assertIn("optimistic", result["scenarios"])


if __name__ == "__main__":
    unittest.main()
