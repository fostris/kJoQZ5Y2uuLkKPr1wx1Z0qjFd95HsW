import sqlite3
import tempfile
import unittest
from pathlib import Path

import db


class DbMigrationsTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db_path = db.DB_PATH
        db.DB_PATH = Path(self._tmpdir.name) / "portfolio_test.db"

    def tearDown(self):
        db.DB_PATH = self._original_db_path
        self._tmpdir.cleanup()

    def test_init_db_applies_migrations_on_new_database(self):
        db.init_db()

        version = db.get_schema_version()
        self.assertEqual(version, db.SCHEMA_MIGRATIONS[-1][0])

        with db.get_db() as conn:
            migrations_count = conn.execute("SELECT COUNT(*) AS c FROM schema_migrations").fetchone()["c"]
            data_sync_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='data_sync_status'"
            ).fetchone()
            bond_ratings_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bond_ratings'"
            ).fetchone()
            instrument_fx_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='instrument_fx'"
            ).fetchone()
            reports_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='reports'"
            ).fetchone()

        self.assertEqual(migrations_count, len(db.SCHEMA_MIGRATIONS))
        self.assertIsNotNone(data_sync_exists)
        self.assertIsNotNone(bond_ratings_exists)
        self.assertIsNotNone(instrument_fx_exists)
        self.assertIsNotNone(reports_exists)

    def test_apply_migrations_is_idempotent(self):
        db.init_db()

        with db.get_db() as conn:
            before_count = conn.execute("SELECT COUNT(*) AS c FROM schema_migrations").fetchone()["c"]

        applied = db.apply_migrations()

        with db.get_db() as conn:
            after_count = conn.execute("SELECT COUNT(*) AS c FROM schema_migrations").fetchone()["c"]

        self.assertEqual(applied, 0)
        self.assertEqual(after_count, before_count)
        self.assertEqual(db.get_schema_version(), db.SCHEMA_MIGRATIONS[-1][0])

    def test_existing_db_without_schema_migrations_is_supported(self):
        # Эмулируем старую БД без schema_migrations и без data_sync_status.
        conn = sqlite3.connect(str(db.DB_PATH))
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_date TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL
                )
                """
            )
        finally:
            conn.close()

        db.init_db()

        self.assertEqual(db.get_schema_version(), db.SCHEMA_MIGRATIONS[-1][0])
        with db.get_db() as conn:
            has_migrations = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            has_data_sync = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='data_sync_status'"
            ).fetchone()

        self.assertIsNotNone(has_migrations)
        self.assertIsNotNone(has_data_sync)


if __name__ == "__main__":
    unittest.main()
