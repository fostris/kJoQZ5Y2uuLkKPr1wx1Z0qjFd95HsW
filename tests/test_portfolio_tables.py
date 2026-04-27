import unittest
from datetime import date

import pandas as pd

from portfolio_tables import (
    POSITIONS_TABLE_VIEW_MODES,
    get_positions_table_columns,
    prepare_positions_dataset,
    prepare_positions_display_table,
)


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

    def test_get_positions_table_columns_for_modes(self):
        available = [
            "Инструмент",
            "Тип",
            "Эмитент",
            "YTM",
            "Доля портфеля %",
            "Доля эмитента %",
            "Полная стоимость",
            "Δ за день",
            "P&L ₽",
            "P&L %",
        ]

        self.assertIn("Все колонки", POSITIONS_TABLE_VIEW_MODES)
        self.assertIn("Обзор", POSITIONS_TABLE_VIEW_MODES)
        self.assertIn("Качество данных", POSITIONS_TABLE_VIEW_MODES)

        overview_columns = get_positions_table_columns("Обзор", available)
        self.assertEqual(
            overview_columns,
            ["Инструмент", "Тип", "Эмитент", "Доля портфеля %", "Доля эмитента %", "Полная стоимость", "Δ за день"],
        )

        risk_columns = get_positions_table_columns("Риск", available)
        self.assertEqual(
            risk_columns,
            ["Инструмент", "Тип", "Эмитент", "Доля портфеля %", "Доля эмитента %", "YTM", "Полная стоимость"],
        )

    def test_get_positions_table_columns_fallbacks(self):
        available = ["Инструмент", "Тип", "Полная стоимость"]

        unknown_mode_columns = get_positions_table_columns("Неизвестный режим", available)
        self.assertEqual(unknown_mode_columns, available)

        empty_intersection_columns = get_positions_table_columns("Календарь", ["Инструмент"])
        self.assertEqual(empty_intersection_columns, ["Инструмент"])


if __name__ == "__main__":
    unittest.main()
