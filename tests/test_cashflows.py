import unittest
from datetime import date

from analytics.cashflows import build_coupon_cashflow_by_month, build_maturity_ladder


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


class MaturityLadderTests(unittest.TestCase):
    def test_regular_maturity(self):
        positions = [{"isin": "ISIN1", "qty": 10, "nominal": 1000}]
        maturities = [
            {
                "isin": "ISIN1",
                "maturity_date": "2027-06-01",
                "maturity_value": 10000.0,
                "qty": 10,
                "nominal": 1000,
            }
        ]

        result = build_maturity_ladder(
            positions=positions,
            maturities=maturities,
            amortizations=[],
            as_of_date=date(2026, 1, 1),
        )

        self.assertEqual(len(result["years"]), 1)
        row = result["years"][0]
        self.assertEqual(row["year"], 2027)
        self.assertAlmostEqual(row["maturity_return"], 10000.0)
        self.assertAlmostEqual(row["amortization_return"], 0.0)
        self.assertAlmostEqual(row["total_return"], 10000.0)
        self.assertEqual(row["maturity_count"], 1)
        self.assertEqual(row["amortization_count"], 0)

    def test_amortizing_bond(self):
        positions = [{"isin": "ISIN1", "qty": 10, "nominal": 1000}]
        maturities = [
            {"isin": "ISIN1", "maturity_date": "2028-01-10", "maturity_value": 6000.0},
        ]
        amortizations = [
            {"isin": "ISIN1", "amort_date": "2026-07-15", "amort_value": 2000.0},
            {"isin": "ISIN1", "amort_date": "2027-07-15", "amort_value": 2000.0},
        ]

        result = build_maturity_ladder(
            positions=positions,
            maturities=maturities,
            amortizations=amortizations,
            as_of_date=date(2026, 1, 1),
        )

        self.assertEqual([row["year"] for row in result["years"]], [2026, 2027, 2028])
        self.assertAlmostEqual(result["years"][0]["amortization_return"], 2000.0)
        self.assertAlmostEqual(result["years"][1]["amortization_return"], 2000.0)
        self.assertAlmostEqual(result["years"][2]["maturity_return"], 6000.0)
        self.assertAlmostEqual(result["total_amortization_return"], 4000.0)
        self.assertAlmostEqual(result["total_maturity_return"], 6000.0)
        self.assertAlmostEqual(result["total_return"], 10000.0)


if __name__ == "__main__":
    unittest.main()
