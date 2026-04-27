import unittest

from analytics.data_quality import build_bond_data_quality_report


class BondDataQualityTests(unittest.TestCase):
    def test_missing_ytm_issuer_and_maturity(self):
        positions = [
            {
                "name": "Bond A",
                "isin": "ISIN1",
                "asset_type": "bond_corp",
                "value_end": 1000.0,
                "nkd_end": 10.0,
                "price_end": 99.0,
            }
        ]
        report = build_bond_data_quality_report(
            positions=positions,
            ytm_map={},
            issuer_map={},
            maturities=[],
            coupons=[{"isin": "ISIN1"}],
            cost_basis={"ISIN1": {"avg_price": 95.0}},
            amortizations=[],
        )

        self.assertEqual(report["bond_count"], 1)
        self.assertEqual(report["bonds_with_issues_count"], 1)
        codes = {item["code"] for item in report["problems"]}
        self.assertIn("ytm", codes)
        self.assertIn("issuer", codes)
        self.assertIn("maturity", codes)

    def test_amortization_required_but_missing(self):
        positions = [
            {
                "name": "Bond A",
                "isin": "ISIN1",
                "asset_type": "bond_corp",
                "value_end": 1000.0,
                "nkd_end": 10.0,
                "price_end": 99.0,
            }
        ]
        maturities = [
            {"isin": "ISIN1", "maturity_date": "2028-01-01", "has_amortization": 1},
        ]
        report = build_bond_data_quality_report(
            positions=positions,
            ytm_map={"ISIN1": 12.0},
            issuer_map={"ISIN1": "Issuer A"},
            maturities=maturities,
            coupons=[{"isin": "ISIN1"}],
            cost_basis={"ISIN1": {"avg_price": 95.0}},
            amortizations=[],
        )

        codes = {item["code"] for item in report["problems"]}
        self.assertIn("amortization", codes)

    def test_full_data_has_no_problems(self):
        positions = [
            {
                "name": "Bond A",
                "isin": "ISIN1",
                "asset_type": "bond_corp",
                "value_end": 1000.0,
                "nkd_end": 10.0,
                "price_end": 99.0,
            }
        ]
        maturities = [
            {"isin": "ISIN1", "maturity_date": "2028-01-01", "has_amortization": 0},
        ]
        report = build_bond_data_quality_report(
            positions=positions,
            ytm_map={"ISIN1": 12.0},
            issuer_map={"ISIN1": "Issuer A"},
            maturities=maturities,
            coupons=[{"isin": "ISIN1"}],
            cost_basis={"ISIN1": {"avg_price": 95.0}},
            amortizations=[],
        )

        self.assertEqual(report["bond_count"], 1)
        self.assertEqual(report["bonds_with_issues_count"], 0)
        self.assertEqual(report["problems"], [])
        self.assertAlmostEqual(report["overall_score_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()

