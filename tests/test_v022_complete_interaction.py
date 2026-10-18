import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_market_research_assistant as app  # noqa: E402

DB = Path(r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE市场研究助手_v0.22_20261018\SHFE公告参数市场研究助手_v0.22.sqlite3")


class UserEntryUnitTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(
            """
            CREATE TABLE product_research_snapshot(product_code TEXT PRIMARY KEY);
            INSERT INTO product_research_snapshot VALUES ('AO');
            CREATE TABLE user_notice_entry(
              user_notice_id TEXT PRIMARY KEY,product_code TEXT,notice_title_cn TEXT,notice_title_en TEXT,
              announcement_date TEXT,official_source_url TEXT,event_description_cn TEXT,created_by TEXT,
              review_status TEXT,created_at TEXT,updated_at TEXT);
            CREATE TABLE user_notice_parameter_record(
              record_id TEXT PRIMARY KEY,user_notice_id TEXT,parameter_code TEXT,announced_value REAL,
              value_unit TEXT,start_date TEXT,end_date TEXT,end_date_inclusive INTEGER,instrument_scope TEXT,
              direction_code TEXT,source_excerpt_cn TEXT,notes_cn TEXT);
            CREATE TABLE user_input_audit_log(
              audit_id TEXT PRIMARY KEY,entity_type TEXT,entity_id TEXT,action TEXT,before_json TEXT,
              after_json TEXT,actor TEXT,created_at TEXT);
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_multi_parameter_entry_is_audited(self):
        result = app.create_user_notice(self.conn, {
            "product_code": "ao", "notice_title_cn": "测试公告", "announcement_date": "20261018",
            "created_by": "tester", "parameters": [
                {"parameter_code": "TRADING_MARGIN", "announced_value": 0.12, "value_unit": "ratio", "start_date": "20261019"},
                {"parameter_code": "POSITION_LIMIT", "announced_value": 500, "value_unit": "lots", "start_date": "20261019", "end_date": "20261030"},
            ]})
        self.assertEqual(result["review_status"], "pending_review")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM user_notice_parameter_record").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM user_input_audit_log").fetchone()[0], 1)

    def test_invalid_date_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "结束日不能早于起始日"):
            app.create_user_notice(self.conn, {
                "product_code": "AO", "notice_title_cn": "测试", "announcement_date": "20261018",
                "created_by": "tester", "parameters": [{"parameter_code": "X", "announced_value": 1,
                "start_date": "20261020", "end_date": "20261019"}]})

    def test_stale_data_never_becomes_trade_condition(self):
        result = app.build_trade_research_assessment({
            "database_last_date": "20261015", "freshness_status": "stale_or_incomplete",
            "composite_intensity_score": 99, "liquidity_state": "normal", "risk_state": "high"},
            {"history_count": 100})
        self.assertEqual(result["assessment_code"], "data_unavailable")
        self.assertEqual(result["personalized_trade_suitability"], "not_assessed")

    def test_chinese_high_risk_state_is_watch_only(self):
        result = app.build_trade_research_assessment({
            "database_last_date": "20261015", "freshness_status": "current_to_latest_complete_official_available",
            "composite_intensity_score": 95, "liquidity_state": "偏弱或价格冲击偏高", "risk_state": "高波动风险"},
            {"history_count": 100})
        self.assertEqual(result["assessment_code"], "watch_only_risk_elevated")


@unittest.skipUnless(DB.is_file(), "v0.22 artifact not built")
class V022ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = sqlite3.connect(DB)
        cls.conn.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_database_has_entry_audit_and_combined_interval_view(self):
        objects = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master")}
        self.assertTrue({"user_notice_entry", "user_notice_parameter_record", "user_input_audit_log", "v_all_policy_interval_effective"} <= objects)
        self.assertEqual(self.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_product_payload_has_research_condition(self):
        payload = app.product_payload(self.conn, "AO", 120)
        self.assertIn("trade_research_assessment", payload)
        self.assertEqual(payload["trade_research_assessment"]["personalized_trade_suitability"], "not_assessed")
        self.assertGreater(len(payload["series"]), 0)

    def test_ui_contains_direct_input_entry_and_parameter_chart(self):
        html = (ROOT / "web" / "market_research_assistant.html").read_text(encoding="utf-8")
        for marker in ['list="productOptions"', 'id="saveNotice"', 'id="parameterChart"', 'id="tradeAssessment"']:
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
