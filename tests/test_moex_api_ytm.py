import math
import unittest
from urllib.error import URLError
from unittest.mock import patch

import moex_api


class MoexYtmParsingTests(unittest.TestCase):
    def test_extract_bond_ytm_success_from_marketdata(self):
        data = {
            "marketdata": {
                "columns": ["SECID", "BOARDID", "YIELD", "VALTODAY"],
                "data": [
                    ["SU26219RMFS4", "SPOB", 6.63, 0],
                    ["SU26219RMFS4", "TQOB", 13.45, 14458439],
                ],
            }
        }

        ytm = moex_api.extract_bond_ytm_from_marketdata(data)

        self.assertEqual(ytm, 13.45)

    def test_extract_bond_ytm_missing_field_returns_none(self):
        data = {
            "marketdata": {
                "columns": ["SECID", "BOARDID", "LAST"],
                "data": [["SU26219RMFS4", "TQOB", 98.053]],
            }
        }

        ytm = moex_api.extract_bond_ytm_from_marketdata(data)

        self.assertIsNone(ytm)

    def test_extract_bond_ytm_empty_marketdata_returns_none(self):
        data = {
            "marketdata": {
                "columns": ["SECID", "BOARDID", "YIELD"],
                "data": [],
            }
        }

        ytm = moex_api.extract_bond_ytm_from_marketdata(data)

        self.assertIsNone(ytm)


class MoexYtmFormattingTests(unittest.TestCase):
    def test_format_ytm_value_and_null(self):
        self.assertEqual(moex_api.format_ytm(12.3456), "12.35%")
        self.assertEqual(moex_api.format_ytm(None), "—")
        self.assertEqual(moex_api.format_ytm(math.nan), "—")


class _FakeHttpResponse:
    def __init__(self, payload: str, status: int = 200):
        self._payload = payload.encode("utf-8")
        self.status = status

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class MoexFetchRetryTests(unittest.TestCase):
    @patch("moex_api.time.sleep", return_value=None)
    def test_fetch_json_retries_temporary_error_then_succeeds(self, _sleep_mock):
        with patch(
            "moex_api.urlopen",
            side_effect=[URLError("temporary"), _FakeHttpResponse('{\"ok\": true}')],
        ) as mocked_urlopen:
            result = moex_api._fetch_json("https://example.test")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(mocked_urlopen.call_count, 2)

    @patch("moex_api.time.sleep", return_value=None)
    def test_fetch_json_stops_after_max_retries(self, _sleep_mock):
        with patch(
            "moex_api.urlopen",
            side_effect=URLError("network down"),
        ) as mocked_urlopen:
            result, status, error = moex_api._fetch_json("https://example.test", return_status=True)

        self.assertEqual(result, {})
        self.assertIsNone(status)
        self.assertIn("network down", error)
        self.assertEqual(mocked_urlopen.call_count, moex_api.FETCH_MAX_RETRIES)

    @patch("moex_api.time.sleep", return_value=None)
    def test_fetch_json_does_not_retry_non_retryable_http_error(self, _sleep_mock):
        with patch("moex_api._is_retryable_error", return_value=False), patch(
            "moex_api.urlopen",
            side_effect=URLError("non retryable"),
        ) as mocked_urlopen:
            result = moex_api._fetch_json("https://example.test")

        self.assertEqual(result, {})
        self.assertEqual(mocked_urlopen.call_count, 1)


class MoexDataFreshnessStatusTests(unittest.TestCase):
    def test_get_bond_ytm_by_isin_records_success_status(self):
        with patch("moex_api.get_ticker_by_isin", return_value="SU26219RMFS4"), patch(
            "moex_api.fetch_bond_ytm",
            return_value=13.4,
        ), patch("moex_api.db.upsert_data_sync_status") as upsert_mock:
            result = moex_api.get_bond_ytm_by_isin("RU000A0JX0J2")

        self.assertEqual(result, 13.4)
        upsert_mock.assert_called_once_with(
            data_source=moex_api.MOEX_DATA_SOURCE,
            entity="ytm",
            isin="RU000A0JX0J2",
            status="success",
            error_message=None,
        )

    def test_get_bond_ytm_by_isin_records_error_status_when_missing(self):
        with patch("moex_api.get_ticker_by_isin", return_value="SU26219RMFS4"), patch(
            "moex_api.fetch_bond_ytm",
            return_value=None,
        ), patch("moex_api.db.upsert_data_sync_status") as upsert_mock:
            result = moex_api.get_bond_ytm_by_isin("RU000A0JX0J2")

        self.assertIsNone(result)
        upsert_mock.assert_called_once_with(
            data_source=moex_api.MOEX_DATA_SOURCE,
            entity="ytm",
            isin="RU000A0JX0J2",
            status="error",
            error_message="YTM unavailable from MOEX",
        )

    def test_get_issuer_by_isin_records_error_when_not_found(self):
        with patch("moex_api._search_security_by_isin", return_value=None), patch(
            "moex_api.db.upsert_data_sync_status",
        ) as upsert_mock:
            result = moex_api.get_issuer_by_isin("RU000A0JX0J2")

        self.assertIsNone(result)
        upsert_mock.assert_called_once_with(
            data_source=moex_api.MOEX_DATA_SOURCE,
            entity="issuer",
            isin="RU000A0JX0J2",
            status="error",
            error_message="Issuer card not found in MOEX search",
        )

    @patch("moex_api.time.sleep", return_value=None)
    def test_sync_coupons_records_success_status(self, _sleep_mock):
        positions = [{"isin": "RU000A0JX0J2", "name": "ОФЗ", "qty": 5, "asset_type": "bond_ofz_pd"}]
        with patch("moex_api.get_bond_coupons", return_value=[]), patch(
            "moex_api.db.upsert_data_sync_status",
        ) as upsert_mock:
            stats = moex_api.sync_coupons_for_portfolio(positions, future_only=True)

        self.assertEqual(stats["bonds_processed"], 1)
        upsert_mock.assert_called_with(
            data_source=moex_api.MOEX_DATA_SOURCE,
            entity="coupon",
            isin="RU000A0JX0J2",
            status="success",
            error_message=None,
        )

    @patch("moex_api.time.sleep", return_value=None)
    def test_sync_maturity_records_error_status(self, _sleep_mock):
        positions = [{"isin": "RU000A0JX0J2", "name": "ОФЗ", "qty": 5, "asset_type": "bond_ofz_pd"}]
        with patch("moex_api.get_bond_info", side_effect=RuntimeError("moex error")), patch(
            "moex_api.db.upsert_data_sync_status",
        ) as upsert_mock:
            stats = moex_api.sync_maturity_for_portfolio(positions)

        self.assertEqual(stats["synced"], 0)
        upsert_mock.assert_called_with(
            data_source=moex_api.MOEX_DATA_SOURCE,
            entity="maturity",
            isin="RU000A0JX0J2",
            status="error",
            error_message="moex error",
        )


if __name__ == "__main__":
    unittest.main()
