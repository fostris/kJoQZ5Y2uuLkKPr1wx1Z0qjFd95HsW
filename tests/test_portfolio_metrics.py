import unittest

import pandas as pd

from portfolio_metrics import (
    add_pnl_columns,
    add_position_shares,
    calculate_total_portfolio_value,
    calculate_total_position_value,
)


class PositionValueTests(unittest.TestCase):
    def test_value_plus_nkd(self):
        self.assertEqual(calculate_total_position_value(1000, 25), 1025.0)

    def test_missing_nkd(self):
        self.assertEqual(calculate_total_position_value(1000, None), 1000.0)

    def test_missing_value(self):
        self.assertIsNone(calculate_total_position_value(None, 25))

    def test_both_missing(self):
        self.assertIsNone(calculate_total_position_value(None, None))


class PortfolioValueTests(unittest.TestCase):
    def test_multiple_positions(self):
        df = pd.DataFrame(
            [
                {"value_end": 1000.0, "nkd_end": 10.0},
                {"value_end": 500.0, "nkd_end": 5.0},
            ]
        )
        self.assertEqual(calculate_total_portfolio_value(df), 1515.0)

    def test_empty_portfolio(self):
        df = pd.DataFrame(columns=["value_end", "nkd_end"])
        self.assertEqual(calculate_total_portfolio_value(df), 0.0)

    def test_none_values(self):
        df = pd.DataFrame(
            [
                {"value_end": None, "nkd_end": 10.0},
                {"value_end": 500.0, "nkd_end": None},
            ]
        )
        self.assertEqual(calculate_total_portfolio_value(df), 510.0)

    def test_zero_values(self):
        df = pd.DataFrame(
            [
                {"value_end": 0.0, "nkd_end": 0.0},
                {"value_end": 0.0, "nkd_end": 0.0},
            ]
        )
        self.assertEqual(calculate_total_portfolio_value(df), 0.0)


class PnlTests(unittest.TestCase):
    def test_add_pnl_columns_scenarios(self):
        df = pd.DataFrame(
            [
                {"isin": "POS", "value_end": 110.0, "nkd_end": 0.0, "qty": 1},   # current > cost
                {"isin": "NEG", "value_end": 80.0, "nkd_end": 0.0, "qty": 1},    # current < cost
                {"isin": "NOAVG", "value_end": 50.0, "nkd_end": 0.0, "qty": 1},  # avg missing
                {"isin": "ZEROQ", "value_end": 0.0, "nkd_end": 0.0, "qty": 0},   # qty zero
            ]
        )
        cost_map = {
            "POS": {"avg_price": 100.0},
            "NEG": {"avg_price": 100.0},
            "ZEROQ": {"avg_price": 50.0},
        }

        out = add_pnl_columns(df, cost_map)

        self.assertAlmostEqual(out.iloc[0]["pnl"], 10.0)
        self.assertAlmostEqual(out.iloc[0]["pnl_pct"], 10.0)

        self.assertAlmostEqual(out.iloc[1]["pnl"], -20.0)
        self.assertAlmostEqual(out.iloc[1]["pnl_pct"], -20.0)

        self.assertTrue(pd.isna(out.iloc[2]["avg_price"]))
        self.assertTrue(pd.isna(out.iloc[2]["pnl"]))
        self.assertTrue(pd.isna(out.iloc[2]["pnl_pct"]))

        self.assertAlmostEqual(out.iloc[3]["pnl"], 0.0)
        self.assertAlmostEqual(out.iloc[3]["pnl_pct"], 0.0)


class PortfolioSharesTests(unittest.TestCase):
    def test_normal_portfolio(self):
        df = pd.DataFrame([{"total": 100.0}, {"total": 300.0}])
        out = add_position_shares(df, value_column="total")
        self.assertAlmostEqual(out.iloc[0]["position_share"], 0.25)
        self.assertAlmostEqual(out.iloc[1]["position_share"], 0.75)

    def test_total_zero(self):
        df = pd.DataFrame([{"total": 0.0}, {"total": 0.0}])
        out = add_position_shares(df, value_column="total")
        self.assertAlmostEqual(out.iloc[0]["position_share"], 0.0)
        self.assertAlmostEqual(out.iloc[1]["position_share"], 0.0)

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["total"])
        out = add_position_shares(df, value_column="total")
        self.assertIn("position_share", out.columns)
        self.assertEqual(len(out), 0)

    def test_single_position_hundred_percent(self):
        df = pd.DataFrame([{"total": 500.0}])
        out = add_position_shares(df, value_column="total")
        self.assertAlmostEqual(out.iloc[0]["position_share"], 1.0)


if __name__ == "__main__":
    unittest.main()
