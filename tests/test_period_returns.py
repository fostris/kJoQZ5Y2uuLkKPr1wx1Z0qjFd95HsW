import unittest
from datetime import date

from portfolio_metrics import compute_period_returns


class PeriodReturnsTests(unittest.TestCase):
    def test_no_flows_twr_equals_simple_return(self):
        result = compute_period_returns(
            current_report_id=2,
            current_value=110_000.0,
            current_date=date(2026, 1, 31),
            historical_snapshots=[
                {"report_id": 1, "period_end": "01.01.2026", "total_value": 100_000.0},
                {"report_id": 2, "period_end": "31.01.2026", "total_value": 110_000.0},
            ],
            deposits=[],
            withdrawals=[],
        )
        month = result["month"]
        self.assertIsNotNone(month)
        self.assertAlmostEqual(month["abs_change"], 10_000.0, places=2)
        self.assertAlmostEqual(month["twr_pct"], 10.0, places=4)

    def test_single_mid_period_deposit_is_neutralized(self):
        result = compute_period_returns(
            current_report_id=2,
            current_value=155_000.0,
            current_date=date(2026, 1, 31),
            historical_snapshots=[
                {"report_id": 1, "period_end": "01.01.2026", "total_value": 100_000.0},
                {"report_id": 2, "period_end": "31.01.2026", "total_value": 155_000.0},
            ],
            deposits=[{"date": "16.01.2026", "amount": 50_000.0}],
            withdrawals=[],
        )
        month = result["month"]
        self.assertIsNotNone(month)
        self.assertAlmostEqual(month["abs_change"], 5_000.0, places=2)
        self.assertAlmostEqual(month["twr_pct"], 3.333333, places=3)

    def test_multiple_deposits_are_handled(self):
        result = compute_period_returns(
            current_report_id=2,
            current_value=160_000.0,
            current_date=date(2026, 1, 31),
            historical_snapshots=[
                {"report_id": 1, "period_end": "01.01.2026", "total_value": 100_000.0},
                {"report_id": 2, "period_end": "31.01.2026", "total_value": 160_000.0},
            ],
            deposits=[
                {"date": "10.01.2026", "amount": 20_000.0},
                {"date": "20.01.2026", "amount": 30_000.0},
            ],
            withdrawals=[],
        )
        month = result["month"]
        self.assertIsNotNone(month)
        self.assertAlmostEqual(month["abs_change"], 10_000.0, places=2)
        self.assertIsNotNone(month["twr_pct"])
        self.assertGreater(month["twr_pct"], 0.0)

    def test_missing_start_snapshot_returns_none_for_period(self):
        result = compute_period_returns(
            current_report_id=1,
            current_value=120_000.0,
            current_date=date(2026, 1, 31),
            historical_snapshots=[
                {"report_id": 1, "period_end": "31.01.2026", "total_value": 120_000.0},
            ],
            deposits=[],
            withdrawals=[],
        )
        self.assertIsNone(result["month"])
        self.assertIsNone(result["3m"])

    def test_zero_start_value_makes_twr_undefined(self):
        result = compute_period_returns(
            current_report_id=2,
            current_value=100_000.0,
            current_date=date(2026, 1, 31),
            historical_snapshots=[
                {"report_id": 1, "period_end": "01.01.2026", "total_value": 0.0},
                {"report_id": 2, "period_end": "31.01.2026", "total_value": 100_000.0},
            ],
            deposits=[{"date": "16.01.2026", "amount": 100_000.0}],
            withdrawals=[],
        )
        month = result["month"]
        self.assertIsNotNone(month)
        self.assertAlmostEqual(month["abs_change"], 0.0, places=2)
        self.assertIsNone(month["twr_pct"])

    def test_all_time_contains_abs_pnl_and_twr(self):
        result = compute_period_returns(
            current_report_id=3,
            current_value=155_000.0,
            current_date=date(2026, 1, 31),
            historical_snapshots=[
                {"report_id": 1, "period_end": "01.01.2026", "total_value": 100_000.0},
                {"report_id": 2, "period_end": "15.01.2026", "total_value": 102_000.0},
                {"report_id": 3, "period_end": "31.01.2026", "total_value": 155_000.0},
            ],
            deposits=[
                {"date": "01.01.2026", "amount": 100_000.0},
                {"date": "16.01.2026", "amount": 50_000.0},
            ],
            withdrawals=[],
        )
        all_time = result["all"]
        self.assertIsNotNone(all_time)
        self.assertAlmostEqual(all_time["abs_pnl"], 5_000.0, places=2)
        self.assertIsNotNone(all_time["twr_pct"])
        self.assertGreater(all_time["twr_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
