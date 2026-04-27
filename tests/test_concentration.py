import unittest

import concentration


class ConcentrationMetricsTests(unittest.TestCase):
    def test_calculate_position_shares(self):
        positions = [
            {"name": "A", "asset_type": "stock", "value_end": 100.0, "nkd_end": 0.0},
            {"name": "B", "asset_type": "stock", "value_end": 300.0, "nkd_end": 0.0},
        ]

        rows, total = concentration.calculate_position_shares(positions)

        self.assertEqual(total, 400.0)
        self.assertAlmostEqual(rows[0]["position_share"], 0.25)
        self.assertAlmostEqual(rows[1]["position_share"], 0.75)

    def test_grouping_by_issuer(self):
        positions = [
            {"name": "Bond 1", "isin": "ISIN1", "asset_type": "bond_corp", "value_end": 100.0, "nkd_end": 0.0},
            {"name": "Bond 2", "isin": "ISIN2", "asset_type": "bond_corp", "value_end": 200.0, "nkd_end": 0.0},
            {"name": "Bond 3", "isin": "ISIN3", "asset_type": "bond_corp", "value_end": 300.0, "nkd_end": 0.0},
        ]

        rows, total = concentration.calculate_position_shares(positions)
        issuers, fallback_count = concentration.group_bond_positions_by_issuer(
            rows,
            total,
            issuer_by_isin={
                "ISIN1": "Issuer A",
                "ISIN2": "Issuer A",
                "ISIN3": "Issuer B",
            },
        )

        self.assertEqual(fallback_count, 0)
        self.assertEqual(len(issuers), 2)
        self.assertEqual(issuers[0]["issuer"], "Issuer A")
        self.assertAlmostEqual(issuers[0]["market_value"], 300.0)
        self.assertAlmostEqual(issuers[0]["issuer_share"], 0.5)
        self.assertEqual(issuers[0]["issues_count"], 2)

    def test_hhi_calculation(self):
        hhi = concentration.compute_hhi([0.2, 0.2, 0.2, 0.2, 0.2])
        self.assertAlmostEqual(hhi, 0.2)

    def test_warning_for_position_share_over_limit(self):
        positions = [
            {"name": "Big", "isin": "I1", "asset_type": "stock", "value_end": 150.0, "nkd_end": 0.0},
            {"name": "Small", "isin": "I2", "asset_type": "stock", "value_end": 50.0, "nkd_end": 0.0},
        ]

        metrics = concentration.calculate_concentration_metrics(positions)

        self.assertTrue(any("Позиция 'Big'" in msg for msg in metrics["warnings"]))

    def test_warning_for_issuer_share_over_limit(self):
        positions = [
            {"name": "Bond A", "isin": "ISIN1", "asset_type": "bond_corp", "value_end": 120.0, "nkd_end": 0.0},
            {"name": "Bond B", "isin": "ISIN2", "asset_type": "bond_corp", "value_end": 80.0, "nkd_end": 0.0},
        ]

        metrics = concentration.calculate_concentration_metrics(
            positions,
            issuer_by_isin={"ISIN1": "Issuer X", "ISIN2": "Issuer X"},
        )

        self.assertTrue(any("Эмитент 'Issuer X'" in msg for msg in metrics["warnings"]))

    def test_warning_for_corporate_bonds_share_over_limit(self):
        positions = [
            {"name": "Corp1", "isin": "C1", "asset_type": "bond_corp", "value_end": 80.0, "nkd_end": 0.0},
            {"name": "Corp2", "isin": "C2", "asset_type": "bond_corp", "value_end": 10.0, "nkd_end": 0.0},
            {"name": "Stock", "isin": "S1", "asset_type": "stock", "value_end": 10.0, "nkd_end": 0.0},
        ]

        metrics = concentration.calculate_concentration_metrics(positions)

        self.assertTrue(any("Доля корпоративных облигаций" in msg for msg in metrics["warnings"]))

    def test_empty_portfolio(self):
        metrics = concentration.calculate_concentration_metrics([])

        self.assertEqual(metrics["total_portfolio_value"], 0.0)
        self.assertIsNone(metrics["largest_position_share"])
        self.assertIsNone(metrics["largest_issuer_share"])
        self.assertIsNone(metrics["position_hhi"])
        self.assertIsNone(metrics["issuer_hhi"])
        self.assertEqual(metrics["warnings"], [])

    def test_unknown_issuer_fallback(self):
        positions = [
            {"name": "Bond Unknown", "isin": "UNK", "asset_type": "bond_corp", "value_end": 100.0, "nkd_end": 0.0}
        ]

        metrics = concentration.calculate_concentration_metrics(positions, issuer_by_isin={})

        self.assertEqual(metrics["issuers"][0]["issuer"], "Bond Unknown")
        self.assertEqual(metrics["issuer_fallback_count"], 1)

    def test_severity_levels_for_position_thresholds_5_10_15_20(self):
        items = concentration.build_concentration_warning_items(
            position_rows=[
                {"name": "P5", "position_share": 0.05},
                {"name": "P10", "position_share": 0.10},
                {"name": "P15", "position_share": 0.15},
                {"name": "P20", "position_share": 0.20},
            ],
            issuer_rows=[],
            corporate_bonds_share=None,
            position_hhi=None,
            issuer_hhi=None,
        )

        by_name = {}
        for item in items:
            text = item["text"]
            if "P5" in text:
                by_name["P5"] = item["severity"]
            if "P10" in text:
                by_name["P10"] = item["severity"]
            if "P15" in text:
                by_name["P15"] = item["severity"]
            if "P20" in text:
                by_name["P20"] = item["severity"]

        self.assertEqual(by_name["P5"], "info")
        self.assertEqual(by_name["P10"], "warning")
        self.assertEqual(by_name["P15"], "high")
        self.assertEqual(by_name["P20"], "critical")

    def test_severity_levels_for_issuer_thresholds_5_10_15_20(self):
        items = concentration.build_concentration_warning_items(
            position_rows=[],
            issuer_rows=[
                {"issuer": "I5", "issuer_share": 0.05},
                {"issuer": "I10", "issuer_share": 0.10},
                {"issuer": "I15", "issuer_share": 0.15},
                {"issuer": "I20", "issuer_share": 0.20},
            ],
            corporate_bonds_share=None,
            position_hhi=None,
            issuer_hhi=None,
        )

        by_issuer = {}
        for item in items:
            text = item["text"]
            if "I5" in text:
                by_issuer["I5"] = item["severity"]
            if "I10" in text:
                by_issuer["I10"] = item["severity"]
            if "I15" in text:
                by_issuer["I15"] = item["severity"]
            if "I20" in text:
                by_issuer["I20"] = item["severity"]

        self.assertEqual(by_issuer["I5"], "info")
        self.assertEqual(by_issuer["I10"], "warning")
        self.assertEqual(by_issuer["I15"], "high")
        self.assertEqual(by_issuer["I20"], "critical")

    def test_warning_items_sorted_by_severity(self):
        items = concentration.build_concentration_warning_items(
            position_rows=[
                {"name": "P15", "position_share": 0.15},
                {"name": "P5", "position_share": 0.05},
                {"name": "P20", "position_share": 0.20},
            ],
            issuer_rows=[],
            corporate_bonds_share=None,
            position_hhi=None,
            issuer_hhi=None,
        )

        severities = [item["severity"] for item in items]
        self.assertEqual(severities, ["critical", "high", "info"])

    def test_warning_items_with_same_severity_sorted_by_share(self):
        items = concentration.build_concentration_warning_items(
            position_rows=[
                {"name": "P12", "position_share": 0.12},
                {"name": "P10", "position_share": 0.10},
            ],
            issuer_rows=[],
            corporate_bonds_share=None,
            position_hhi=None,
            issuer_hhi=None,
        )

        texts = [item["text"] for item in items]
        self.assertIn("P12", texts[0])
        self.assertIn("P10", texts[1])

    def test_metrics_expose_warning_items(self):
        positions = [
            {"name": "Big", "isin": "I1", "asset_type": "stock", "value_end": 95.0, "nkd_end": 0.0},
            {"name": "Small", "isin": "I2", "asset_type": "stock", "value_end": 5.0, "nkd_end": 0.0},
        ]

        metrics = concentration.calculate_concentration_metrics(positions)

        self.assertTrue(metrics["warning_items"])
        self.assertIn("severity", metrics["warning_items"][0])
        self.assertIn("text", metrics["warning_items"][0])


if __name__ == "__main__":
    unittest.main()
