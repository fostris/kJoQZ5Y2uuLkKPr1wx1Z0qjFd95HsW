import unittest
from datetime import date

from analytics.cashflows import build_coupon_cashflow_by_month


class CouponCashflowByMonthTests(unittest.TestCase):
    def test_one_bond_two_coupons(self):
        positions = [
            {"isin": "ISIN1", "qty": 10},
        ]
        coupons = [
            {"isin": "ISIN1", "name": "Bond A", "coupon_date": "2026-05-15", "coupon_amount": 12.5},
            {"isin": "ISIN1", "name": "Bond A", "coupon_date": "2026-11-20", "coupon_amount": 11.0},
        ]

        result = build_coupon_cashflow_by_month(
            coupons=coupons,
            positions=positions,
            months=12,
            as_of_date=date(2026, 5, 1),
        )

        may_row = next(row for row in result["months"] if row["month"] == "2026-05")
        nov_row = next(row for row in result["months"] if row["month"] == "2026-11")

        self.assertAlmostEqual(may_row["income"], 125.0)
        self.assertEqual(may_row["payments_count"], 1)
        self.assertEqual(may_row["bonds"], ["Bond A"])

        self.assertAlmostEqual(nov_row["income"], 110.0)
        self.assertEqual(nov_row["payments_count"], 1)
        self.assertEqual(nov_row["bonds"], ["Bond A"])

        self.assertAlmostEqual(result["total_income"], 235.0)
        self.assertEqual(result["total_payments"], 2)

    def test_several_bonds_same_month(self):
        positions = [
            {"isin": "ISIN1", "qty": 5},
            {"isin": "ISIN2", "qty": 10},
        ]
        coupons = [
            {"isin": "ISIN1", "name": "Bond A", "coupon_date": "2026-06-10", "coupon_amount": 10.0},
            {"isin": "ISIN2", "name": "Bond B", "coupon_date": "2026-06-25", "coupon_amount": 8.0},
        ]

        result = build_coupon_cashflow_by_month(
            coupons=coupons,
            positions=positions,
            months=12,
            as_of_date=date(2026, 6, 1),
        )

        june_row = next(row for row in result["months"] if row["month"] == "2026-06")
        self.assertAlmostEqual(june_row["income"], 130.0)
        self.assertEqual(june_row["payments_count"], 2)
        self.assertEqual(june_row["bonds"], ["Bond A", "Bond B"])

    def test_window_limited_to_12_months(self):
        positions = [{"isin": "ISIN1", "qty": 10}]
        coupons = [
            {"isin": "ISIN1", "name": "Bond A", "coupon_date": "2026-05-15", "coupon_amount": 10.0},
            {"isin": "ISIN1", "name": "Bond A", "coupon_date": "2027-05-01", "coupon_amount": 10.0},
        ]

        result = build_coupon_cashflow_by_month(
            coupons=coupons,
            positions=positions,
            months=12,
            as_of_date=date(2026, 5, 1),
        )

        may_2026 = next(row for row in result["months"] if row["month"] == "2026-05")
        apr_2027 = next(row for row in result["months"] if row["month"] == "2027-04")

        self.assertAlmostEqual(may_2026["income"], 100.0)
        self.assertAlmostEqual(apr_2027["income"], 0.0)
        self.assertAlmostEqual(result["total_income"], 100.0)
        self.assertEqual(len(result["months"]), 12)


if __name__ == "__main__":
    unittest.main()

