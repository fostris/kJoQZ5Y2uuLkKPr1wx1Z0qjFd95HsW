import unittest
from datetime import date

from analytics.data_quality import build_attention_list, build_bond_data_quality_report


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


class AttentionListTests(unittest.TestCase):
    def test_empty_input_returns_empty_list(self):
        attention = build_attention_list(
            positions=[],
            position_share_map={},
            issuer_share_map={},
            issuer_map={},
            ytm_map={},
            maturity_by_isin={},
            coupons=[],
            cost_basis={},
            as_of_date=date(2026, 4, 27),
        )

        self.assertEqual(attention, [])

    def test_one_bond_can_have_multiple_reasons(self):
        positions = [
            {
                "name": "Bond Risk",
                "isin": "ISIN1",
                "asset_type": "bond_corp",
                "value_end": 1000.0,
                "nkd_end": 0.0,
                "qty": 10,
                "price_end": 80.0,
            }
        ]
        attention = build_attention_list(
            positions=positions,
            position_share_map={"ISIN1": 0.12},
            issuer_share_map={"Issuer A": 0.20},
            issuer_map={"ISIN1": "Issuer A"},
            ytm_map={},
            maturity_by_isin={},
            coupons=[],
            cost_basis={"ISIN1": {"avg_price": 120.0}},
            as_of_date=date(2026, 4, 27),
            near_maturity_days_threshold=90,
            loss_pct_threshold=-10.0,
            long_maturity_years_threshold=7.0,
            concentration_threshold=0.10,
        )

        self.assertEqual(len(attention), 1)
        row = attention[0]
        self.assertIn("Доля позиции", row["reason"])
        self.assertIn("Доля эмитента", row["reason"])
        self.assertIn("Нет YTM", row["reason"])
        self.assertIn("Нет даты погашения", row["reason"])
        self.assertIn("Нет купонного календаря", row["reason"])
        self.assertIn("Убыток", row["reason"])
        self.assertIn("оценить концентрацию", row["suggested_action"])
        self.assertIn("проверить доходность", row["suggested_action"])
        self.assertIn("проверить данные", row["suggested_action"])
        self.assertIn("проверить причину убытка", row["suggested_action"])

    def test_attention_list_sorted_by_severity_then_share(self):
        positions = [
            {"name": "A", "isin": "A", "asset_type": "stock", "value_end": 120.0, "nkd_end": 0.0},
            {"name": "B", "isin": "B", "asset_type": "stock", "value_end": 160.0, "nkd_end": 0.0},
            {"name": "C", "isin": "C", "asset_type": "stock", "value_end": 130.0, "nkd_end": 0.0},
        ]
        attention = build_attention_list(
            positions=positions,
            position_share_map={"A": 0.12, "B": 0.16, "C": 0.13},
            issuer_share_map={},
            issuer_map={},
            ytm_map={},
            maturity_by_isin={},
            coupons=[],
            cost_basis={},
            as_of_date=date(2026, 4, 27),
        )

        self.assertEqual([row["isin"] for row in attention], ["B", "C", "A"])
        self.assertEqual([row["severity"] for row in attention], ["high", "warning", "warning"])


if __name__ == "__main__":
    unittest.main()
