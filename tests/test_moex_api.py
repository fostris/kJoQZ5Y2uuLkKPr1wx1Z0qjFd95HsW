import unittest
from datetime import date
from unittest.mock import patch

import moex_api


class MoexCouponsSecidFallbackTests(unittest.TestCase):
    def test_get_bond_coupons_uses_secid_fallback_for_ofz(self):
        empty_bondization = {
            "coupons": {"columns": ["coupondate"], "data": []},
            "amortizations": {"columns": ["amortdate"], "data": []},
        }
        secid_bondization = {
            "coupons": {
                "columns": ["coupondate", "recorddate", "valueprc", "value", "facevalue", "couponperiod", "name"],
                "data": [["2026-09-16", "2026-09-15", 7.75, 38.64, 1000.0, 23, "ОФЗ 26219"]],
            }
        }

        with patch("moex_api.get_ticker_by_isin", return_value="SU26219RMFS4"), patch(
            "moex_api._fetch_json",
            side_effect=[empty_bondization, secid_bondization],
        ) as fetch_mock:
            coupons = moex_api.get_bond_coupons(
                "RU000A0JWM07",
                from_date=date(2026, 5, 1),
                till_date=date(2028, 9, 16),
            )

        self.assertEqual(len(coupons), 1)
        self.assertEqual(coupons[0].isin, "RU000A0JWM07")
        self.assertEqual(coupons[0].coupon_date, "2026-09-16")
        self.assertAlmostEqual(coupons[0].coupon_amount, 38.64)

        first_url = fetch_mock.call_args_list[0].args[0]
        second_url = fetch_mock.call_args_list[1].args[0]
        self.assertIn("/securities/RU000A0JWM07/bondization.json", first_url)
        self.assertIn("/securities/SU26219RMFS4/bondization.json", second_url)
        self.assertIn("from=2026-05-01", first_url)
        self.assertIn("till=2028-09-16", first_url)

    @patch("moex_api.time.sleep", return_value=None)
    def test_sync_coupons_writes_all_future_coupons_until_maturity(self, _sleep_mock):
        positions = [
            {"isin": "RU000A0JWM07", "name": "ОФЗ 26219", "qty": 9, "asset_type": "bond_ofz_pd"}
        ]
        coupons = [
            moex_api.CouponInfo(
                isin="RU000A0JWM07",
                name="ОФЗ 26219",
                coupon_date="2026-09-16",
                record_date="2026-09-15",
                coupon_rate=7.75,
                coupon_amount=38.64,
                nominal=1000.0,
                coupon_number=23,
            ),
            moex_api.CouponInfo(
                isin="RU000A0JWM07",
                name="ОФЗ 26219",
                coupon_date="2027-03-17",
                record_date="2027-03-16",
                coupon_rate=7.75,
                coupon_amount=38.64,
                nominal=1000.0,
                coupon_number=24,
            ),
        ]

        with patch("moex_api.get_bond_info", return_value={"maturity_date": "2028-09-16"}), patch(
            "moex_api.get_bond_coupons",
            return_value=coupons,
        ) as coupons_mock, patch("moex_api.db.upsert_coupon") as upsert_coupon_mock, patch(
            "moex_api.db.upsert_data_sync_status",
        ):
            stats = moex_api.sync_coupons_for_portfolio(positions, future_only=True)

        self.assertEqual(stats["bonds_processed"], 1)
        self.assertEqual(stats["synced"], 2)
        self.assertEqual(upsert_coupon_mock.call_count, 2)

        first_call = upsert_coupon_mock.call_args_list[0].kwargs
        second_call = upsert_coupon_mock.call_args_list[1].kwargs
        self.assertEqual(first_call["coupon_date"], "2026-09-16")
        self.assertEqual(second_call["coupon_date"], "2027-03-17")
        self.assertAlmostEqual(first_call["expected_income"], 38.64 * 9)
        self.assertAlmostEqual(second_call["expected_income"], 38.64 * 9)

        call_kwargs = coupons_mock.call_args.kwargs
        self.assertEqual(call_kwargs["till_date"], date(2028, 9, 16))
        self.assertEqual(call_kwargs["from_date"], date.today())


if __name__ == "__main__":
    unittest.main()
