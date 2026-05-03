import unittest
from datetime import date

from analytics.bonds import DurationResult, WeightedYtmResult
from analytics.target_model import Targets, compute_target_deviations


DEFAULT_TARGETS = Targets(
    position_max_pct=0.07,
    issuer_max_pct=0.10,
    sector_max_pct=0.30,
    duration_min_years=1.5,
    duration_max_years=3.5,
    ytm_min_for_buy=0.16,
    target_monthly_cashflow=0.0,
)


def _duration(duration_years: float | None, coverage: float) -> DurationResult:
    return DurationResult(
        duration_years=duration_years,
        coverage=coverage,
        coverage_value=0.0,
        bonds_total_value=0.0,
        by_isin={},
    )


def _weighted_ytm() -> WeightedYtmResult:
    return WeightedYtmResult(
        ytm=None,
        coverage=0.0,
        coverage_value=0.0,
        bonds_total_value=0.0,
    )


def _compute(
    *,
    positions,
    concentration_data,
    portfolio_total_value=100_000.0,
    duration_years=2.0,
    duration_coverage=1.0,
    sector_by_isin=None,
    asset_type_targets=None,
):
    return compute_target_deviations(
        positions=positions,
        concentration_data=concentration_data,
        duration_result=_duration(duration_years, duration_coverage),
        weighted_ytm_result=_weighted_ytm(),
        issuer_by_isin={},
        sector_by_isin=sector_by_isin or {},
        asset_type_targets=asset_type_targets or {},
        targets=DEFAULT_TARGETS,
        portfolio_total_value=portfolio_total_value,
        as_of_date=date(2026, 5, 3),
    )


class TargetModelConcentrationTests(unittest.TestCase):
    def test_position_concentration_thresholds(self):
        result = _compute(
            positions=[],
            concentration_data={
                "positions": [
                    {"name": "P15", "isin": "ISIN15", "position_share": 0.15},
                    {"name": "P9", "isin": "ISIN9", "position_share": 0.09},
                    {"name": "P75", "isin": "ISIN75", "position_share": 0.075},
                    {"name": "P5", "isin": "ISIN5", "position_share": 0.05},
                ],
                "issuers": [],
                "asset_types": [],
            },
            portfolio_total_value=400_000.0,
        )

        by_name = {row.name: row for row in result.deviations if row.type == "position_concentration"}
        self.assertEqual(set(by_name), {"P15", "P9", "P75"})
        self.assertEqual(by_name["P15"].severity, "critical")
        self.assertEqual(by_name["P9"].severity, "warning")
        self.assertEqual(by_name["P75"].severity, "info")

        self.assertAlmostEqual(by_name["P15"].delta_pp or 0.0, 8.0, places=6)
        self.assertAlmostEqual(by_name["P15"].correction_amount_rub or 0.0, -32_000.0, places=6)

    def test_issuer_concentration_thresholds(self):
        result = _compute(
            positions=[],
            concentration_data={
                "positions": [],
                "issuers": [
                    {"issuer": "I18", "issuer_share": 0.18},
                    {"issuer": "I12", "issuer_share": 0.12},
                    {"issuer": "I105", "issuer_share": 0.105},
                    {"issuer": "I9", "issuer_share": 0.09},
                ],
                "asset_types": [],
            },
            portfolio_total_value=200_000.0,
        )

        by_name = {row.name: row for row in result.deviations if row.type == "issuer_concentration"}
        self.assertEqual(set(by_name), {"I18", "I12", "I105"})
        self.assertEqual(by_name["I18"].severity, "critical")
        self.assertEqual(by_name["I12"].severity, "warning")
        self.assertEqual(by_name["I105"].severity, "info")

    def test_sector_concentration_and_unknown_coverage(self):
        positions = [
            {"name": "Bond A", "isin": "A", "asset_type": "bond_corp", "value_end": 120.0, "nkd_end": 0.0},
            {"name": "Bond B", "isin": "B", "asset_type": "bond_corp", "value_end": 80.0, "nkd_end": 0.0},
            {"name": "Bond C", "isin": "C", "asset_type": "bond_corp", "value_end": 100.0, "nkd_end": 0.0},
        ]
        result = _compute(
            positions=positions,
            concentration_data={"positions": [], "issuers": [], "asset_types": []},
            portfolio_total_value=300.0,
            sector_by_isin={"A": "Финансы", "B": "Финансы", "C": None},
        )

        sector_devs = [row for row in result.deviations if row.type == "sector_concentration"]
        self.assertEqual(len(sector_devs), 1)
        self.assertEqual(sector_devs[0].name, "Финансы")
        self.assertEqual(sector_devs[0].severity, "critical")
        self.assertEqual(result.coverage.sector_unknown_count, 1)
        self.assertAlmostEqual(result.coverage.sector_coverage, 200.0 / 300.0, places=6)

    def test_all_sectors_unknown_means_no_sector_deviations(self):
        positions = [
            {"name": "Bond A", "isin": "A", "asset_type": "bond_corp", "value_end": 120.0, "nkd_end": 0.0},
            {"name": "Bond B", "isin": "B", "asset_type": "bond_corp", "value_end": 80.0, "nkd_end": 0.0},
        ]
        result = _compute(
            positions=positions,
            concentration_data={"positions": [], "issuers": [], "asset_types": []},
            portfolio_total_value=200.0,
            sector_by_isin={},
        )

        self.assertFalse(any(row.type == "sector_concentration" for row in result.deviations))
        self.assertEqual(result.coverage.sector_unknown_count, 2)
        self.assertEqual(result.coverage.sector_coverage, 0.0)


class TargetModelDurationTests(unittest.TestCase):
    def test_duration_below_warning_on_half_year_gap(self):
        result = _compute(
            positions=[],
            concentration_data={"positions": [], "issuers": [], "asset_types": []},
            duration_years=1.0,
            duration_coverage=0.8,
        )
        duration_devs = [row for row in result.deviations if row.type == "duration_below"]
        self.assertEqual(len(duration_devs), 1)
        self.assertEqual(duration_devs[0].severity, "warning")
        self.assertAlmostEqual(duration_devs[0].delta_abs, -0.5, places=6)

    def test_duration_above_critical(self):
        result = _compute(
            positions=[],
            concentration_data={"positions": [], "issuers": [], "asset_types": []},
            duration_years=4.5,
            duration_coverage=0.8,
        )
        duration_devs = [row for row in result.deviations if row.type == "duration_above"]
        self.assertEqual(len(duration_devs), 1)
        self.assertEqual(duration_devs[0].severity, "critical")
        self.assertAlmostEqual(duration_devs[0].delta_abs, 1.0, places=6)

    def test_duration_in_range_has_no_deviation(self):
        result = _compute(
            positions=[],
            concentration_data={"positions": [], "issuers": [], "asset_types": []},
            duration_years=2.0,
            duration_coverage=1.0,
        )
        self.assertFalse(any(row.type.startswith("duration_") for row in result.deviations))

    def test_duration_none_has_no_deviation(self):
        result = _compute(
            positions=[],
            concentration_data={"positions": [], "issuers": [], "asset_types": []},
            duration_years=None,
            duration_coverage=0.9,
        )
        self.assertFalse(any(row.type.startswith("duration_") for row in result.deviations))
        self.assertAlmostEqual(result.coverage.duration_coverage, 0.9, places=6)

    def test_duration_coverage_below_half_skips_deviation(self):
        result = _compute(
            positions=[],
            concentration_data={"positions": [], "issuers": [], "asset_types": []},
            duration_years=0.7,
            duration_coverage=0.49,
        )
        self.assertFalse(any(row.type.startswith("duration_") for row in result.deviations))


class TargetModelYtmAndAllocationTests(unittest.TestCase):
    def test_ytm_below_min_for_buy_applies_only_to_bonds(self):
        positions = [
            {"name": "Bond Low", "isin": "B1", "asset_type": "bond_corp", "value_end": 100.0, "ytm": 0.12},
            {"name": "Bond High", "isin": "B2", "asset_type": "bond_ofz_pd", "value_end": 100.0, "ytm": 0.18},
            {"name": "Stock", "isin": "S1", "asset_type": "stock", "value_end": 100.0, "ytm": 0.05},
        ]
        result = _compute(
            positions=positions,
            concentration_data={"positions": [], "issuers": [], "asset_types": []},
            portfolio_total_value=300.0,
        )

        ytm_devs = [row for row in result.deviations if row.type == "ytm_below_min_buy"]
        self.assertEqual(len(ytm_devs), 1)
        self.assertEqual(ytm_devs[0].name, "Bond Low")
        self.assertEqual(ytm_devs[0].severity, "info")

    def test_asset_allocation_with_positive_and_negative_gaps(self):
        result = _compute(
            positions=[],
            concentration_data={
                "positions": [],
                "issuers": [],
                "asset_types": [
                    {"asset_type": "bond_corp", "asset_type_share": 0.75},
                    {"asset_type": "stock", "asset_type_share": 0.05},
                    {"asset_type": "etf", "asset_type_share": 0.20},
                ],
            },
            portfolio_total_value=1_000_000.0,
            asset_type_targets={"bond_corp": 0.60, "stock": 0.15},
        )

        by_name = {row.name: row for row in result.deviations if row.type == "asset_allocation"}
        self.assertEqual(set(by_name), {"bond_corp", "stock"})

        self.assertEqual(by_name["bond_corp"].severity, "critical")
        self.assertAlmostEqual(by_name["bond_corp"].delta_pp or 0.0, 15.0, places=6)
        self.assertAlmostEqual(by_name["bond_corp"].correction_amount_rub or 0.0, -150_000.0, places=6)

        self.assertEqual(by_name["stock"].severity, "critical")
        self.assertAlmostEqual(by_name["stock"].delta_pp or 0.0, -10.0, places=6)
        self.assertAlmostEqual(by_name["stock"].correction_amount_rub or 0.0, 100_000.0, places=6)

    def test_portfolio_total_zero_sets_correction_to_zero(self):
        result = _compute(
            positions=[],
            concentration_data={
                "positions": [{"name": "P", "isin": "P", "position_share": 0.20}],
                "issuers": [],
                "asset_types": [],
            },
            portfolio_total_value=0.0,
        )

        position_dev = [row for row in result.deviations if row.type == "position_concentration"][0]
        self.assertEqual(position_dev.correction_amount_rub, 0.0)


class TargetModelBoundaryAndSortingTests(unittest.TestCase):
    def test_empty_portfolio_returns_empty_deviations(self):
        result = _compute(
            positions=[],
            concentration_data={"positions": [], "issuers": [], "asset_types": []},
            portfolio_total_value=0.0,
            duration_years=None,
            duration_coverage=0.0,
            asset_type_targets={},
        )

        self.assertEqual(result.deviations, [])
        self.assertEqual(result.summary, {"total": 0, "critical": 0, "warning": 0, "info": 0})

    def test_sorting_by_severity_then_type_then_correction(self):
        result = _compute(
            positions=[],
            concentration_data={
                "positions": [
                    {"name": "PosBig", "isin": "P1", "position_share": 0.20},
                    {"name": "PosMid", "isin": "P2", "position_share": 0.15},
                ],
                "issuers": [
                    {"issuer": "Issuer", "issuer_share": 0.25},
                ],
                "asset_types": [
                    {"asset_type": "stock", "asset_type_share": 0.25},
                ],
            },
            portfolio_total_value=100_000.0,
            asset_type_targets={"stock": 0.15},
        )

        critical_rows = [row for row in result.deviations if row.severity == "critical"]
        self.assertGreaterEqual(len(critical_rows), 3)

        # critical + type order: position -> issuer -> asset_allocation
        self.assertEqual(critical_rows[0].type, "position_concentration")
        self.assertEqual(critical_rows[1].type, "position_concentration")
        self.assertEqual(critical_rows[2].type, "issuer_concentration")

        # Within position_concentration sorted by correction magnitude (larger first).
        self.assertEqual(critical_rows[0].name, "PosBig")
        self.assertEqual(critical_rows[1].name, "PosMid")


if __name__ == "__main__":
    unittest.main()
