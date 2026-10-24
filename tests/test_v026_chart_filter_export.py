import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class V026InteractionSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "web" / "market_research_assistant.html").read_text(encoding="utf-8")

    def test_three_charts_have_png_export(self):
        for canvas_id in ("chart", "componentChart", "parameterChart"):
            self.assertIn(f'data-canvas="{canvas_id}"', self.html)
        self.assertIn("function exportChartPng", self.html)

    def test_charts_have_hover_metadata_and_tooltip(self):
        self.assertIn('id="chartTooltip"', self.html)
        self.assertIn("function bindChartInteractions", self.html)
        for chart_id in ("chart", "componentChart", "parameterChart"):
            self.assertIn(f"setChartHover('{chart_id}'", self.html)

    def test_intense_day_filters_and_csv_export_are_present(self):
        for marker in ('id="intenseLevel"', 'id="intenseStart"', 'id="intenseEnd"',
                       'id="exportIntense"', "filteredIntenseDays", "downloadCsv"):
            self.assertIn(marker, self.html)
        self.assertTrue("最近30条异常日" in self.html or "完整历史" in self.html)

    def test_ai_contract_keeps_current_official_defaults(self):
        source = (ROOT / "scripts" / "run_market_research_assistant.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("OPENAI_MODEL", "gpt-6-astra")', source)
        self.assertIn('"https://api.openai.com/v1/responses"', source)
        self.assertIn('"format": {', source)
        self.assertIn('"store": False', source)


if __name__ == "__main__":
    unittest.main()
