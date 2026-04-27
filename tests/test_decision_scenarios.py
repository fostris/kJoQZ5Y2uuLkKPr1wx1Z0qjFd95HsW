import unittest
from datetime import date

from analytics.decision_scenarios import build_buy_candidates


class BuyScenarioTests(unittest.TestCase):
    def test_candidates_sorted_by_ytm_then_position_share(self):
        positions = [
            {"name": "Bond A", "isin": "ISIN_A", "asset_type": "bond_corp", "value_end": 100.0, "nkd_end": 0.0},
            {"name": "Bond C", "isin": "ISIN_C", "asset_type": "bond_corp", "value_end": 100.0, "nkd_end": 0.0},
            {"name": "Bond B", "isin": "ISIN_B", "asset_type": "bond_corp", "value_end": 100.0, "nkd_end": 0.0},
        ]

        result = build_buy_candidates(
            positions=positions,
            free_cash=90.0,
            issuer_by_isin={"ISIN_A": "Issuer A", "ISIN_B": "Issuer B", "ISIN_C": "Issuer C"},
            ytm_by_isin={"ISIN_A": 14.0, "ISIN_B": 12.0, "ISIN_C": 14.0},
            maturity_by_isin={"ISIN_A": "2028-04-01", "ISIN_B": "2028-04-01", "ISIN_C": "2028-04-01"},
            position_share_map={"ISIN_A": 0.03, "ISIN_B": 0.01, "ISIN_C": 0.05},
            issuer_share_map={"Issuer A": 0.03, "Issuer B": 0.01, "Issuer C": 0.05},
            current_type_pct={"bond_corp": 35.0},
            target_type_pct={"bond_corp": 45.0},
            total_portfolio_value=1000.0,
            max_issuer_share=0.10,
            max_position_share=0.10,
            min_ytm=10.0,
            max_years_to_maturity=10.0,
            exclude_without_ytm=True,
            exclude_without_maturity=True,
            bond_asset_types=("bond_corp", "bond_ofz_pd", "bond_ofz_in"),
            as_of_date=date(2026, 4, 28),
        )

        candidates = result["candidates"]
        self.assertEqual([row["name"] for row in candidates], ["Bond A", "Bond C", "Bond B"])
        self.assertAlmostEqual(candidates[0]["suggested_amount"], 30.0)
        self.assertAlmostEqual(candidates[1]["suggested_amount"], 30.0)
        self.assertAlmostEqual(candidates[2]["suggested_amount"], 30.0)

    def test_exclusion_reasons_are_reported(self):
        positions = [
            {"name": "Bond Good", "isin": "GOOD", "asset_type": "bond_corp", "value_end": 100.0, "nkd_end": 0.0},
            {"name": "Bond No YTM", "isin": "NOYTM", "asset_type": "bond_corp", "value_end": 100.0, "nkd_end": 0.0},
            {"name": "Bond Long", "isin": "LONG", "asset_type": "bond_corp", "value_end": 100.0, "nkd_end": 0.0},
            {"name": "Bond Issuer Limit", "isin": "ISSLIM", "asset_type": "bond_corp", "value_end": 100.0, "nkd_end": 0.0},
        ]

        result = build_buy_candidates(
            positions=positions,
            free_cash=100.0,
            issuer_by_isin={
                "GOOD": "Issuer G",
                "NOYTM": "Issuer N",
                "LONG": "Issuer L",
                "ISSLIM": "Issuer X",
            },
            ytm_by_isin={"GOOD": 12.0, "LONG": 12.5, "ISSLIM": 13.0},
            maturity_by_isin={"GOOD": "2028-01-01", "LONG": "2040-01-01", "ISSLIM": "2028-01-01"},
            position_share_map={"GOOD": 0.03, "NOYTM": 0.03, "LONG": 0.03, "ISSLIM": 0.03},
            issuer_share_map={"Issuer G": 0.03, "Issuer N": 0.03, "Issuer L": 0.03, "Issuer X": 0.15},
            current_type_pct={"bond_corp": 40.0},
            target_type_pct={"bond_corp": 50.0},
            total_portfolio_value=1000.0,
            max_issuer_share=0.10,
            max_position_share=0.10,
            min_ytm=10.0,
            max_years_to_maturity=6.0,
            exclude_without_ytm=True,
            exclude_without_maturity=True,
            bond_asset_types=("bond_corp", "bond_ofz_pd", "bond_ofz_in"),
            as_of_date=date(2026, 4, 28),
        )

        self.assertEqual(len(result["candidates"]), 1)
        summary = {row["reason_code"]: row["count"] for row in result["excluded_summary"]}
        self.assertEqual(summary["missing_ytm"], 1)
        self.assertEqual(summary["maturity_too_long"], 1)
        self.assertEqual(summary["issuer_share_limit"], 1)

    def test_missing_ytm_can_be_kept_with_warning(self):
        positions = [
            {"name": "Bond No YTM", "isin": "NOYTM", "asset_type": "bond_corp", "value_end": 100.0, "nkd_end": 0.0},
        ]
        result = build_buy_candidates(
            positions=positions,
            free_cash=50.0,
            issuer_by_isin={"NOYTM": "Issuer N"},
            ytm_by_isin={},
            maturity_by_isin={"NOYTM": "2028-01-01"},
            position_share_map={"NOYTM": 0.03},
            issuer_share_map={"Issuer N": 0.03},
            current_type_pct={"bond_corp": 40.0},
            target_type_pct={"bond_corp": 50.0},
            total_portfolio_value=1000.0,
            max_issuer_share=0.10,
            max_position_share=0.10,
            min_ytm=10.0,
            max_years_to_maturity=6.0,
            exclude_without_ytm=False,
            exclude_without_maturity=True,
            bond_asset_types=("bond_corp", "bond_ofz_pd", "bond_ofz_in"),
            as_of_date=date(2026, 4, 28),
        )

        self.assertEqual(len(result["candidates"]), 1)
        self.assertIn("нет YTM", result["candidates"][0]["warnings"])
        self.assertIn("YTM нет", result["candidates"][0]["explanation"])


if __name__ == "__main__":
    unittest.main()

