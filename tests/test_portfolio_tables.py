import unittest
from datetime import date

import pandas as pd

from portfolio_tables import prepare_positions_dataset, prepare_positions_display_table


class PortfolioTablesTests(unittest.TestCase):
    def test_prepare_positions_table_adds_columns_and_keeps_source_unchanged(self):
        pos_df = pd.DataFrame(
            [
                {
                    "name": "Bond A",
                    "asset_type": "bond_corp",
                    "isin": "ISIN1",
                    "qty": 2.0,
                    "price_end": 50.0,
                    "value_end": 100.0,
                    "nkd_end": 10.0,
                    "change_value": 5.0,
                },
                {
                    "name": "Stock B",
                    "asset_type": "stock",
                    "isin": "ISIN2",
                    "qty": 1.0,
                    "price_end": 80.0,
                    "value_end": None,
                    "nkd_end": None,
                    "change_value": -2.0,
                },
            ]
        )
        original = pos_df.copy(deep=True)

        filtered = prepare_positions_dataset(
            pos_df=pos_df,
            type_filter=["bond_corp", "stock"],
            bond_asset_types=("bond_corp", "bond_ofz_pd", "bond_ofz_in"),
            ytm_by_isin={"ISIN1": 12.3},
            issuer_by_isin={"ISIN1": "Issuer A"},
            issuer_share_map={"Issuer A": 0.4},
            position_share_map={"ISIN1": 0.6, "ISIN2": 0.4},
            cost_map={"ISIN1": {"avg_price": 45.0}},
            sort_col="По имени",
            maturity_by_isin={"ISIN1": "2027-04-27"},
            as_of_date=date(2026, 4, 27),
        )

        display_df = prepare_positions_display_table(
            filtered=filtered,
            type_labels={"bond_corp": "Корп. облигации", "stock": "Акции"},
            format_ytm_fn=lambda v: "—" if v is None else f"{v:.2f}%",
        )

        self.assertIn("Полная стоимость", display_df.columns)
        self.assertIn("P&L ₽", display_df.columns)
        self.assertIn("P&L %", display_df.columns)
        self.assertIn("Дней до погашения", display_df.columns)
        self.assertIn("Лет до погашения", display_df.columns)
        self.assertIn("Цена к номиналу %", display_df.columns)
        self.assertIn("Статус к номиналу", display_df.columns)

        bond_row = display_df[display_df["Инструмент"] == "Bond A"].iloc[0]
        self.assertAlmostEqual(bond_row["Полная стоимость"], 110.0)
        self.assertAlmostEqual(bond_row["P&L ₽"], 20.0)
        self.assertAlmostEqual(bond_row["P&L %"], 22.2222222222, places=6)
        self.assertEqual(bond_row["Дней до погашения"], 365)
        self.assertEqual(bond_row["Лет до погашения"], "1.00")
        self.assertEqual(bond_row["Цена к номиналу %"], "50.00")
        self.assertEqual(bond_row["Статус к номиналу"], "discount")

        stock_row = display_df[display_df["Инструмент"] == "Stock B"].iloc[0]
        self.assertTrue(pd.isna(stock_row["Полная стоимость"]))
        self.assertTrue(pd.isna(stock_row["P&L ₽"]))
        self.assertTrue(pd.isna(stock_row["P&L %"]))
        self.assertEqual(stock_row["Дней до погашения"], "нет данных")
        self.assertEqual(stock_row["Лет до погашения"], "нет данных")
        self.assertEqual(stock_row["Цена к номиналу %"], "нет данных")
        self.assertEqual(stock_row["Статус к номиналу"], "нет данных")

        self.assertNotIn("avg_price", pos_df.columns)
        self.assertTrue(pos_df.equals(original))


if __name__ == "__main__":
    unittest.main()
