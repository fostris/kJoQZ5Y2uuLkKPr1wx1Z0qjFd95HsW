import math
import unittest

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


if __name__ == "__main__":
    unittest.main()
