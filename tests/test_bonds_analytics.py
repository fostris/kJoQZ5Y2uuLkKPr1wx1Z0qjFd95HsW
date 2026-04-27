import unittest
from datetime import date

from analytics.bonds import (
    calculate_days_to_maturity,
    calculate_weighted_years_to_maturity,
    calculate_weighted_ytm,
    calculate_years_to_maturity,
)


class WeightedYtmTests(unittest.TestCase):
    def test_weighted_ytm_with_full_coverage(self):
        positions = [
            {"asset_type": "bond_corp", "isin": "BOND1", "value_end": 100.0, "nkd_end": 0.0},
            {"asset_type": "bond_ofz_pd", "isin": "BOND2", "value_end": 300.0, "nkd_end": 0.0},
            {"asset_type": "stock", "isin": "STOCK1", "value_end": 500.0, "nkd_end": 0.0},
        ]

        metrics = calculate_weighted_ytm(
            positions=positions,
            ytm_by_isin={"BOND1": 10.0, "BOND2": 20.0},
        )

        self.assertAlmostEqual(metrics["weighted_ytm"], 17.5)
        self.assertAlmostEqual(metrics["coverage_pct"], 1.0)
        self.assertAlmostEqual(metrics["covered_value"], 400.0)
        self.assertAlmostEqual(metrics["total_bond_value"], 400.0)
        self.assertEqual(metrics["missing_count"], 0)
        self.assertEqual(metrics["missing_positions"], [])

    def test_weighted_ytm_with_partial_coverage(self):
        positions = [
            {"asset_type": "bond_corp", "isin": "BOND1", "value_end": 100.0, "nkd_end": 0.0},
            {"asset_type": "bond_ofz_in", "isin": "BOND2", "value_end": 300.0, "nkd_end": 0.0},
        ]

        metrics = calculate_weighted_ytm(
            positions=positions,
            ytm_by_isin={"BOND1": 12.0},
        )

        self.assertAlmostEqual(metrics["weighted_ytm"], 12.0)
        self.assertAlmostEqual(metrics["coverage_pct"], 0.25)
        self.assertAlmostEqual(metrics["total_bond_value"], 400.0)
        self.assertAlmostEqual(metrics["covered_value"], 100.0)
        self.assertEqual(metrics["missing_count"], 1)
        self.assertEqual(metrics["missing_positions"][0]["isin"], "BOND2")
        self.assertAlmostEqual(metrics["missing_positions"][0]["portfolio_share"], 0.75)

    def test_no_ytm_values_results_in_zero_coverage(self):
        positions = [
            {"asset_type": "bond_corp", "isin": "BOND1", "value_end": 100.0, "nkd_end": 0.0},
            {"asset_type": "bond_ofz_in", "isin": "BOND2", "value_end": 300.0, "nkd_end": 0.0},
        ]

        metrics = calculate_weighted_ytm(
            positions=positions,
            ytm_by_isin={},
        )

        self.assertIsNone(metrics["weighted_ytm"])
        self.assertAlmostEqual(metrics["coverage_pct"], 0.0)
        self.assertAlmostEqual(metrics["total_bond_value"], 400.0)
        self.assertAlmostEqual(metrics["covered_value"], 0.0)
        self.assertEqual(metrics["missing_count"], 2)
        self.assertEqual([row["isin"] for row in metrics["missing_positions"]], ["BOND2", "BOND1"])

    def test_no_bonds_returns_no_data(self):
        positions = [
            {"asset_type": "stock", "isin": "STOCK1", "value_end": 1000.0, "nkd_end": 0.0},
        ]

        metrics = calculate_weighted_ytm(
            positions=positions,
            ytm_by_isin={"STOCK1": 15.0},
        )

        self.assertIsNone(metrics["weighted_ytm"])
        self.assertIsNone(metrics["coverage_pct"])
        self.assertAlmostEqual(metrics["total_bond_value"], 0.0)
        self.assertAlmostEqual(metrics["covered_value"], 0.0)
        self.assertEqual(metrics["missing_count"], 0)
        self.assertEqual(metrics["missing_positions"], [])

    def test_uses_market_value_fallback_when_value_end_missing(self):
        positions = [
            {
                "asset_type": "bond_corp",
                "isin": "BOND1",
                "qty": 2,
                "nominal": 1000,
                "price_end": 105.0,
                "nkd_end": 10.0,
                "value_end": None,
            },
        ]

        metrics = calculate_weighted_ytm(
            positions=positions,
            ytm_by_isin={"BOND1": 11.0},
        )

        self.assertAlmostEqual(metrics["weighted_ytm"], 11.0)
        self.assertAlmostEqual(metrics["coverage_pct"], 1.0)
        self.assertAlmostEqual(metrics["total_bond_value"], 2110.0)
        self.assertAlmostEqual(metrics["covered_value"], 2110.0)


class MaturityAnalyticsTests(unittest.TestCase):
    def test_calculate_years_to_maturity(self):
        as_of = date(2026, 1, 1)
        self.assertAlmostEqual(calculate_years_to_maturity("2027-01-01", as_of), 365 / 365.25, places=6)
        self.assertEqual(calculate_days_to_maturity("2027-01-01", as_of), 365)

    def test_invalid_maturity_date_returns_none(self):
        as_of = date(2026, 1, 1)
        self.assertIsNone(calculate_years_to_maturity("invalid", as_of))
        self.assertIsNone(calculate_days_to_maturity(None, as_of))

    def test_weighted_years_to_maturity_with_partial_coverage(self):
        positions = [
            {"asset_type": "bond_corp", "isin": "B1", "value_end": 100.0, "nkd_end": 0.0},
            {"asset_type": "bond_ofz_pd", "isin": "B2", "value_end": 300.0, "nkd_end": 0.0},
            {"asset_type": "stock", "isin": "S1", "value_end": 500.0, "nkd_end": 0.0},
        ]
        as_of = date(2026, 1, 1)
        maturity_map = {
            "B1": "2027-01-01",
        }

        metrics = calculate_weighted_years_to_maturity(positions, maturity_map, as_of)

        self.assertAlmostEqual(metrics["coverage_pct"], 0.25)
        self.assertEqual(metrics["missing_count"], 1)
        self.assertAlmostEqual(metrics["covered_value"], 100.0)
        self.assertAlmostEqual(metrics["total_bond_value"], 400.0)
        self.assertAlmostEqual(metrics["weighted_years_to_maturity"], 365 / 365.25, places=6)

    def test_weighted_years_to_maturity_no_bonds(self):
        metrics = calculate_weighted_years_to_maturity(
            positions=[{"asset_type": "stock", "isin": "S1", "value_end": 100.0, "nkd_end": 0.0}],
            maturity_by_isin={},
            as_of_date=date(2026, 1, 1),
        )
        self.assertIsNone(metrics["weighted_years_to_maturity"])
        self.assertIsNone(metrics["coverage_pct"])
        self.assertEqual(metrics["missing_count"], 0)


if __name__ == "__main__":
    unittest.main()
