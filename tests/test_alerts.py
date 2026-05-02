import unittest
from datetime import date, timedelta

from analytics.alerts import build_alerts


def _default_data_quality_data():
    return {
        "ytm_by_isin": {},
        "maturity_by_isin": {},
        "rating_by_isin": {},
        "cost_basis": {},
        "issuer_by_isin": {},
    }


def _default_concentration_data(positions):
    return {
        "positions": [
            {
                "isin": row.get("isin"),
                "name": row.get("name"),
                "position_share": row.get("position_share"),
            }
            for row in positions
        ],
        "issuers": [],
        "sectors": [],
        "position_hhi": None,
        "position_hhi_target": None,
        "total_portfolio_value": 1_000_000.0,
    }


def _rule_alerts(alerts, rule_code):
    return [row for row in alerts if row.rule_code == rule_code]


class AlertsDataRulesTests(unittest.TestCase):
    def test_missing_ytm_triggers_for_bond(self):
        positions = [
            {"name": "Bond A", "isin": "B1", "asset_type": "bond_corp", "position_share": 0.02},
        ]
        result = build_alerts(
            positions,
            concentration_data=_default_concentration_data(positions),
            data_quality_data={
                **_default_data_quality_data(),
                "maturity_by_isin": {"B1": "2030-01-01"},
                "rating_by_isin": {"B1": "AA(RU)"},
                "cost_basis": {"B1": {"avg_price": 100.0}},
                "issuer_by_isin": {"B1": "Issuer A"},
            },
            as_of_date=date(2026, 5, 2),
        )
        self.assertEqual(len(_rule_alerts(result.data_alerts, "missing_ytm")), 1)

    def test_missing_ytm_does_not_trigger_for_stock(self):
        positions = [
            {"name": "SBER", "isin": "RU0009029540", "asset_type": "stock", "position_share": 0.02},
        ]
        result = build_alerts(
            positions,
            concentration_data=_default_concentration_data(positions),
            data_quality_data={
                **_default_data_quality_data(),
                "cost_basis": {"RU0009029540": {"avg_price": 280.0}},
                "issuer_by_isin": {"RU0009029540": "Сбербанк"},
            },
            as_of_date=date(2026, 5, 2),
        )
        self.assertEqual(_rule_alerts(result.data_alerts, "missing_ytm"), [])

    def test_missing_ytm_does_not_trigger_for_etf(self):
        positions = [
            {"name": "ETF X", "isin": "ETF1", "asset_type": "etf", "position_share": 0.02},
        ]
        result = build_alerts(
            positions,
            concentration_data=_default_concentration_data(positions),
            data_quality_data={
                **_default_data_quality_data(),
                "cost_basis": {"ETF1": {"avg_price": 10.0}},
                "issuer_by_isin": {"ETF1": "Management Co"},
            },
            as_of_date=date(2026, 5, 2),
        )
        self.assertEqual(_rule_alerts(result.data_alerts, "missing_ytm"), [])

    def test_missing_maturity_only_for_bonds(self):
        positions = [
            {"name": "Bond A", "isin": "B2", "asset_type": "bond_corp", "position_share": 0.02},
            {"name": "Stock A", "isin": "S2", "asset_type": "stock", "position_share": 0.02},
        ]
        result = build_alerts(
            positions,
            concentration_data=_default_concentration_data(positions),
            data_quality_data={
                **_default_data_quality_data(),
                "rating_by_isin": {"B2": "AA(RU)"},
                "cost_basis": {"B2": {"avg_price": 100.0}, "S2": {"avg_price": 50.0}},
                "issuer_by_isin": {"B2": "Issuer B", "S2": "Issuer S"},
            },
            as_of_date=date(2026, 5, 2),
        )
        alerts = _rule_alerts(result.data_alerts, "missing_maturity")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].isin, "B2")

    def test_missing_rating_is_warning(self):
        positions = [
            {"name": "Bond R", "isin": "BR", "asset_type": "bond_corp", "position_share": 0.02},
        ]
        result = build_alerts(
            positions,
            concentration_data=_default_concentration_data(positions),
            data_quality_data={
                **_default_data_quality_data(),
                "maturity_by_isin": {"BR": "2030-01-01"},
                "cost_basis": {"BR": {"avg_price": 100.0}},
                "issuer_by_isin": {"BR": "Issuer R"},
            },
            as_of_date=date(2026, 5, 2),
        )
        alerts = _rule_alerts(result.data_alerts, "missing_rating")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].severity, "warning")


class AlertsRiskRulesTests(unittest.TestCase):
    def test_concentration_position_thresholds(self):
        positions = [
            {"name": "C15", "isin": "C15", "asset_type": "stock", "position_share": 0.15},
            {"name": "W10", "isin": "W10", "asset_type": "stock", "position_share": 0.10},
            {"name": "I07", "isin": "I07", "asset_type": "stock", "position_share": 0.07},
        ]
        result = build_alerts(
            positions,
            concentration_data=_default_concentration_data(positions),
            data_quality_data=_default_data_quality_data(),
            as_of_date=date(2026, 5, 2),
        )
        by_isin = {row.isin: row for row in _rule_alerts(result.risk_alerts, "concentration_position")}
        self.assertEqual(by_isin["C15"].severity, "critical")
        self.assertEqual(by_isin["W10"].severity, "warning")
        self.assertEqual(by_isin["I07"].severity, "info")

    def test_concentration_position_boundary_149_is_warning(self):
        positions = [
            {"name": "Pos149", "isin": "P149", "asset_type": "stock", "position_share": 0.149},
        ]
        result = build_alerts(
            positions,
            concentration_data=_default_concentration_data(positions),
            data_quality_data=_default_data_quality_data(),
            as_of_date=date(2026, 5, 2),
        )
        alerts = _rule_alerts(result.risk_alerts, "concentration_position")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].severity, "warning")

    def test_loss_thresholds_and_profit_ignored(self):
        positions = [
            {"name": "Loss25", "isin": "L25", "asset_type": "stock", "position_share": 0.02, "pnl_pct": -25.0},
            {"name": "Loss15", "isin": "L15", "asset_type": "stock", "position_share": 0.02, "pnl_pct": -15.0},
            {"name": "Loss05", "isin": "L05", "asset_type": "stock", "position_share": 0.02, "pnl_pct": -5.0},
            {"name": "Profit30", "isin": "P30", "asset_type": "stock", "position_share": 0.02, "pnl_pct": 30.0},
        ]
        result = build_alerts(
            positions,
            concentration_data=_default_concentration_data(positions),
            data_quality_data=_default_data_quality_data(),
            as_of_date=date(2026, 5, 2),
        )
        by_isin = {row.isin: row for row in _rule_alerts(result.risk_alerts, "loss_position")}
        self.assertEqual(by_isin["L25"].severity, "critical")
        self.assertEqual(by_isin["L15"].severity, "warning")
        self.assertNotIn("L05", by_isin)
        self.assertNotIn("P30", by_isin)

    def test_maturity_soon_thresholds(self):
        as_of = date(2026, 5, 2)
        positions = [
            {"name": "M25", "isin": "M25", "asset_type": "bond_corp", "position_share": 0.02},
            {"name": "M60", "isin": "M60", "asset_type": "bond_corp", "position_share": 0.02},
            {"name": "M120", "isin": "M120", "asset_type": "bond_corp", "position_share": 0.02},
        ]
        result = build_alerts(
            positions,
            concentration_data=_default_concentration_data(positions),
            data_quality_data={
                **_default_data_quality_data(),
                "maturity_by_isin": {
                    "M25": (as_of + timedelta(days=25)).isoformat(),
                    "M60": (as_of + timedelta(days=60)).isoformat(),
                    "M120": (as_of + timedelta(days=120)).isoformat(),
                },
            },
            as_of_date=as_of,
        )
        by_isin = {row.isin: row for row in _rule_alerts(result.risk_alerts, "maturity_soon")}
        self.assertEqual(by_isin["M25"].severity, "critical")
        self.assertEqual(by_isin["M60"].severity, "warning")
        self.assertNotIn("M120", by_isin)


class AlertsSplitAndSortingTests(unittest.TestCase):
    def test_same_position_produces_risk_and_data_alerts(self):
        positions = [
            {"name": "Seligdar", "isin": "SLD", "asset_type": "bond_corp", "position_share": 0.15},
        ]
        result = build_alerts(
            positions,
            concentration_data=_default_concentration_data(positions),
            data_quality_data={
                **_default_data_quality_data(),
                "maturity_by_isin": {"SLD": "2030-01-01"},
                "rating_by_isin": {"SLD": "AA(RU)"},
                "cost_basis": {"SLD": {"avg_price": 100.0}},
                "issuer_by_isin": {"SLD": "Issuer S"},
            },
            as_of_date=date(2026, 5, 2),
        )
        self.assertTrue(any(row.rule_code == "concentration_position" for row in result.risk_alerts))
        self.assertTrue(any(row.rule_code == "missing_ytm" for row in result.data_alerts))

    def test_sorting_by_severity_then_sort_key(self):
        positions = [
            {"name": "CritLow", "isin": "CL", "asset_type": "stock", "position_share": 0.15},
            {"name": "CritHigh", "isin": "CH", "asset_type": "stock", "position_share": 0.20},
            {"name": "Warn", "isin": "W", "asset_type": "stock", "position_share": 0.11},
            {"name": "Info", "isin": "I", "asset_type": "stock", "position_share": 0.07},
        ]
        result = build_alerts(
            positions,
            concentration_data=_default_concentration_data(positions),
            data_quality_data=_default_data_quality_data(),
            as_of_date=date(2026, 5, 2),
        )
        concentration_alerts = _rule_alerts(result.risk_alerts, "concentration_position")
        ordered_isins = [row.isin for row in concentration_alerts]
        self.assertEqual(ordered_isins[:2], ["CH", "CL"])
        self.assertEqual(ordered_isins[2], "W")
        self.assertEqual(ordered_isins[3], "I")


class AlertsEdgeCasesTests(unittest.TestCase):
    def test_empty_portfolio_returns_empty_result(self):
        result = build_alerts(
            [],
            concentration_data={},
            data_quality_data={},
            as_of_date=date(2026, 5, 2),
        )
        self.assertEqual(result.data_alerts, [])
        self.assertEqual(result.risk_alerts, [])
        self.assertEqual(result.summary["data_total"], 0)
        self.assertEqual(result.summary["risk_total"], 0)

    def test_missing_asset_type_does_not_crash_and_no_missing_ytm(self):
        positions = [
            {"name": "Unknown", "isin": "UNK", "position_share": 0.02},
        ]
        result = build_alerts(
            positions,
            concentration_data=_default_concentration_data(positions),
            data_quality_data=_default_data_quality_data(),
            as_of_date=date(2026, 5, 2),
        )
        self.assertEqual(_rule_alerts(result.data_alerts, "missing_ytm"), [])


if __name__ == "__main__":
    unittest.main()
