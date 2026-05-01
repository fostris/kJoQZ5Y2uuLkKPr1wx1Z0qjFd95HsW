import unittest

from analytics.fx_exposure import compute_fx_exposure


class FxExposureTests(unittest.TestCase):
    def test_empty_override_all_rub(self):
        positions = [
            {"isin": "RU1", "name": "Bond A", "value": 80.0},
            {"isin": "RU2", "name": "Bond B", "value": 20.0},
        ]
        result = compute_fx_exposure(positions, fx_overrides={})

        self.assertAlmostEqual(result["total_value"], 100.0)
        self.assertAlmostEqual(result["fx_share"], 0.0)
        self.assertAlmostEqual(result["rub_share"], 1.0)
        self.assertAlmostEqual(result["by_currency"]["RUB"], 100.0)

    def test_one_fx_substitute_is_20_percent(self):
        positions = [
            {"isin": "RU1", "name": "Bond A", "value": 80.0},
            {"isin": "RU2", "name": "Bond USD", "value": 20.0},
        ]
        overrides = {
            "RU2": {"currency": "USD", "exposure_type": "fx_substitute"},
        }
        result = compute_fx_exposure(positions, fx_overrides=overrides)

        self.assertAlmostEqual(result["fx_share"], 0.2)
        self.assertAlmostEqual(result["rub_share"], 0.8)
        self.assertAlmostEqual(result["by_currency"]["USD"], 20.0)

    def test_commodity_proxy_not_included_in_fx_share(self):
        positions = [
            {"isin": "RU1", "name": "Rub Bond", "value": 60.0},
            {"isin": "RU2", "name": "USD Subst", "value": 20.0},
            {"isin": "RU3", "name": "Exporter Stock", "value": 20.0},
        ]
        overrides = {
            "RU2": {"currency": "USD", "exposure_type": "fx_substitute"},
            "RU3": {"currency": "USD", "exposure_type": "commodity_proxy"},
        }
        result = compute_fx_exposure(positions, fx_overrides=overrides)

        self.assertAlmostEqual(result["fx_share"], 0.25)
        self.assertIn("commodity_proxy", result["by_exposure_type"])
        self.assertAlmostEqual(result["by_exposure_type"]["commodity_proxy"], 20.0)

    def test_currency_buckets_sum_to_total(self):
        positions = [
            {"isin": "RU1", "name": "RUB", "value": 50.0},
            {"isin": "RU2", "name": "USD", "value": 30.0},
            {"isin": "RU3", "name": "GOLD", "value": 20.0},
        ]
        overrides = {
            "RU2": {"currency": "USD", "exposure_type": "fx_substitute"},
            "RU3": {"currency": "GOLD", "exposure_type": "gold"},
        }
        result = compute_fx_exposure(positions, fx_overrides=overrides)

        self.assertAlmostEqual(sum(result["by_currency"].values()), result["total_value"], places=8)


if __name__ == "__main__":
    unittest.main()
