from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path


DB = Path(
    r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE市场研究助手_v0.21_20261017"
    r"\SHFE公告参数市场研究助手_v0.21.sqlite3"
)


@unittest.skipUnless(DB.is_file(), "v0.21 artifact not built")
class V021EvidenceQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(DB)

    def tearDown(self) -> None:
        self.conn.close()

    def test_parameter_rows_and_unique_policy_events_are_separate(self) -> None:
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM notice_parameter_market_real_event_master").fetchone()[0], 71)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM unique_policy_event_summary").fetchone()[0], 51)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(DISTINCT unique_policy_event_id) FROM unique_policy_event_summary").fetchone()[0],
            51,
        )

    def test_all_four_windows_and_overlap_audits_exist(self) -> None:
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM policy_market_window_statistics").fetchone()[0], 204)
        self.assertEqual(
            {row[0] for row in self.conn.execute("SELECT DISTINCT window_trading_days FROM policy_market_window_statistics")},
            {1, 5, 10, 20},
        )
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM policy_event_overlap_audit").fetchone()[0], 51)

    def test_evidence_fields_and_bilingual_types_are_complete(self) -> None:
        missing = self.conn.execute(
            """SELECT COUNT(*) FROM notice_parameter_market_real_event_master
               WHERE evidence_grade IS NULL OR evidence_status IS NULL OR mentor_review_status IS NULL
                  OR policy_event_type_en IS NULL OR policy_event_type_en=''
                  OR policy_event_type_cn IS NULL OR policy_event_type_cn=''
                  OR policy_event_type_cn=policy_event_type_code"""
        ).fetchone()[0]
        self.assertEqual(missing, 0)
        invalid_grade = self.conn.execute(
            "SELECT COUNT(*) FROM notice_parameter_market_real_event_master WHERE evidence_grade NOT IN ('A','B','C','U','NA')"
        ).fetchone()[0]
        self.assertEqual(invalid_grade, 0)

    def test_ao_bu_screening_and_routine_classification(self) -> None:
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ao_bu_real_event_evidence").fetchone()[0], 5)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ao_bu_policy_event_evidence_link").fetchone()[0], 8)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM unique_policy_event_summary WHERE real_event_link_status='routine_contract_lifecycle_policy'").fetchone()[0],
            2,
        )

    def test_database_integrity(self) -> None:
        self.assertEqual(self.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")


if __name__ == "__main__":
    unittest.main()
