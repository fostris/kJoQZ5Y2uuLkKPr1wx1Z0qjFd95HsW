import tempfile
import unittest
from pathlib import Path

import db


class PortfolioTargetsDbTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db_path = db.DB_PATH
        db.DB_PATH = Path(self._tmpdir.name) / "portfolio_test.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._original_db_path
        self._tmpdir.cleanup()

    def test_migration_creates_portfolio_targets_and_defaults(self):
        with db.get_db() as conn:
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='portfolio_targets'"
            ).fetchone()

        self.assertIsNotNone(table_exists)
        targets = db.get_portfolio_targets()
        self.assertEqual(set(targets.keys()), set(db.PORTFOLIO_TARGET_DEFAULTS.keys()))

        for key, (default_value, _description) in db.PORTFOLIO_TARGET_DEFAULTS.items():
            self.assertAlmostEqual(float(targets[key]), float(default_value), places=9)

    def test_apply_migrations_is_idempotent_for_portfolio_targets(self):
        first_targets = db.get_portfolio_targets()
        applied = db.apply_migrations()
        second_targets = db.get_portfolio_targets()

        self.assertEqual(applied, 0)
        self.assertEqual(set(second_targets.keys()), set(db.PORTFOLIO_TARGET_DEFAULTS.keys()))
        self.assertEqual(len(second_targets), 7)
        self.assertEqual(first_targets, second_targets)

    def test_set_portfolio_target_updates_value(self):
        db.set_portfolio_target("issuer_max_pct", 0.123)
        targets = db.get_portfolio_targets()
        self.assertAlmostEqual(targets["issuer_max_pct"], 0.123, places=9)

    def test_get_portfolio_targets_returns_all_keys(self):
        targets = db.get_portfolio_targets()
        self.assertEqual(len(targets), 7)
        self.assertTrue(set(db.PORTFOLIO_TARGET_DEFAULTS.keys()).issubset(set(targets.keys())))

    def test_reset_portfolio_targets_to_defaults(self):
        db.set_portfolio_target("position_max_pct", 0.22)
        db.set_portfolio_target("duration_max_years", 10.0)

        changed = db.get_portfolio_targets()
        self.assertAlmostEqual(changed["position_max_pct"], 0.22, places=9)
        self.assertAlmostEqual(changed["duration_max_years"], 10.0, places=9)

        db.reset_portfolio_targets_to_defaults()
        reset_targets = db.get_portfolio_targets()

        for key, (default_value, _description) in db.PORTFOLIO_TARGET_DEFAULTS.items():
            self.assertAlmostEqual(float(reset_targets[key]), float(default_value), places=9)


if __name__ == "__main__":
    unittest.main()
