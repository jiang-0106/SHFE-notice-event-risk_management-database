import sqlite3
import unittest
from pathlib import Path

from scripts import run_market_research_assistant as app


ROOT = Path(__file__).resolve().parents[1]
DB = Path(r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE市场研究助手_v0.26_20261021\SHFE公告参数市场研究助手_v0.26.sqlite3")


class V027SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "web" / "market_research_assistant.html").read_text(encoding="utf-8")
        cls.server = (ROOT / "scripts" / "run_market_research_assistant.py").read_text(encoding="utf-8")

    def test_full_history_filters_pagination_and_export_are_wired(self):
        for marker in ('id="intenseMinScore"', 'id="applyIntenseFilter"', 'id="intensePrev"',
                       'id="intenseNext"', "loadIntenseDays", "/api/intense-days",
                       "/api/export/intense-days"):
            self.assertTrue(marker in self.html or marker in self.server, marker)

    def test_parameter_scope_filter_is_present(self):
        for marker in ('id="parameterScope"', "selectedParameterRows", "renderParameterScope"):
            self.assertIn(marker, self.html)

    def test_png_export_adds_report_metadata(self):
        for marker in ("数据截止日", "导出日", "不构成投资建议", "report.height=source.height+112"):
            self.assertIn(marker, self.html)


@unittest.skipUnless(DB.is_file(), "v0.26 database artifact not available")
class V027FullHistoryQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = sqlite3.connect(DB)
        cls.conn.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_query_is_paginated_but_counts_complete_history(self):
        result = app.intense_days_page(self.conn, "AO", page=1, page_size=5)
        self.assertEqual(len(result["rows"]), 5)
        self.assertGreater(result["total"], len(result["rows"]))
        self.assertGreaterEqual(result["total_pages"], 2)

    def test_extreme_and_score_filters_are_applied(self):
        result = app.intense_days_page(self.conn, "AO", level="extreme", min_score=95, export_all=True)
        self.assertTrue(all(row["intensity_level"] == "extreme" for row in result["rows"]))
        self.assertTrue(all(row["composite_intensity_score"] >= 95 for row in result["rows"]))
        self.assertEqual(result["total"], len(result["rows"]))

    def test_invalid_filter_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "level"):
            app.intense_days_page(self.conn, "AO", level="unknown")
        with self.assertRaisesRegex(ValueError, "结束日期"):
            app.intense_days_page(self.conn, "AO", start_date="20260102", end_date="20260101")


if __name__ == "__main__":
    unittest.main()
