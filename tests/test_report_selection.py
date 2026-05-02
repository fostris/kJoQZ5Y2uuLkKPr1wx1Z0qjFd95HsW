import unittest

from report_selection import resolve_default_report_id, should_switch_to_new_report


class ReportSelectionTests(unittest.TestCase):
    def test_resolve_default_report_id_empty(self):
        self.assertIsNone(resolve_default_report_id([]))

    def test_resolve_default_report_id_max_period_end(self):
        reports = [
            {"id": 10, "period_end": "01.03.2026"},
            {"id": 11, "period_end": "22.04.2026"},
            {"id": 12, "period_end": "28.02.2026"},
        ]
        self.assertEqual(resolve_default_report_id(reports), 11)

    def test_resolve_default_report_id_same_period_end_uses_max_id(self):
        reports = [
            {"id": 20, "period_end": "22.04.2026"},
            {"id": 25, "period_end": "22.04.2026"},
            {"id": 24, "period_end": "22.04.2026"},
        ]
        self.assertEqual(resolve_default_report_id(reports), 25)

    def test_should_switch_when_newer(self):
        self.assertTrue(should_switch_to_new_report("22.04.2026", "15.04.2026"))

    def test_should_not_switch_when_older(self):
        self.assertFalse(should_switch_to_new_report("01.03.2026", "22.04.2026"))

    def test_should_switch_when_db_was_empty(self):
        self.assertTrue(should_switch_to_new_report("22.04.2026", None))

    def test_should_switch_when_dates_equal(self):
        self.assertTrue(should_switch_to_new_report("22.04.2026", "22.04.2026"))


if __name__ == "__main__":
    unittest.main()
