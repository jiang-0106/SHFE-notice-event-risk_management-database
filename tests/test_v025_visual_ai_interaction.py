import sqlite3
import unittest
from pathlib import Path

from scripts import run_market_research_assistant as app


ROOT = Path(__file__).resolve().parents[1]
DB = Path(r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE市场研究助手_v0.25_20261021\SHFE公告参数市场研究助手_v0.25.sqlite3")


class V025SourceTests(unittest.TestCase):
    def test_ui_has_component_chart_drilldown_parameter_comparison_and_formatted_ai(self):
        html = (ROOT / "web" / "market_research_assistant.html").read_text(encoding="utf-8")
        for marker in (
            'id="componentChart"', 'id="intenseDayDetail"', 'id="parameterComparison"',
            'id="autoAi"', "renderAiResult", "loadDayContext", "同范围调整前",
        ):
            self.assertIn(marker, html)

    def test_ai_auto_mode_is_opt_in(self):
        html = (ROOT / "web" / "market_research_assistant.html").read_text(encoding="utf-8")
        self.assertNotIn('id="autoAi" type="checkbox" checked', html)
        self.assertIn("auto_ai_default", (ROOT / "scripts" / "run_market_research_assistant.py").read_text(encoding="utf-8"))


@unittest.skipUnless(DB.is_file(), "v0.25 artifact not built")
class V025ContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = sqlite3.connect(DB)
        cls.connection.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def test_intense_day_context_has_metrics_and_auditable_window(self):
        trade_date = self.connection.execute(
            """SELECT trade_date FROM product_trading_intensity_daily
               WHERE product_code='AO' AND intensity_level IN ('intense','extreme')
               ORDER BY trade_date DESC LIMIT 1"""
        ).fetchone()[0]
        result = app.intense_day_context(self.connection, "ao", trade_date)
        self.assertEqual(result["product_code"], "AO")
        self.assertEqual(result["trade_date"], trade_date)
        self.assertIn("composite_intensity_score", result["metrics"])
        self.assertIn("nearby_parameter_changes", result)
        self.assertIn("nearby_notices", result)
        self.assertIn("不表示", result["interpretation_boundary_cn"])

    def test_invalid_day_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "YYYYMMDD"):
            app.intense_day_context(self.connection, "AO", "2026-10-20")


if __name__ == "__main__":
    unittest.main()
