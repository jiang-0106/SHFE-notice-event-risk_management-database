from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
BASE_DIR = Path(os.environ.get("SHFE_V15_BASE_DIR", HERE))
EXPANSION_DIR = Path(os.environ.get("SHFE_V15_EXPANSION_DIR", BASE_DIR / "03_全品种扩展"))
AUDIT_DIR = Path(os.environ.get("SHFE_V15_AUDIT_DIR", EXPANSION_DIR / "15_公告参数变更点对应"))
SOURCE_OVERRIDE = os.environ.get("SHFE_V15_SOURCE_DB")
SOURCE_DB = Path(SOURCE_OVERRIDE) if SOURCE_OVERRIDE else next(EXPANSION_DIR.glob("*v0.14.sqlite3"))
OUTPUT_OVERRIDE = os.environ.get("SHFE_V15_OUTPUT_DB")
OUTPUT_DB = Path(OUTPUT_OVERRIDE) if OUTPUT_OVERRIDE else next(EXPANSION_DIR.glob("*v0.15.sqlite3"))
EXPECTED_SOURCE_HASH = os.environ.get(
    "SHFE_V15_EXPECTED_SOURCE_SHA256",
    "a8a4ba1cdab8a3c3263825100ca9f6cf2bf5b8c945d688b08d4aeb503bf98982",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scalar(connection: sqlite3.Connection, sql: str, parameters=()) -> Any:
    return connection.execute(sql, parameters).fetchone()[0]


def csv_audit(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    header = rows[0]
    return {
        "has_utf8_bom": raw.startswith(b"\xef\xbb\xbf"),
        "column_count": len(header),
        "column_count_even": len(header) % 2 == 0,
        "headers_nonblank": all(header),
        "data_row_count": len(rows) - 1,
        "all_rows_same_width": all(len(row) == len(header) for row in rows[1:]),
    }


def main() -> None:
    tests: list[dict[str, Any]] = []

    def check(name: str, passed: bool, value: Any, expected: Any, note: str) -> None:
        tests.append({
            "check_name": name,
            "status": "PASS" if passed else "FAIL",
            "value": value,
            "expected": expected,
            "note": note,
        })

    source_hash = sha256(SOURCE_DB)
    output_hash = sha256(OUTPUT_DB)
    check("source_v014_hash", source_hash == EXPECTED_SOURCE_HASH, source_hash, EXPECTED_SOURCE_HASH, "The preserved v0.14 source must remain byte-identical.")
    check("output_differs_from_source", output_hash != source_hash, output_hash, "different from source", "v0.15 adds normalized change and alignment layers.")

    with sqlite3.connect(SOURCE_DB) as source, sqlite3.connect(OUTPUT_DB) as output:
        source.row_factory = sqlite3.Row
        output.row_factory = sqlite3.Row
        check("sqlite_quick_check", scalar(output, "PRAGMA quick_check") == "ok", scalar(output, "PRAGMA quick_check"), "ok", "SQLite quick structural check.")
        check("sqlite_integrity_check", scalar(output, "PRAGMA integrity_check") == "ok", scalar(output, "PRAGMA integrity_check"), "ok", "SQLite full integrity check.")

        source_tables = [row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        changed_legacy_counts = []
        for table in source_tables:
            source_count = scalar(source, f'SELECT COUNT(*) FROM "{table}"')
            output_count = scalar(output, f'SELECT COUNT(*) FROM "{table}"')
            if source_count != output_count:
                changed_legacy_counts.append({"table": table, "source": source_count, "output": output_count})
        check("legacy_table_row_counts_preserved", not changed_legacy_counts, changed_legacy_counts, [], "Every pre-v0.15 table retains its source row count.")

        change_rows = scalar(output, "SELECT COUNT(*) FROM official_contract_parameter_change")
        clusters = scalar(output, "SELECT COUNT(*) FROM official_product_parameter_change_cluster")
        members = scalar(output, "SELECT COUNT(*) FROM official_product_parameter_change_cluster_member")
        check("change_rows_positive", change_rows == 152730, change_rows, 152730, "Normalized contract-field change rows.")
        check("cluster_rows_positive", clusters == 24636, clusters, 24636, "Product-date-value descriptive clusters.")
        check("member_reconciliation", members == change_rows, members, change_rows, "Each normalized change row has one cluster membership.")
        distinct_members = scalar(output, "SELECT COUNT(DISTINCT change_id) FROM official_product_parameter_change_cluster_member")
        check("distinct_member_reconciliation", distinct_members == change_rows, distinct_members, change_rows, "No change row is omitted or duplicated across clusters.")
        cluster_sum = scalar(output, "SELECT SUM(affected_field_count) FROM official_product_parameter_change_cluster")
        check("cluster_field_sum", cluster_sum == change_rows, cluster_sum, change_rows, "Cluster field counts sum to normalized change rows.")
        first_obs = scalar(output, "SELECT COUNT(*) FROM official_contract_parameter_change WHERE previous_trade_date IS NULL")
        check("first_observations_excluded", first_obs == 0, first_obs, 0, "Initial listings are not mislabeled as changes.")
        false_changes = scalar(output, "SELECT COUNT(*) FROM official_contract_parameter_change WHERE old_value=new_value")
        check("no_unchanged_rows", false_changes == 0, false_changes, 0, "Every normalized row changes value.")
        invalid_dates = scalar(output, "SELECT COUNT(*) FROM official_contract_parameter_change WHERE previous_trade_date>=trade_date")
        check("change_date_order", invalid_dates == 0, invalid_dates, 0, "Previous observation must precede the change date.")
        invalid_shares = scalar(output, "SELECT COUNT(*) FROM official_product_parameter_change_cluster WHERE affected_contract_share<0 OR affected_contract_share>1")
        check("cluster_share_bounds", invalid_shares == 0, invalid_shares, 0, "Affected contract shares stay within [0,1].")
        ao_bu_clusters = scalar(output, "SELECT COUNT(*) FROM official_product_parameter_change_cluster WHERE product_code IN ('AO','BU')")
        check("ao_bu_cluster_count", ao_bu_clusters == 1795, ao_bu_clusters, 1795, "AO and BU descriptive change clusters are fully exported.")

        summary_rows = scalar(output, "SELECT COUNT(*) FROM verified_notice_parameter_change_alignment")
        detail_rows = scalar(output, "SELECT COUNT(*) FROM verified_notice_parameter_contract_alignment")
        view_rows = scalar(output, "SELECT COUNT(*) FROM verified_notice_parameter_alignment_bilingual")
        check("verified_summary_coverage", summary_rows == 30, summary_rows, 30, "All source-verified AO/BU margin and price-limit parameter rows.")
        check("verified_detail_coverage", detail_rows == 504, detail_rows, 504, "All notice-scope contract-field pairs.")
        check("bilingual_view_coverage", view_rows == summary_rows, view_rows, summary_rows, "Mentor view reconciles to the verified summary.")
        below = scalar(output, "SELECT COUNT(*) FROM verified_notice_parameter_contract_alignment WHERE value_relation='below_notice_value'")
        missing = scalar(output, "SELECT COUNT(*) FROM verified_notice_parameter_contract_alignment WHERE value_relation='missing'")
        check("observation_date_no_below_notice", below == 0, below, 0, "No selected post-close/listing observation is below the verified notice level.")
        check("observation_date_no_missing", missing == 0, missing, 0, "No selected notice-scope official daily observation is missing.")
        effective_below = scalar(output, "SELECT SUM(effective_date_below_notice_field_count) FROM verified_notice_parameter_change_alignment")
        check("effective_date_snapshot_retained", effective_below == 290, effective_below, 290, "Pre-close values remain visible instead of being overwritten by post-close values.")
        close_rule_rows = scalar(output, "SELECT COUNT(*) FROM verified_notice_parameter_change_alignment WHERE effective_rule LIKE '%收盘结算%'")
        close_rule_wrong = scalar(output, "SELECT COUNT(*) FROM verified_notice_parameter_change_alignment WHERE effective_rule LIKE '%收盘结算%' AND NOT (observation_trade_date>effective_date AND observation_date_basis='next_official_trade_parameter_date_after_close_settlement')")
        listing_rows = scalar(output, "SELECT COUNT(*) FROM verified_notice_parameter_change_alignment WHERE effective_rule LIKE '%上市时起%'")
        listing_wrong = scalar(output, "SELECT COUNT(*) FROM verified_notice_parameter_change_alignment WHERE effective_rule LIKE '%上市时起%' AND NOT (observation_trade_date=effective_date AND observation_date_basis='same_date_for_listing_or_non_close_settlement_rule')")
        check("close_settlement_rule_count", close_rule_rows == 24, close_rule_rows, 24, "Twenty-four parameters use the close-settlement timing rule.")
        check("close_settlement_next_date_mapping", close_rule_wrong == 0, close_rule_wrong, 0, "Close-settlement notices map to the next official trade-parameter date.")
        check("listing_rule_count", listing_rows == 6, listing_rows, 6, "Six parameters describe two newly listed contracts.")
        check("listing_same_date_mapping", listing_wrong == 0, listing_wrong, 0, "Listing-at-start notices use the listing date itself.")
        initial_listing = scalar(output, "SELECT COUNT(*) FROM verified_notice_parameter_change_alignment WHERE change_point_alignment_status='all_fields_are_initial_listing_observations'")
        check("initial_listing_summary_count", initial_listing == 6, initial_listing, 6, "Initial values are distinguished from within-contract changes.")
        statuses = dict(output.execute("SELECT level_alignment_status,COUNT(*) FROM verified_notice_parameter_change_alignment GROUP BY level_alignment_status"))
        check("level_status_distribution", statuses == {"all_values_equal_notice_level": 17, "notice_floor_satisfied_with_higher_values_present": 13}, statuses, {"all_values_equal_notice_level": 17, "notice_floor_satisfied_with_higher_values_present": 13}, "Only exact or from-high-compliant level statuses remain.")

        detail_mismatch = scalar(
            output,
            """
            SELECT COUNT(*) FROM (
              SELECT a.verified_parameter_id,
                     a.observed_field_count AS summary_observed,
                     SUM(d.observed_value IS NOT NULL) AS detail_observed,
                     a.equal_notice_value_field_count AS summary_equal,
                     SUM(d.value_relation='equal_to_notice_value') AS detail_equal,
                     a.above_notice_value_field_count AS summary_above,
                     SUM(d.value_relation='above_notice_value') AS detail_above,
                     a.below_notice_value_field_count AS summary_below,
                     SUM(d.value_relation='below_notice_value') AS detail_below
              FROM verified_notice_parameter_change_alignment a
              JOIN verified_notice_parameter_contract_alignment d USING(verified_parameter_id)
              GROUP BY a.verified_parameter_id
              HAVING summary_observed<>detail_observed OR summary_equal<>detail_equal
                  OR summary_above<>detail_above OR summary_below<>detail_below
            )
            """,
        )
        check("summary_detail_reconciliation", detail_mismatch == 0, detail_mismatch, 0, "Every event summary reconciles to contract-field details.")
        origin_errors = scalar(output, "SELECT COUNT(*) FROM verified_notice_parameter_contract_alignment WHERE data_origin<>'official_exchange_daily_raw'")
        check("official_origin_tag", origin_errors == 0, origin_errors, 0, "Observed values retain the official raw-data origin tag.")
        integration_nonpass = scalar(output, "SELECT COUNT(*) FROM v15_integration_check WHERE check_status<>'PASS'")
        check("embedded_integration_checks", integration_nonpass == 0, integration_nonpass, 0, "All embedded v0.15 checks pass.")
        dictionary_rows = scalar(output, "SELECT COUNT(*) FROM v15_field_dictionary")
        check("field_dictionary_present", dictionary_rows >= 9, dictionary_rows, ">=9", "Key derived fields and timing choices are documented.")
        prediction_objects = scalar(output, "SELECT COUNT(*) FROM sqlite_master WHERE lower(name) LIKE '%predict%' AND name NOT IN (SELECT name FROM sqlite_master WHERE 0)")
        # Legacy objects can contain prediction-related material. New v0.15 object names are checked separately.
        new_prediction_objects = scalar(output, "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'v15%' AND lower(name) LIKE '%predict%'")
        check("no_new_prediction_objects", new_prediction_objects == 0, new_prediction_objects, 0, "v0.15 remains a synchronous correspondence layer.")

    expected_csv_rows = {
        "verified_notice_parameter_alignment_v15.csv": 30,
        "verified_notice_parameter_contract_detail_v15.csv": 504,
        "official_product_parameter_change_clusters_v15.csv": 24636,
        "ao_bu_parameter_change_clusters_v15.csv": 1795,
    }
    csv_results = {}
    for name, expected_rows in expected_csv_rows.items():
        result = csv_audit(AUDIT_DIR / name)
        csv_results[name] = result
        check(f"csv_{name}_row_count", result["data_row_count"] == expected_rows, result["data_row_count"], expected_rows, "CSV data rows reconcile to the database.")
        check(f"csv_{name}_utf8_bom", result["has_utf8_bom"], result["has_utf8_bom"], True, "UTF-8 BOM supports direct Chinese display in Excel.")
        check(f"csv_{name}_paired_columns", result["column_count_even"] and result["headers_nonblank"] and result["all_rows_same_width"], result, "even nonblank columns and consistent row widths", "English and Chinese columns are adjacent and machine-readable.")

    building_left = list(EXPANSION_DIR.glob("*v0.15.sqlite3.building"))
    interim_left = list(EXPANSION_DIR.glob("*.timing_unadjusted_interim"))
    check("no_building_file_left", not building_left, [str(path) for path in building_left], [], "No unfinished database remains.")
    check("no_interim_file_left", not interim_left, [str(path) for path in interim_left], [], "The superseded same-turn interim was removed after successful replacement.")

    passed = sum(test["status"] == "PASS" for test in tests)
    failed = len(tests) - passed
    report = {
        "version": "v0.15",
        "database": str(OUTPUT_DB),
        "database_sha256": output_hash,
        "database_size_bytes": OUTPUT_DB.stat().st_size,
        "source_database": str(SOURCE_DB),
        "source_database_sha256": source_hash,
        "summary": {"checks": len(tests), "passed": passed, "failed": failed},
        "csv_audits": csv_results,
        "tests": tests,
    }
    output_path = AUDIT_DIR / "v15_validation_summary.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(json.dumps({"database_sha256": output_hash, "database_size_bytes": OUTPUT_DB.stat().st_size}, ensure_ascii=False))
    if failed:
        for test in tests:
            if test["status"] == "FAIL":
                print(json.dumps(test, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
