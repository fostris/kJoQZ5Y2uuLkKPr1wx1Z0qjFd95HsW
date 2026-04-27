import unittest

import pandas as pd

from ui.charts import plot_coupon_cashflow_by_month, plot_ytm_vs_maturity


class YtmVsMaturityChartTests(unittest.TestCase):
    def test_excludes_rows_without_ytm_or_maturity(self):
        df = pd.DataFrame(
            [
                {
                    "name": "Bond A",
                    "isin": "ISIN1",
                    "asset_type": "bond_corp",
                    "ytm": 11.5,
                    "years_to_maturity": 2.3,
                    "position_share": 0.12,
                },
                {
                    "name": "Bond B",
                    "isin": "ISIN2",
                    "asset_type": "bond_corp",
                    "ytm": None,
                    "years_to_maturity": 3.1,
                    "position_share": 0.08,
                },
                {
                    "name": "Bond C",
                    "isin": "ISIN3",
                    "asset_type": "bond_ofz_pd",
                    "ytm": 9.1,
                    "years_to_maturity": None,
                    "position_share": 0.06,
                },
            ]
        )

        result = plot_ytm_vs_maturity(df)

        self.assertIsNotNone(result["figure"])
        self.assertEqual(result["included_count"], 1)
        self.assertEqual(len(result["excluded_positions"]), 2)

        reasons = {row["isin"]: row["reason"] for row in result["excluded_positions"]}
        self.assertIn("нет YTM", reasons["ISIN2"])
        self.assertIn("нет срока до погашения", reasons["ISIN3"])

    def test_hover_contains_required_fields(self):
        df = pd.DataFrame(
            [
                {
                    "name": "Bond A",
                    "isin": "ISIN1",
                    "asset_type": "bond_corp",
                    "ytm": 11.5,
                    "years_to_maturity": 2.3,
                    "position_share": 0.12,
                }
            ]
        )

        result = plot_ytm_vs_maturity(df)

        self.assertIsNotNone(result["figure"])
        hovertemplate = result["figure"].data[0].hovertemplate
        self.assertIn("ISIN", hovertemplate)
        self.assertIn("YTM, %", hovertemplate)
        self.assertIn("Срок до погашения, лет", hovertemplate)
        self.assertIn("Доля позиции, %", hovertemplate)

    def test_no_valid_points_returns_none_figure(self):
        df = pd.DataFrame(
            [
                {
                    "name": "Bond X",
                    "isin": "ISINX",
                    "asset_type": "bond_corp",
                    "ytm": None,
                    "years_to_maturity": None,
                    "position_share": 0.1,
                }
            ]
        )

        result = plot_ytm_vs_maturity(df)

        self.assertIsNone(result["figure"])
        self.assertEqual(result["included_count"], 0)
        self.assertEqual(len(result["excluded_positions"]), 1)


class CouponCashflowChartTests(unittest.TestCase):
    def test_months_sorted_chronologically(self):
        cashflow_df = pd.DataFrame(
            [
                {"month": "2026-12", "income": 300.0, "payments_count": 1, "bonds_text": "C"},
                {"month": "2026-10", "income": 100.0, "payments_count": 1, "bonds_text": "A"},
                {"month": "2026-11", "income": 200.0, "payments_count": 2, "bonds_text": "B"},
            ]
        )

        result = plot_coupon_cashflow_by_month(cashflow_df)

        self.assertIsNotNone(result["figure"])
        x_values = list(result["figure"].data[0].x)
        self.assertEqual(x_values, ["10.2026", "11.2026", "12.2026"])
        self.assertAlmostEqual(result["dataframe"]["income"].sum(), 600.0)

    def test_empty_dataframe_returns_none_figure(self):
        result = plot_coupon_cashflow_by_month(pd.DataFrame())

        self.assertIsNone(result["figure"])
        self.assertTrue(result["dataframe"].empty)


if __name__ == "__main__":
    unittest.main()
