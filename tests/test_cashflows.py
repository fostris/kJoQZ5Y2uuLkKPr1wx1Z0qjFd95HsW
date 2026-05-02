import unittest
from datetime import date

from analytics.cashflows import (
    build_12m_cashflow_forecast,
    build_coupon_cashflow_by_month,
    build_maturity_ladder,
)


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


class CashflowForecast12MTests(unittest.TestCase):
    def test_ofz_coupons_are_included_in_12m_forecast(self):
        positions = [
            {
                "isin": "RU000A0JWM07",
                "asset_type": "bond_ofz_pd",
                "qty": 9,
                "nominal": 1000,
                "value_end": 9000,
                "nkd_end": 0,
            }
        ]
        result = build_12m_cashflow_forecast(
            positions=positions,
            coupon_schedule={
                "RU000A0JWM07": [
                    {"coupon_date": "2026-09-16", "coupon_amount": 38.64},
                    {"coupon_date": "2027-03-17", "coupon_amount": 38.64},
                ]
            },
            maturity_by_isin={},
            amortization_schedule={},
            dividend_schedule={},
            bonds_total_value=9000.0,
            as_of_date=date(2026, 5, 1),
        )
        sep = next(row for row in result.months if row.year_month == "2026-09")
        mar = next(row for row in result.months if row.year_month == "2027-03")
        self.assertAlmostEqual(sep.coupons, 38.64 * 9)
        self.assertAlmostEqual(mar.coupons, 38.64 * 9)
        self.assertAlmostEqual(result.by_source["coupons"], 38.64 * 9 * 2)

    def test_monthly_grouping_and_12_rows(self):
        positions = [{"isin": "B1", "asset_type": "bond_corp", "qty": 10, "nominal": 1000, "value_end": 10000, "nkd_end": 0}]
        result = build_12m_cashflow_forecast(
            positions=positions,
            coupon_schedule={
                "B1": [
                    {"coupon_date": "2026-04-15", "coupon_amount": 10.0},
                    {"coupon_date": "2026-05-15", "coupon_amount": 10.0},
                    {"coupon_date": "2026-05-31", "coupon_amount": 5.0},
                    {"coupon_date": "2026-06-01", "coupon_amount": 7.0},
                ]
            },
            maturity_by_isin={},
            amortization_schedule={},
            dividend_schedule={},
            bonds_total_value=10000.0,
            as_of_date=date(2026, 4, 1),
        )
        self.assertEqual(len(result.months), 12)
        apr = next(row for row in result.months if row.year_month == "2026-04")
        may = next(row for row in result.months if row.year_month == "2026-05")
        jun = next(row for row in result.months if row.year_month == "2026-06")
        self.assertAlmostEqual(apr.coupons, 100.0)
        self.assertAlmostEqual(may.coupons, 150.0)
        self.assertAlmostEqual(jun.coupons, 70.0)

    def test_sources_split_and_totals(self):
        positions = [{"isin": "B1", "asset_type": "bond_corp", "qty": 10, "nominal": 1000, "value_end": 10000, "nkd_end": 0}]
        result = build_12m_cashflow_forecast(
            positions=positions,
            coupon_schedule={"B1": [{"coupon_date": "2026-04-10", "coupon_amount": 3.0}]},
            maturity_by_isin={"B1": date(2026, 4, 20)},
            amortization_schedule={"B1": [{"amort_date": "2026-04-05", "amort_value": 1000.0, "qty": 10}]},
            dividend_schedule={"B1": [{"record_date": "2026-04-25", "dividend_amount": 2.0}]},
            bonds_total_value=10000.0,
            as_of_date=date(2026, 4, 1),
        )
        apr = next(row for row in result.months if row.year_month == "2026-04")
        self.assertAlmostEqual(apr.coupons, 30.0)
        self.assertAlmostEqual(apr.amortizations, 1000.0)
        self.assertAlmostEqual(apr.dividends, 20.0)
        self.assertAlmostEqual(apr.total, apr.coupons + apr.maturities + apr.amortizations + apr.dividends)
        self.assertAlmostEqual(result.by_source["coupons"], 30.0)
        self.assertAlmostEqual(result.by_source["amortizations"], 1000.0)
        self.assertAlmostEqual(result.by_source["dividends"], 20.0)
        self.assertAlmostEqual(result.total, sum(row.total for row in result.months))

    def test_window_12_months_inclusive_start_exclusive_end(self):
        positions = [{"isin": "B1", "asset_type": "bond_corp", "qty": 10, "nominal": 1000, "value_end": 10000, "nkd_end": 0}]
        result = build_12m_cashflow_forecast(
            positions=positions,
            coupon_schedule={
                "B1": [
                    {"coupon_date": "2026-04-01", "coupon_amount": 1.0},  # входит
                    {"coupon_date": "2027-04-01", "coupon_amount": 1.0},  # не входит
                    {"coupon_date": "2027-05-01", "coupon_amount": 1.0},  # не входит
                ]
            },
            maturity_by_isin={},
            amortization_schedule={},
            dividend_schedule={},
            bonds_total_value=10000.0,
            as_of_date=date(2026, 4, 1),
        )
        self.assertAlmostEqual(result.by_source["coupons"], 10.0)

    def test_reinvestment_risk_buckets_and_shares(self):
        as_of = date(2026, 4, 1)
        positions = [
            {"isin": "B25", "asset_type": "bond_corp", "qty": 1, "nominal": 1000, "value_end": 1000, "nkd_end": 0},
            {"isin": "B100", "asset_type": "bond_corp", "qty": 1, "nominal": 2000, "value_end": 2000, "nkd_end": 0},
            {"isin": "S1", "asset_type": "stock", "qty": 10, "value_end": 1000, "nkd_end": 0},
        ]
        result = build_12m_cashflow_forecast(
            positions=positions,
            coupon_schedule={"B25": [{"coupon_date": "2026-04-10", "coupon_amount": 5.0}]},  # не входит в reinvestment
            maturity_by_isin={"B25": date(2026, 4, 26), "B100": date(2026, 7, 10)},
            amortization_schedule={},
            dividend_schedule={"S1": [{"record_date": "2026-04-15", "dividend_amount": 1.0}]},  # не входит
            bonds_total_value=3000.0,
            as_of_date=as_of,
        )
        rr = result.reinvestment_risk
        self.assertAlmostEqual(rr.days_30, 1000.0)
        self.assertAlmostEqual(rr.days_90, 1000.0)
        self.assertAlmostEqual(rr.days_180, 3000.0)
        self.assertAlmostEqual(rr.days_365, 3000.0)
        self.assertAlmostEqual(rr.share_30, 1000.0 / 3000.0)
        self.assertAlmostEqual(rr.share_90, 1000.0 / 3000.0)
        self.assertAlmostEqual(rr.share_180, 1.0)
        self.assertAlmostEqual(rr.share_365, 1.0)

    def test_reinvestment_risk_zero_bonds_value_has_zero_shares(self):
        positions = [{"isin": "B1", "asset_type": "bond_corp", "qty": 1, "nominal": 1000, "value_end": 1000, "nkd_end": 0}]
        result = build_12m_cashflow_forecast(
            positions=positions,
            coupon_schedule={},
            maturity_by_isin={"B1": date(2026, 4, 20)},
            amortization_schedule={},
            dividend_schedule={},
            bonds_total_value=0.0,
            as_of_date=date(2026, 4, 1),
        )
        rr = result.reinvestment_risk
        self.assertEqual(rr.share_30, 0.0)
        self.assertEqual(rr.share_90, 0.0)
        self.assertEqual(rr.share_180, 0.0)
        self.assertEqual(rr.share_365, 0.0)

    def test_empty_or_missing_schedules_return_zero_forecast(self):
        positions = []
        result = build_12m_cashflow_forecast(
            positions=positions,
            coupon_schedule={},
            maturity_by_isin={},
            amortization_schedule={},
            dividend_schedule={},
            bonds_total_value=0.0,
            as_of_date=date(2026, 4, 1),
        )
        self.assertEqual(len(result.months), 12)
        self.assertTrue(all(row.total == 0.0 for row in result.months))
        self.assertEqual(result.total, 0.0)
        self.assertEqual(result.reinvestment_risk.days_365, 0.0)


if __name__ == "__main__":
    unittest.main()
