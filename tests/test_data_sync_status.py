import tempfile
import unittest
from pathlib import Path

import db


class DataSyncStatusDbTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db_path = db.DB_PATH
        db.DB_PATH = Path(self._tmpdir.name) / "portfolio_test.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._original_db_path
        self._tmpdir.cleanup()

    def test_get_data_sync_freshness_empty(self):
        freshness = db.get_data_sync_freshness("ytm")

        self.assertEqual(freshness["entity"], "ytm")
        self.assertEqual(freshness["total"], 0)
        self.assertIsNone(freshness["latest_at"])

    def test_upsert_data_sync_status_keeps_history_and_errors(self):
        db.upsert_data_sync_status(
            data_source="moex_iss",
            entity="ytm",
            isin="RU000A0JX0J2",
            status="success",
            fetched_at="2026-04-27 10:00:00",
        )
        db.upsert_data_sync_status(
            data_source="moex_iss",
            entity="ytm",
            isin="RU000A0JX0J2",
            status="error",
            error_message="temporary network error",
            fetched_at="2026-04-27 10:05:00",
        )
        db.upsert_data_sync_status(
            data_source="moex_iss",
            entity="ytm",
            isin="RU000A10C5L7",
            status="success",
            fetched_at="2026-04-27 10:06:00",
        )

        freshness = db.get_data_sync_freshness("ytm")

        self.assertEqual(freshness["total"], 3)
        self.assertEqual(freshness["success_count"], 2)
        self.assertEqual(freshness["error_count"], 1)
        self.assertEqual(freshness["latest_status"], "success")
        self.assertEqual(freshness["latest_success_at"], "2026-04-27 10:06:00")
        self.assertEqual(freshness["latest_error_at"], "2026-04-27 10:05:00")
        self.assertEqual(freshness["latest_error_message"], "temporary network error")

        with db.get_db() as conn:
            total_rows = conn.execute("SELECT COUNT(*) AS c FROM data_sync_status").fetchone()["c"]
        self.assertEqual(total_rows, 3)

    def test_get_data_sync_freshness_filters_by_entity(self):
        db.upsert_data_sync_status(
            data_source="moex_iss",
            entity="coupon",
            isin="RU000A0JX0J2",
            status="success",
            fetched_at="2026-04-27 11:00:00",
        )
        db.upsert_data_sync_status(
            data_source="moex_iss",
            entity="maturity",
            isin="RU000A0JX0J2",
            status="error",
            error_message="http 503",
            fetched_at="2026-04-27 11:01:00",
        )

        coupon_freshness = db.get_data_sync_freshness("coupon")
        maturity_freshness = db.get_data_sync_freshness("maturity")

        self.assertEqual(coupon_freshness["total"], 1)
        self.assertEqual(coupon_freshness["success_count"], 1)
        self.assertEqual(coupon_freshness["error_count"], 0)
        self.assertEqual(maturity_freshness["total"], 1)
        self.assertEqual(maturity_freshness["success_count"], 0)
        self.assertEqual(maturity_freshness["error_count"], 1)
        self.assertEqual(maturity_freshness["latest_error_message"], "http 503")


if __name__ == "__main__":
    unittest.main()
