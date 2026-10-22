import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import integrate_shfe_incremental_v017 as incremental  # noqa: E402
import run_market_research_assistant as app  # noqa: E402
import update_market_research_assistant_v023 as updater  # noqa: E402

DB_V023 = Path(r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE市场研究助手_v0.23_20261021\SHFE公告参数市场研究助手_v0.23.sqlite3")


class MaintenanceWorkflowTests(unittest.TestCase):
    def test_http_create_review_and_query_flow(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "api.sqlite3"
            connection = sqlite3.connect(database)
            try:
                connection.executescript(
                    """
                    CREATE TABLE product_research_snapshot(product_code TEXT PRIMARY KEY);
                    INSERT INTO product_research_snapshot VALUES ('AO');
                    CREATE TABLE user_notice_entry(
                      user_notice_id TEXT PRIMARY KEY,product_code TEXT,notice_title_cn TEXT,notice_title_en TEXT,
                      announcement_date TEXT,official_source_url TEXT,event_description_cn TEXT,created_by TEXT,
                      review_status TEXT,reviewed_by TEXT,reviewed_at TEXT,review_note TEXT,
                      validation_warnings_json TEXT,record_version INTEGER,created_at TEXT,updated_at TEXT);
                    CREATE TABLE user_notice_parameter_record(
                      record_id TEXT PRIMARY KEY,user_notice_id TEXT,parameter_code TEXT,announced_value REAL,
                      value_unit TEXT,start_date TEXT,end_date TEXT,end_date_inclusive INTEGER,instrument_scope TEXT,
                      direction_code TEXT,source_excerpt_cn TEXT,notes_cn TEXT);
                    CREATE TABLE user_input_audit_log(
                      audit_id TEXT PRIMARY KEY,entity_type TEXT,entity_id TEXT,action TEXT,before_json TEXT,
                      after_json TEXT,actor TEXT,created_at TEXT);
                    CREATE TABLE policy_interval_manual_override(interval_id TEXT PRIMARY KEY);
                    """
                )
                connection.commit()
            finally:
                connection.close()
            app.AppHandler.db_path = database
            app.AppHandler.web_html = b"ok"
            server = ThreadingHTTPServer(("127.0.0.1", 0), app.AppHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                create_body = {
                    "product_code": "AO", "notice_title_cn": "接口测试公告", "announcement_date": "20261021",
                    "official_source_url": "https://www.shfe.com.cn/test", "created_by": "api-tester",
                    "parameters": [{"parameter_code": "MARGIN", "announced_value": 0.12,
                                    "value_unit": "ratio", "start_date": "20261022"}],
                }
                request = urllib.request.Request(base + "/api/notice-entry",
                    data=json.dumps(create_body, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"}, method="POST")
                created = json.loads(urllib.request.urlopen(request, timeout=10).read().decode("utf-8"))
                review_body = {"user_notice_id": created["user_notice_id"], "record_version": 1,
                               "action": "approve", "reviewer": "reviewer", "review_note": "核验通过"}
                request = urllib.request.Request(base + "/api/notice-review",
                    data=json.dumps(review_body, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"}, method="POST")
                reviewed = json.loads(urllib.request.urlopen(request, timeout=10).read().decode("utf-8"))
                queried = json.loads(urllib.request.urlopen(base + "/api/user-notices?product=AO", timeout=10).read().decode("utf-8"))
                self.assertEqual(reviewed["review_status"], "approved")
                self.assertEqual(queried[0]["review_status"], "approved")
                self.assertEqual(len(list(database.parent.glob("api_user_backups/*.json"))), 2)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_small_user_backup_contains_mutable_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "assistant.sqlite3"
            connection = sqlite3.connect(database)
            try:
                connection.executescript(
                    """
                    CREATE TABLE user_notice_entry(user_notice_id TEXT PRIMARY KEY,review_status TEXT);
                    INSERT INTO user_notice_entry VALUES ('USER-1','pending_review');
                    CREATE TABLE user_notice_parameter_record(record_id TEXT PRIMARY KEY,user_notice_id TEXT);
                    INSERT INTO user_notice_parameter_record VALUES ('P-1','USER-1');
                    CREATE TABLE user_input_audit_log(audit_id TEXT PRIMARY KEY);
                    CREATE TABLE policy_interval_manual_override(interval_id TEXT PRIMARY KEY);
                    """
                )
                connection.commit()
            finally:
                connection.close()
            backup = Path(app.backup_user_work(database, "before_review"))
            payload = json.loads(backup.read_text(encoding="utf-8"))
            self.assertEqual(payload["reason"], "before_review")
            self.assertEqual(payload["tables"]["user_notice_entry"][0]["user_notice_id"], "USER-1")
            self.assertLess(backup.stat().st_size, database.stat().st_size * 5)

    def test_incremental_cluster_is_appended_for_new_parameter_change(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            CREATE TABLE official_trade_parameter_daily(
              trade_date TEXT,trade_date_basis TEXT,product_code TEXT,product_code_basis TEXT,
              contract_code TEXT,spec_long_margin_ratio REAL,spec_short_margin_ratio REAL,
              hedge_long_margin_ratio REAL,hedge_short_margin_ratio REAL,upper_limit_ratio REAL,
              lower_limit_ratio REAL,price_limits_raw TEXT,source_update_time TEXT,source_manifest_date TEXT,
              PRIMARY KEY(trade_date,contract_code));
            CREATE TABLE official_product_parameter_change_cluster(
              cluster_id TEXT PRIMARY KEY,trade_date TEXT,product_code TEXT,parameter_code TEXT,
              old_value REAL,new_value REAL,parameter_fields TEXT,affected_contract_codes TEXT,
              affected_contract_count INTEGER,affected_field_count INTEGER,active_contract_count INTEGER,
              affected_contract_share REAL,scope_class TEXT,near_expiry_contract_count INTEGER,
              long_gap_field_count INTEGER,interpretation_limit TEXT,
              UNIQUE(trade_date,product_code,parameter_code,old_value,new_value));
            """
        )
        base = [
            ("20261020", "payload", "AO", "prefix", "ao2611", .10, .10, .09, .09, .08, .08, "", "", "20261020"),
            ("20261021", "payload", "AO", "prefix", "ao2611", .12, .12, .09, .09, .10, .10, "", "", "20261021"),
        ]
        connection.executemany("INSERT INTO official_trade_parameter_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", base)
        count = incremental.append_parameter_change_clusters(connection, {"20261021"})
        self.assertEqual(count, 2)
        codes = {row[0] for row in connection.execute("SELECT parameter_code FROM official_product_parameter_change_cluster")}
        self.assertEqual(codes, {"margin_general", "price_limit"})
        connection.close()

    def test_updater_uses_oldest_of_three_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "source.sqlite3"
            connection = sqlite3.connect(database)
            try:
                for table, last_date in (("market_contract_daily", "20261020"),
                                         ("settlement_parameter_daily", "20261019"),
                                         ("official_trade_parameter_daily", "20261020")):
                    connection.execute(f"CREATE TABLE {table}(trade_date TEXT)")
                    connection.execute(f"INSERT INTO {table} VALUES (?)", (last_date,))
                connection.commit()
            finally:
                connection.close()
            self.assertEqual(updater.latest_complete_source_date(database), "20261019")

    def test_ui_has_review_workbench_and_restore_message(self):
        html = (ROOT / "web" / "market_research_assistant.html").read_text(encoding="utf-8")
        for marker in ("用户录入复核工作台", "/api/notice-review", "/api/notice-update", "恢复包已生成"):
            self.assertIn(marker, html)


@unittest.skipUnless(DB_V023.is_file(), "v0.23 artifact not built")
class V023ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = sqlite3.connect(DB_V023)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def test_integrity_migration_and_indexes(self):
        self.assertEqual(self.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        migrations = {row[0] for row in self.connection.execute("SELECT migration_id FROM research_assistant_schema_migration")}
        self.assertIn("v023_user_review_workflow", migrations)
        indexes = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertTrue({"ix_user_notice_product_status", "ix_user_parameter_notice", "ix_user_audit_entity"} <= indexes)

    def test_three_source_cutoff_is_conservative(self):
        source_dates = [self.connection.execute(f"SELECT MAX(trade_date) FROM {table}").fetchone()[0]
                        for table in ("market_contract_daily", "settlement_parameter_daily", "official_trade_parameter_daily")]
        self.assertEqual(source_dates, ["20261021", "20261020", "20261021"])
        rows = self.connection.execute(
            "SELECT DISTINCT latest_complete_sync_date,availability_checked_through,unresolved_availability_checks FROM product_data_completeness_dashboard"
        ).fetchall()
        self.assertEqual(rows, [("20261020", "20261021", 0)])

    def test_incremental_clusters_and_daily_indicators_updated(self):
        self.assertEqual(self.connection.execute("SELECT MAX(trade_date) FROM product_trading_intensity_daily").fetchone()[0], "20261020")
        self.assertGreaterEqual(self.connection.execute(
            "SELECT COUNT(*) FROM official_product_parameter_change_cluster WHERE cluster_id LIKE 'incremental_cluster_%'"
        ).fetchone()[0], 15)


if __name__ == "__main__":
    unittest.main()
