import unittest

from report_export import build_portfolio_summary_html


class ReportExportTests(unittest.TestCase):
    def test_build_portfolio_summary_html_with_data(self):
        html = build_portfolio_summary_html(
            report_date="27.04.2026",
            portfolio_value=1_000_000,
            bond_value=450_000,
            weighted_ytm=12.34,
            ytm_coverage_pct=0.82,
            largest_positions=[
                {"name": "Bond A", "isin": "ISIN1", "position_share": 0.12, "market_value": 120_000},
            ],
            largest_issuers=[
                {"issuer": "Issuer A", "issuer_share": 0.25, "market_value": 250_000},
            ],
            warnings=[{"severity": "warning", "text": "Доля эмитента 25%"}],
            coupon_cashflow_12m={
                "months": [{"month": "2026-05", "income": 1500.0, "payments_count": 2}],
                "total_income": 1500.0,
            },
            maturity_ladder={
                "years": [{"year": 2027, "maturity_return": 10000.0, "amortization_return": 2000.0, "total_return": 12000.0}],
            },
        )

        self.assertIn("Краткий отчёт портфеля", html)
        self.assertIn("27.04.2026", html)
        self.assertIn("Bond A", html)
        self.assertIn("Issuer A", html)
        self.assertIn("[warning] Доля эмитента 25%", html)
        self.assertIn("Итого за 12 месяцев", html)
        self.assertIn("2026-05", html)

    def test_build_portfolio_summary_html_marks_missing_data(self):
        html = build_portfolio_summary_html(
            report_date="27.04.2026",
            portfolio_value=None,
            bond_value=None,
            weighted_ytm=None,
            ytm_coverage_pct=None,
            largest_positions=[],
            largest_issuers=[],
            warnings=[],
            coupon_cashflow_12m={"months": [], "total_income": None},
            maturity_ladder={"years": []},
        )

        self.assertIn("нет данных", html)
        self.assertIn("Средневзвешенная YTM недоступна", html)
        self.assertIn("Нет данных для блока крупнейших позиций", html)
        self.assertIn("Предупреждения отсутствуют", html)


if __name__ == "__main__":
    unittest.main()
