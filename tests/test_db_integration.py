import tempfile
import unittest
from pathlib import Path

import db
import parser as bp


class DbIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db_path = db.DB_PATH
        db.DB_PATH = Path(self._tmpdir.name) / "portfolio_test.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._original_db_path
        self._tmpdir.cleanup()

    def _build_report(self) -> bp.BrokerReport:
        return bp.BrokerReport(
            report_date="01.04.2026",
            period_start="01.03.2026",
            period_end="31.03.2026",
            investor="TEST USER",
            contract="TEST-001",
            total_start=100000.0,
            total_end=110500.0,
            total_change=10500.0,
            securities_start=90000.0,
            securities_end=100000.0,
            cash_start=10000.0,
            cash_end=10500.0,
            positions=[
                bp.Position(
                    name="Test Bond",
                    isin="RU000TEST99",
                    currency="RUB",
                    qty=10,
                    nominal=1000.0,
                    price_end=101.2,
                    value_end=10120.0,
                    nkd_end=80.0,
                    price_start=99.8,
                    value_start=9980.0,
                    nkd_start=70.0,
                    change_value=150.0,
                    asset_type="bond_corp",
                )
            ],
            cash_flows=[
                bp.CashFlow(
                    date="15.03.2026",
                    description="Купон",
                    currency="RUB",
                    credit=450.0,
                    debit=0.0,
                )
            ],
            trades=[
                bp.Trade(
                    trade_date="10.03.2026",
                    settle_date="12.03.2026",
                    trade_time="12:00:00",
                    name="Test Bond",
                    ticker="TSTBOND",
                    currency="RUB",
                    side="Покупка",
                    qty=2,
                    price=1000.0,
                    amount=2000.0,
                    nkd=10.0,
                    broker_fee=1.0,
                    exchange_fee=0.2,
                    trade_id="TR-100",
                    status="Исполнена",
                )
            ],
            deposits=[
                bp.Deposit(
                    year="2026",
                    date="05.03.2026",
                    amount=40000.0,
                    iis_type="ИИС",
                )
            ],
            securities_info=[],
        )

    def test_schema_creation_contains_required_tables(self):
        with db.get_db() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()

        tables = {row["name"] for row in rows}
        required_tables = {
            "reports",
            "positions",
            "coupon_calendar",
            "bond_maturities",
            "cost_basis",
            "schema_migrations",
        }
        self.assertTrue(required_tables.issubset(tables))

    def test_import_report_and_read_positions(self):
        report = self._build_report()

        report_id = db.import_report(report)
        self.assertGreater(report_id, 0)

        duplicate_id = db.import_report(report)
        self.assertEqual(duplicate_id, -1)

        positions = db.get_positions(report_id)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["isin"], "RU000TEST99")
        self.assertEqual(positions[0]["asset_type"], "bond_corp")
        self.assertEqual(positions[0]["qty"], 10)
        self.assertEqual(positions[0]["nkd_end"], 80.0)

    def test_upsert_coupon_inserts_and_updates(self):
        db.upsert_coupon(
            isin="RU000TEST99",
            name="Test Bond",
            coupon_date="2026-06-15",
            coupon_rate=12.5,
            coupon_amount=31.4,
            nominal=1000.0,
            qty=10,
            expected_income=314.0,
        )
        db.upsert_coupon(
            isin="RU000TEST99",
            name="Test Bond",
            coupon_date="2026-06-15",
            coupon_rate=12.0,
            coupon_amount=30.0,
            nominal=1000.0,
            qty=12,
            expected_income=360.0,
        )

        coupons = db.get_coupon_calendar()
        self.assertEqual(len(coupons), 1)
        self.assertEqual(coupons[0]["coupon_amount"], 30.0)
        self.assertEqual(coupons[0]["qty"], 12)
        self.assertEqual(coupons[0]["expected_income"], 360.0)

    def test_upsert_bond_maturity_inserts_and_updates(self):
        db.upsert_bond_maturity(
            isin="RU000TEST99",
            name="Test Bond",
            maturity_date="2029-03-01",
            nominal=1000.0,
            qty=10,
            maturity_value=10000.0,
            coupon_rate=11.0,
            has_amortization=False,
        )
        db.upsert_bond_maturity(
            isin="RU000TEST99",
            name="Test Bond v2",
            maturity_date="2029-06-01",
            nominal=1000.0,
            qty=12,
            maturity_value=12000.0,
            coupon_rate=10.5,
            has_amortization=True,
        )

        maturities = db.get_bond_maturities()
        self.assertEqual(len(maturities), 1)
        self.assertEqual(maturities[0]["name"], "Test Bond v2")
        self.assertEqual(maturities[0]["maturity_date"], "2029-06-01")
        self.assertEqual(maturities[0]["maturity_value"], 12000.0)
        self.assertEqual(maturities[0]["has_amortization"], 1)

    def test_cost_basis_upsert_and_map(self):
        db.upsert_cost_basis(
            isin="RU000TEST99",
            name="Test Bond",
            avg_price=990.0,
            total_qty=10,
            total_cost=9900.0,
            source="manual",
        )
        db.upsert_cost_basis(
            isin="RU000TEST99",
            name="Test Bond",
            avg_price=995.0,
            total_qty=12,
            total_cost=11940.0,
            source="auto",
        )

        cost_map = db.get_cost_basis_map()
        self.assertIn("RU000TEST99", cost_map)
        self.assertEqual(cost_map["RU000TEST99"]["avg_price"], 995.0)
        self.assertEqual(cost_map["RU000TEST99"]["total_qty"], 12)
        self.assertEqual(cost_map["RU000TEST99"]["total_cost"], 11940.0)

    def test_tests_run_on_temporary_database_only(self):
        self.assertEqual(db.DB_PATH.parent, Path(self._tmpdir.name))
        self.assertEqual(db.DB_PATH.name, "portfolio_test.db")
        self.assertNotEqual(db.DB_PATH, self._original_db_path)


if __name__ == "__main__":
    unittest.main()
