from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_market_research_assistant_v016 as build  # noqa: E402
import run_market_research_assistant as app  # noqa: E402


class MetricTests(unittest.TestCase):
    def test_percentile_uses_only_supplied_history(self):
        self.assertEqual(build.percentile(5.0, [1.0, 2.0, 3.0, 4.0] * 15), 100.0)
        self.assertEqual(build.percentile(0.0, [1.0, 2.0, 3.0, 4.0] * 15), 0.0)

    def test_intensity_threshold_requires_multiple_signals(self):
        self.assertEqual(build.intensity_level(98.0, 4, 252), "extreme")
        self.assertEqual(build.intensity_level(98.0, 2, 252), "active")
        self.assertEqual(build.intensity_level(91.0, 3, 252), "intense")
        self.assertEqual(build.intensity_level(85.0, 2, 252), "active")
        self.assertEqual(build.intensity_level(95.0, 7, 20), "insufficient_history")

    def test_weighted_score_renormalizes_missing_components(self):
        components = {key: None for key in build.WEIGHTS}
        for key in list(components)[:4]:
            components[key] = 80.0
        self.assertAlmostEqual(build.score_components(components), 80.0)


class IntervalTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            """
            CREATE TABLE verified_notice_parameter_change_alignment(
              notice_id TEXT,notice_title TEXT,product_code TEXT,parameter_code TEXT,
              expected_new_value REAL,effective_date TEXT,effective_rule TEXT,
              effective_date_basis TEXT,instrument_scope TEXT
            )
            """
        )
        self.conn.executemany(
            "INSERT INTO verified_notice_parameter_change_alignment VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ("n1", "first", "AO", "price_limit", 0.07, "20250101", "当日", "verified", "all"),
                ("n2", "repeat", "AO", "price_limit", 0.07, "20250110", "当日", "verified", "some"),
                ("n3", "change", "AO", "price_limit", 0.09, "20250201", "当日", "verified", "all"),
            ],
        )
        build.create_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_equal_level_not_split_and_next_level_closes_interval(self):
        self.assertEqual(build.build_intervals(self.conn), 2)
        rows = self.conn.execute(
            "SELECT announced_value,start_date,end_date,source_notice_count FROM notice_parameter_policy_interval ORDER BY start_date"
        ).fetchall()
        self.assertEqual(rows[0], (0.07, "20250101", "20250131", 2))
        self.assertEqual(rows[1], (0.09, "20250201", None, 1))


class IntegrationSmokeTests(unittest.TestCase):
    DB = app.DEFAULT_DB

    @unittest.skipUnless(DB.is_file(), "v0.16 output database not built")
    def test_ao_payload_and_stale_guard(self):
        conn = sqlite3.connect(self.DB)
        conn.row_factory = sqlite3.Row
        try:
            payload = app.product_payload(conn, "AO", 120)
        finally:
            conn.close()
        self.assertEqual(payload["product_code"], "AO")
        self.assertEqual(len(payload["series"]), 120)
        self.assertEqual(payload["snapshot"]["freshness_status"], "stale")
        self.assertIn("不得给出买入", payload["ai_prompt"])

    def test_ai_call_fails_closed_without_key(self):
        old = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with self.assertRaisesRegex(RuntimeError, "未配置OPENAI_API_KEY"):
                app.call_openai({"product_code": "AO"})
        finally:
            if old is not None:
                os.environ["OPENAI_API_KEY"] = old


if __name__ == "__main__":
    unittest.main()
