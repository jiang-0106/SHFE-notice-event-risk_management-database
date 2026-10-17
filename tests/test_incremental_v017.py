import importlib.util
import sqlite3
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_market_research_assistant_v016.py"
SPEC = importlib.util.spec_from_file_location("market_builder", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)

AUGMENT_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "augment_v019_ec_sn_and_mismatch.py"
AUGMENT_SPEC = importlib.util.spec_from_file_location("v019_augment", AUGMENT_SCRIPT)
AUGMENT = importlib.util.module_from_spec(AUGMENT_SPEC)
assert AUGMENT_SPEC.loader
AUGMENT_SPEC.loader.exec_module(AUGMENT)


class OfficialAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute(
            """
            CREATE TABLE official_data_availability_check (
              requested_date TEXT, dataset TEXT, http_status INTEGER,
              validation_status TEXT, report_date TEXT
            )
            """
        )

    def tearDown(self):
        self.connection.close()

    def test_holiday_404_after_latest_trade_date_is_current(self):
        self.connection.executemany(
            "INSERT INTO official_data_availability_check VALUES (?,?,?,?,?)",
            [
                ("20260930", "market", 200, "valid_saved", "20260930"),
                ("20261001", "market", 404, "official_file_not_available", ""),
                ("20261002", "market", 404, "official_file_not_available", ""),
            ],
        )
        result = MODULE.availability_context(self.connection, "20260930")
        self.assertEqual(result["status"], "current_to_latest_complete_official_available")
        self.assertEqual(result["checked_through"], "20261002")
        self.assertEqual(result["unresolved"], 0)

    def test_network_failure_after_latest_date_is_incomplete(self):
        self.connection.executemany(
            "INSERT INTO official_data_availability_check VALUES (?,?,?,?,?)",
            [
                ("20260930", "market", 200, "valid_saved", "20260930"),
                ("20261001", "market", 0, "http_failure_not_saved", ""),
            ],
        )
        result = MODULE.availability_context(self.connection, "20260930")
        self.assertEqual(result["status"], "availability_check_incomplete")
        self.assertEqual(result["unresolved"], 1)


class V019NormalizationTests(unittest.TestCase):
    def test_episode_id_maps_to_notice_id(self):
        self.assertEqual(AUGMENT.notice_id("t20230907_800754_EC"), "t20230907_800754")
        self.assertEqual(AUGMENT.notice_id("t20240101_123456_SN"), "t20240101_123456")

    def test_common_parameter_text_has_english_counterpart(self):
        translated = AUGMENT.english_values("交易手续费0.1‱→0.5‱；日内开仓上限1000→500手")
        self.assertIn("trading fee", translated)
        self.assertIn("intraday opening limit", translated)
        self.assertIn("lots", translated)


if __name__ == "__main__":
    unittest.main()
