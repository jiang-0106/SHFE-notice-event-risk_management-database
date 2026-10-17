from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_market_research_assistant_v016 as build  # noqa: E402
import run_market_research_assistant as app  # noqa: E402


DB = Path(
    r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE市场研究助手_v0.20_20261017"
    r"\SHFE公告参数市场研究助手_v0.20.sqlite3"
)


class V020UnitTests(unittest.TestCase):
    def test_date_normalization(self) -> None:
        self.assertEqual(build.compact_date("2023-12-15"), "20231215")
        self.assertEqual(build.compact_date("20231215"), "20231215")

    def test_bilingual_product_names(self) -> None:
        self.assertEqual(build.PRODUCT_NAMES["AO"], ("Alumina", "氧化铝"))
        self.assertEqual(build.PRODUCT_NAMES["EC"][1], "集运指数（欧线）")


@unittest.skipUnless(DB.is_file(), "v0.20 artifact not built")
class V020ArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(DB)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self) -> None:
        self.conn.close()

    def test_verified_evidence_counts(self) -> None:
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM verified_real_world_event_ec_sn").fetchone()[0], 59)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM verified_event_policy_chain_ec_sn").fetchone()[0], 47)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM notice_parameter_market_real_event_master").fetchone()[0], 71)

    def test_master_is_complete_and_api_exposes_it(self) -> None:
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM notice_parameter_market_real_event_master WHERE matched_market_trade_date IS NULL").fetchone()[0],
            0,
        )
        payload = app.product_payload(self.conn, "EC", 120)
        self.assertEqual(len(payload["event_master"]), 15)
        self.assertTrue(any(row["real_event_link_status"] == "verified_real_event_chain_link" for row in payload["event_master"]))
        self.assertIn("notice_market_real_event_correspondence", payload["ai_context"])


if __name__ == "__main__":
    unittest.main()
