import unittest

from analytics.ratings import (
    RATING_BUCKET_A,
    RATING_BUCKET_AA,
    RATING_BUCKET_AAA,
    RATING_BUCKET_BBB_OR_LOWER,
    RATING_BUCKET_UNRATED,
    build_rating_distribution,
    classify_rating_bucket,
)


class RatingsAnalyticsTests(unittest.TestCase):
    def test_classify_rating_bucket(self):
        self.assertEqual(classify_rating_bucket("AAA(RU)"), RATING_BUCKET_AAA)
        self.assertEqual(classify_rating_bucket("ruAA+"), RATING_BUCKET_AA)
        self.assertEqual(classify_rating_bucket("A-"), RATING_BUCKET_A)
        self.assertEqual(classify_rating_bucket("BBB"), RATING_BUCKET_BBB_OR_LOWER)
        self.assertEqual(classify_rating_bucket("nr"), RATING_BUCKET_UNRATED)
        self.assertEqual(classify_rating_bucket(""), RATING_BUCKET_UNRATED)

    def test_build_rating_distribution(self):
        positions = [
            {
                "name": "Bond 1",
                "isin": "ISIN1",
                "asset_type": "bond_corp",
                "value_end": 100.0,
                "nkd_end": 0.0,
            },
            {
                "name": "Bond 2",
                "isin": "ISIN2",
                "asset_type": "bond_corp",
                "value_end": 50.0,
                "nkd_end": 0.0,
            },
            {
                "name": "Bond 3",
                "isin": "ISIN3",
                "asset_type": "bond_corp",
                "value_end": 50.0,
                "nkd_end": 0.0,
            },
            {
                "name": "Stock",
                "isin": "STOCK1",
                "asset_type": "stock",
                "value_end": 200.0,
                "nkd_end": 0.0,
            },
        ]
        rating_by_isin = {
            "ISIN1": "AAA",
            "ISIN2": "AA(RU)",
        }

        result = build_rating_distribution(
            positions=positions,
            rating_by_isin=rating_by_isin,
            bond_asset_types=("bond_corp", "bond_ofz_pd", "bond_ofz_in"),
        )

        self.assertAlmostEqual(result["total_bond_value"], 200.0)
        shares = result["share_map"]
        self.assertAlmostEqual(shares[RATING_BUCKET_AAA], 0.5)
        self.assertAlmostEqual(shares[RATING_BUCKET_AA], 0.25)
        self.assertAlmostEqual(shares[RATING_BUCKET_UNRATED], 0.25)
        self.assertEqual(shares[RATING_BUCKET_A], 0.0)
        self.assertEqual(shares[RATING_BUCKET_BBB_OR_LOWER], 0.0)


if __name__ == "__main__":
    unittest.main()

