import unittest
from pathlib import Path

import parser as bp


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "parser"


class ParserTests(unittest.TestCase):
    def test_parse_minimal_report_dates_and_totals(self):
        report = bp.parse_report(FIXTURES_DIR / "minimal_report.html")

        self.assertEqual(report.period_start, "01.01.2026")
        self.assertEqual(report.period_end, "31.01.2026")
        self.assertEqual(report.report_date, "01.02.2026")
        self.assertEqual(report.investor, "TEST INVESTOR")
        self.assertEqual(report.contract, "ABC123")

        self.assertEqual(report.total_start, 105000.0)
        self.assertEqual(report.total_end, 127000.0)
        # Проверяем пустое значение из таблицы: должно стать 0.0.
        self.assertEqual(report.total_change, 0.0)

    def test_parse_minimal_report_positions_and_nkd_empty_values(self):
        report = bp.parse_report(FIXTURES_DIR / "minimal_report.html")

        self.assertEqual(len(report.positions), 1)
        pos = report.positions[0]
        self.assertEqual(pos.name, "Test Bond 01")
        self.assertEqual(pos.isin, "RU000TEST01")
        self.assertEqual(pos.qty, 12)
        self.assertEqual(pos.value_start, 9910.0)
        self.assertEqual(pos.value_end, 12144.0)
        self.assertEqual(pos.nkd_start, 0.0)
        self.assertEqual(pos.nkd_end, 0.0)
        self.assertEqual(pos.asset_type, "bond_corp")

    def test_parse_minimal_report_cashflows_trades_deposits(self):
        report = bp.parse_report(FIXTURES_DIR / "minimal_report.html")

        self.assertEqual(len(report.cash_flows), 1)
        cash_flow = report.cash_flows[0]
        self.assertEqual(cash_flow.date, "05.01.2026")
        self.assertEqual(cash_flow.description, "Купон")
        self.assertEqual(cash_flow.credit, 320.5)
        self.assertEqual(cash_flow.debit, 0.0)

        self.assertEqual(len(report.trades), 1)
        trade = report.trades[0]
        self.assertEqual(trade.trade_date, "06.01.2026")
        self.assertEqual(trade.name, "Test Bond 01")
        self.assertEqual(trade.ticker, "TSTBOND")
        self.assertEqual(trade.qty, 2)
        self.assertEqual(trade.nkd, 0.0)
        self.assertEqual(trade.broker_fee, 1.1)
        self.assertEqual(trade.exchange_fee, 0.2)
        self.assertEqual(trade.status, "Исполнена")

        self.assertEqual(len(report.deposits), 2)
        self.assertEqual(report.deposits[0].iis_type, "ИИС")
        self.assertEqual(report.deposits[0].year, "2026")
        self.assertEqual(report.deposits[0].amount, 40000.0)
        self.assertEqual(report.deposits[1].iis_type, "ИИС-3")
        self.assertEqual(report.deposits[1].amount, 50000.0)

    def test_parse_incomplete_tables_skips_short_rows(self):
        report = bp.parse_report(FIXTURES_DIR / "incomplete_report.html")

        self.assertEqual(report.period_start, "01.02.2026")
        self.assertEqual(report.period_end, "28.02.2026")
        self.assertEqual(report.report_date, "01.03.2026")
        self.assertEqual(report.total_change, -150.0)

        self.assertEqual(report.positions, [])
        self.assertEqual(report.cash_flows, [])
        self.assertEqual(report.trades, [])
        self.assertEqual(report.deposits, [])


if __name__ == "__main__":
    unittest.main()
