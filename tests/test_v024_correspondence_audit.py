import sqlite3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_V024 = Path(
    r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE市场研究助手_v0.24_20261021"
    r"\SHFE公告参数市场研究助手_v0.24.sqlite3"
)


class V024SourceTests(unittest.TestCase):
    def test_ui_and_api_expose_bidirectional_audit(self):
        html = (ROOT / "web" / "market_research_assistant.html").read_text(encoding="utf-8")
        server = (ROOT / "scripts" / "run_market_research_assistant.py").read_text(encoding="utf-8")
        for marker in ("公告—参数双向核验", "导出双向核验CSV", "correspondenceAudit"):
            self.assertIn(marker, html)
        self.assertIn("/api/export/correspondence", server)
        self.assertIn("correspondence_summary", server)


@unittest.skipUnless(DB_V024.is_file(), "v0.24 artifact not built")
class V024ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = sqlite3.connect(DB_V024)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def test_integrity_and_expected_tables(self):
        self.assertEqual(self.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        objects = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"notice_parameter_correspondence_audit", "product_correspondence_completeness"} <= objects)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM product_correspondence_completeness").fetchone()[0], 25)

    def test_notice_audit_is_complete_and_corpus_boundaries_are_explicit(self):
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM notice_parameter_correspondence_audit WHERE audit_direction='notice_to_parameter'"
        ).fetchone()[0], 71)
        statuses = dict(self.connection.execute(
            "SELECT notice_corpus_status,COUNT(*) FROM product_correspondence_completeness GROUP BY notice_corpus_status"
        ))
        self.assertEqual(statuses["partial_parameter_level_verified"], 2)
        self.assertEqual(statuses["partial_episode_level_verified"], 2)
        self.assertEqual(statuses["not_built"], 21)
        self.assertEqual(self.connection.execute(
            """SELECT COUNT(*) FROM notice_parameter_correspondence_audit
               WHERE correspondence_status='notice_corpus_not_yet_built' AND review_priority!='corpus_gap'"""
        ).fetchone()[0], 0)

    def test_high_priority_queue_is_recent_all_contract_only(self):
        rows = self.connection.execute(
            """SELECT a.reference_date,c.scope_class
               FROM notice_parameter_correspondence_audit a
               JOIN official_product_parameter_change_cluster c USING(cluster_id)
               WHERE a.review_priority='high'"""
        ).fetchall()
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(date >= "20251020" and scope == "all_active_contracts" for date, scope in rows))
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM notice_parameter_correspondence_audit WHERE review_priority='high' AND audit_direction!='parameter_to_notice'"
        ).fetchone()[0], 0)

    def test_bilingual_explanations_and_exports(self):
        self.assertEqual(self.connection.execute(
            """SELECT COUNT(*) FROM notice_parameter_correspondence_audit
               WHERE explanation_cn='' OR explanation_en='' OR explanation_cn IS NULL OR explanation_en IS NULL"""
        ).fetchone()[0], 0)
        exports = DB_V024.parent / "exports"
        for name in (
            "product_correspondence_completeness_v024.csv",
            "notice_parameter_bidirectional_audit_v024.csv",
            "notice_parameter_review_queue_v024.csv",
        ):
            self.assertTrue((exports / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
